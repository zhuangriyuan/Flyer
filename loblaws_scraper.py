"""
Loblaws (loblaws.ca) 本周特价/Flyer 爬虫

依赖：pip install requests

用法：
    python loblaws_scraper.py

输出：
    loblaws_raw.json —— 抓到的原始商品数据

之前那版是"直接 GET 整页 HTML 用 BeautifulSoup 解析"的思路，结果第一页就
抓不到——说明这个页面是纯客户端渲染的（JS 跑完才有商品），plain requests
拿到的是空壳。用户去 F12 抓了实际翻页时前端调的接口，发现跟 No Frills
是同一个后端（Loblaw Companies 旗下几个牌子共用 pcx-bff 这套接口），
所以这版直接照抄 nofrills_scraper.py 的路子，改了这几个跟店/牌子相关的
参数：
    banner:      "loblaw"（注意没有 s，跟网站域名 loblaws.ca 不一样）
    storeId:     "1019"（抓包时用户本地环境绑定的门店）
    pickupType:  "STORE"（抓包实测是这个，不是 nofrills 那边的
                 SELF_SERVE_FULL——大概率是"到店取货"这个配送方式选项
                 不一样，不影响传单价格本身）
    options 里多了一条 bff.exp.flyerIABTest

⚠️ storeId 绑定了具体门店，意味着结果是那家门店的传单。想换门店的话，
去官网切换门店后重新 F12 抓一次 Network 请求，把新的 storeId 换进来。

⚠️ x-apikey 这个值实测跟 nofrills 用的是同一个（Loblaw 几个牌子共用），
不是私密凭证，是网站前端自己嵌在网页里的公开 key。

⚠️ 这个接口返回的商品折扣类型（deal type）不只有 nofrills 那边见过的
SALE/LIMIT，因为这次筛选条件里还带了 "PC Points"/"Member Only Price"/
"Multi-Buy"，字段值具体是什么现在还不确定（没有实际响应样本能看）。所以
这版 parse_tile() 把 dealType 原样存下来，筛不筛/怎么筛放到
loblaws_convert.py 里做，用"有没有 wasPrice 且比现价高"这个更通用的
标准来判断"这条算不算真打折"，不写死只认 SALE 那一种类型，防止把
"Member Only Price"这种筛选条件命中的商品误伤掉。
"""

import json
import re
import shutil
import sys
import time
import uuid
from datetime import datetime
from typing import Optional

import requests

for _stream in (sys.stdout, sys.stderr):
    if hasattr(_stream, "reconfigure"):
        _stream.reconfigure(encoding="utf-8", errors="replace")

API_URL = "https://api.pcexpress.ca/pcx-bff/api/v2/flyersPage"
BASE_URL = "https://www.loblaws.ca"
BANNER = "loblaw"  # 注意没有 s

# 抓包时看到的门店编号，如果想换门店，去浏览器里切换后重新抓一次 Network
# 请求替换掉
STORE_ID = "1019"
PICKUP_TYPE = "STORE"

HEADERS = {
    "Accept": "*/*",
    "Accept-Language": "en",
    "Business-User-Agent": "PCXWEB",
    "Content-Type": "application/json",
    "Origin": "https://www.loblaws.ca",
    "Origin_Session_Header": "B",
    "Referer": "https://www.loblaws.ca/",
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
    ),
    "is-helios-account": "false",
    "is-iceberg-enabled": "true",
    "x-apikey": "C1xujSegT5j3ap3yexJjqhOfELwGKYvz",
    "x-application-type": "Web",
    "x-channel": "web",
    "x-loblaw-tenant-id": "ONLINE_GROCERIES",
    "x-preview": "false",
}

# 抓包抓到的筛选条件，跟之前 HTML 版网址里的 promotions 参数一一对应
PROMOTIONS_FILTERS = [
    "Price Reduction",
    "$1,$2,$3,$4,$5",
    "Multi-Buy",
    "PC Points",
    "Member Only Price",
]

REQUEST_DELAY_SECONDS = 3.0


def build_payload(page_number: int, cart_id: str, domain_user_id: str, session_id: str) -> dict:
    today = datetime.now().strftime("%d%m%Y")  # 抓包看到的格式是 DDMMYYYY
    return {
        "cart": {"cartId": cart_id},
        "fulfillmentInfo": {
            "storeId": STORE_ID,
            "pickupType": PICKUP_TYPE,
            "offerType": "OG",
            "date": today,
            "timeSlot": None,
        },
        "listingInfo": {
            "filters": {"promotions": PROMOTIONS_FILTERS},
            "sort": {},
            "pagination": {"from": page_number},
            "includeFiltersInResponse": True,
        },
        "banner": BANNER,
        "userData": {
            "domainUserId": domain_user_id,
            "sessionId": session_id,
        },
        "options": [
            {"name": "bff.exp.next_gen_active", "value": "variant"},
            {"name": "bff.exp.flyerIABTest", "value": "variant"},
        ],
    }


def parse_money(text: Optional[str]) -> Optional[float]:
    if not text:
        return None
    m = re.search(r"[\d.]+", text)
    return float(m.group()) if m else None


_debug_printed_count = {"n": 0}


def extract_image(tile: dict) -> Optional[str]:
    """真正的字段名是 productImage（不是 image，之前猜错了字段名——2026-08
    最新实测确认，抓包截图里显示的 key 列表里没有 image，只有
    productImage）。这版同时兼容几种可能的数据形状（直接字符串 / 数组 /
    单个对象），实在都不匹配才退回打印诊断信息。
    """
    candidate = tile.get("productImage")

    # 情况1：本来就是一个网址字符串
    if isinstance(candidate, str) and candidate:
        return candidate

    # 情况2：是个数组，元素可能是"带好几种尺寸链接的对象"，也可能元素本身
    # 就是字符串
    if isinstance(candidate, list) and candidate:
        first = candidate[0]
        if isinstance(first, dict):
            got = (
                first.get("mediumUrl") or first.get("smallUrl")
                or first.get("largeUrl") or first.get("imageUrl")
                or first.get("thumbnailUrl") or first.get("url")
            )
            if got:
                return got
        elif isinstance(first, str) and first:
            return first

    # 情况3：不是数组，是单个对象，直接带尺寸字段
    if isinstance(candidate, dict):
        got = (
            candidate.get("mediumUrl") or candidate.get("smallUrl")
            or candidate.get("largeUrl") or candidate.get("imageUrl")
            or candidate.get("thumbnailUrl") or candidate.get("url")
            or candidate.get("src")
        )
        if got:
            return got

    # 🔍 临时诊断：上面几种猜测都没命中，打印 productImage 实际的完整内容
    # （不只是 key，这次要看具体值），确认完问题就可以把这段删掉。
    if _debug_printed_count["n"] < 5:
        _debug_printed_count["n"] += 1
        print(f"[loblaws] 🔍 调试：productImage 的完整内容 = {candidate!r}")

    return None


def parse_tile(tile: dict) -> dict:
    pricing = tile.get("pricing") or {}
    deal = tile.get("deal") or {}
    link = tile.get("link")
    return {
        "productId": tile.get("productId"),
        "title": (tile.get("title") or "").strip(),
        "brand": tile.get("brand"),
        "price": parse_money(pricing.get("displayPrice") or pricing.get("price")),
        "wasPrice": parse_money(pricing.get("wasPrice")),
        "packageSizing": tile.get("packageSizing"),
        "dealType": deal.get("type"),  # SALE / LIMIT / 或者其他没见过的值，原样存下来
        "link": (BASE_URL + link) if link else None,
        "image": extract_image(tile),
    }


def get_all_items() -> list:
    session = requests.Session()
    all_items = []
    page_number = 1  # ⚠️ 跟 nofrills 一样，这个 "from" 大概率是页码本身，不是条目偏移量

    # 整个爬取过程固定用同一套"会话身份"，跟真实浏览器连续翻页的行为一致，
    # 不能每次请求都随机生成新的，不然服务器会认成不同的人，翻页状态接不上
    cart_id = str(uuid.uuid4())
    domain_user_id = str(uuid.uuid4())
    session_id = str(uuid.uuid4())

    while True:
        payload = build_payload(page_number, cart_id, domain_user_id, session_id)
        resp = session.post(API_URL, headers=HEADERS, json=payload, timeout=20)
        print(f"[loblaws] POST page={page_number} -> {resp.status_code}, {len(resp.text)} bytes")
        resp.raise_for_status()
        data = resp.json()

        try:
            product_grid = (
                data["layout"]["sections"]["productListingSection"]["components"][0]
                ["data"]["productGrid"]
            )
        except (KeyError, IndexError, TypeError):
            print("[loblaws] 解析不到 productGrid，接口返回结构可能变了，停止。")
            print("[loblaws] 返回内容前500字符：", resp.text[:500])
            break

        tiles = product_grid.get("productTiles", [])
        pagination = product_grid.get("pagination", {})
        total_results = pagination.get("totalResults", 0)
        has_more = pagination.get("hasMore", False)

        print(f"[loblaws] 本页 {len(tiles)} 个商品，总共 {total_results} 个，hasMore={has_more}")

        items = [parse_tile(t) for t in tiles if t.get("title")]
        all_items.extend(items)

        if not has_more or not tiles:
            break

        page_number += 1
        time.sleep(REQUEST_DELAY_SECONDS)

        if page_number > 150:  # 安全上限（纯粹防止意外死循环，正常靠 hasMore=False 自然停）
            print("[loblaws] 翻页数量超过安全上限，停止。")
            break

    return all_items


if __name__ == "__main__":
    items = get_all_items()
    print(f"\n[loblaws] 共抓到 {len(items)} 个商品")

    # 不像 nofrills 只认 dealType=="SALE"，这里只要有 wasPrice 且比现价高
    # 就算数——这次筛选条件里带了 Member Only Price / Multi-Buy，dealType
    # 具体是什么字符串现在不确定，用价格本身判断更保险，不容易漏。
    discounted = [
        i for i in items
        if i["price"] is not None and i["wasPrice"] is not None and i["wasPrice"] > i["price"]
    ]
    print(f"[loblaws] 其中有 wasPrice 且比现价高（算真打折）的有 {len(discounted)} 个")
    if items:
        deal_types = {}
        for i in items:
            deal_types[i["dealType"]] = deal_types.get(i["dealType"], 0) + 1
        print(f"[loblaws] dealType 分布：{deal_types}（如果里面有没见过的类型，"
              f"去 loblaws_convert.py 里检查一下要不要针对性处理）")

    if items:
        print("\n[loblaws] 前 3 条示例：")
        for it in items[:3]:
            print(json.dumps(it, ensure_ascii=False, indent=2))

    with open("loblaws_raw.json", "w", encoding="utf-8") as f:
        json.dump(items, f, ensure_ascii=False, indent=2)
    print("\n[loblaws] 已保存到 loblaws_raw.json")

    backup_name = f"loblaws_raw_backup_{datetime.now().strftime('%Y%m%d_%H%M%S')}.json"
    shutil.copy("loblaws_raw.json", backup_name)
    print(f"[loblaws] 已自动备份一份到 {backup_name}")

    if not items:
        sys.exit(1)
