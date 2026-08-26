"""
No Frills (nofrills.ca) 每周特价 爬虫

依赖：pip install requests

用法：
    python nofrills_scraper.py

输出：
    nofrills_raw.json —— 抓到的原始商品数据

这个网站是 React 前端 + 后端 JSON API（跟 Metro 那种服务端直出 HTML 完全
不一样），所以不用 BeautifulSoup 解析网页，直接调用后端接口拿结构化数据，
反而更省事更准。

⚠️ storeId 绑定了具体门店（"3640"），意味着结果是那家门店的传单。如果你
想换成别的门店，需要在浏览器里切换门店后重新抓一次 Network 请求，把新的
storeId 换进来。同一连锁品牌不同门店的传单内容大部分是重叠的，问题不大。

⚠️ x-apikey 是网站前端自己嵌在网页里的公开 key，不是私密凭证。
"""

import json
import re
import time
import shutil
import uuid
from datetime import datetime
from typing import Optional

import requests

API_URL = "https://api.pcexpress.ca/pcx-bff/api/v2/flyersPage"
BASE_URL = "https://www.nofrills.ca"

# 抓包时看到的门店编号，如果想换门店，去浏览器里切换后重新抓一次 Network 请求替换掉
STORE_ID = "3640"

HEADERS = {
    "Accept": "*/*",
    "Accept-Language": "en",
    "Business-User-Agent": "PCXWEB",
    "Content-Type": "application/json",
    "Origin": "https://www.nofrills.ca",
    "Origin_Session_Header": "B",
    "Referer": "https://www.nofrills.ca/",
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

REQUEST_DELAY_SECONDS = 3.0


def build_payload(page_number: int, cart_id: str, domain_user_id: str, session_id: str) -> dict:
    today = datetime.now().strftime("%d%m%Y")  # 抓包看到的格式是 DDMMYYYY
    return {
        "cart": {"cartId": cart_id},
        "fulfillmentInfo": {
            "storeId": STORE_ID,
            "pickupType": "SELF_SERVE_FULL",
            "offerType": "OG",
            "date": today,
            "timeSlot": None,
        },
        "listingInfo": {
            "filters": {
                "promotions": ["Price Reduction", "$1,$2,$3,$4,$5", "PC Points", "Multi-Buy"]
            },
            "sort": {},
            "pagination": {"from": page_number},
            "includeFiltersInResponse": True,
        },
        "banner": "nofrills",
        "userData": {
            "domainUserId": domain_user_id,
            "sessionId": session_id,
        },
        "options": [{"name": "bff.exp.next_gen_active", "value": "variant"}],
    }


def parse_money(text: Optional[str]) -> Optional[float]:
    if not text:
        return None
    m = re.search(r"[\d.]+", text)
    return float(m.group()) if m else None


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
        "dealType": deal.get("type"),  # "SALE" 才是真降价，"LIMIT" 只是限购提示
        "link": (BASE_URL + link) if link else None,
    }


def get_all_items() -> list:
    session = requests.Session()
    all_items = []
    page_number = 1  # ⚠️ 试验后发现 "from" 很可能是页码本身，不是条目偏移量

    # 整个爬取过程固定用同一套"会话身份"，跟真实浏览器连续翻页的行为一致，
    # 不能每次请求都随机生成新的，不然服务器会认成不同的人，翻页状态接不上
    cart_id = str(uuid.uuid4())
    domain_user_id = str(uuid.uuid4())
    session_id = str(uuid.uuid4())

    while True:
        payload = build_payload(page_number, cart_id, domain_user_id, session_id)
        resp = session.post(API_URL, headers=HEADERS, json=payload, timeout=20)
        print(f"[nofrills] POST page={page_number} -> {resp.status_code}, {len(resp.text)} bytes")
        resp.raise_for_status()
        data = resp.json()

        try:
            product_grid = (
                data["layout"]["sections"]["productListingSection"]["components"][0]
                ["data"]["productGrid"]
            )
        except (KeyError, IndexError, TypeError):
            print("[nofrills] 解析不到 productGrid，接口返回结构可能变了，停止。")
            print("[nofrills] 返回内容前500字符：", resp.text[:500])
            break

        tiles = product_grid.get("productTiles", [])
        pagination = product_grid.get("pagination", {})
        total_results = pagination.get("totalResults", 0)
        has_more = pagination.get("hasMore", False)

        print(f"[nofrills] 本页 {len(tiles)} 个商品，总共 {total_results} 个，hasMore={has_more}")

        items = [parse_tile(t) for t in tiles if t.get("title")]
        all_items.extend(items)

        if not has_more or not tiles:
            break

        page_number += 1
        time.sleep(REQUEST_DELAY_SECONDS)

        if page_number > 60:  # 安全上限（859条 / 48每页 ≈ 18页，60页绰绰有余）
            print("[nofrills] 翻页数量超过安全上限，停止。")
            break

    return all_items


if __name__ == "__main__":
    items = get_all_items()
    print(f"\n[nofrills] 共抓到 {len(items)} 个商品")

    sale_items = [i for i in items if i["dealType"] == "SALE"]
    print(f"[nofrills] 其中标记为打折(SALE)的有 {len(sale_items)} 个")

    if items:
        print("\n[nofrills] 前 3 条示例：")
        for it in items[:3]:
            print(json.dumps(it, ensure_ascii=False, indent=2))

    with open("nofrills_raw.json", "w", encoding="utf-8") as f:
        json.dump(items, f, ensure_ascii=False, indent=2)
    print("\n[nofrills] 已保存到 nofrills_raw.json")

    backup_name = f"nofrills_raw_backup_{datetime.now().strftime('%Y%m%d_%H%M%S')}.json"
    shutil.copy("nofrills_raw.json", backup_name)
    print(f"[nofrills] 已自动备份一份到 {backup_name}")
