"""
T&T 大统华 (tntsupermarket.com) 本周特价 爬虫

依赖：pip install curl_cffi
    （注意不是 requests！这个网站挂在 Akamai 机器人防护后面，Akamai 会
    检查 TLS 握手指纹——普通的 requests 库发出的握手包跟真实 Chrome
    不一样，就算请求头和 Cookie 抄得再像，照样会被 403 拦下来。
    curl_cffi 是专门用来"模拟成真实浏览器的 TLS 指纹"的库，同一套代码，
    把 requests 换成 curl_cffi.requests 基本就能用，接口完全兼容。）

用法：
    python tnt_scraper.py

输出：
    tnt_raw.json —— 抓到的原始商品数据

这个网站是 Magento GraphQL 后端，跟 No Frills 那种"调后端 JSON 接口"是
同一路子：不用 BeautifulSoup 解析网页，直接调用 /graphql，
用 category(id=3222)（"本周特价"这个大类）配合 currentPage 翻页，
每页 35 个商品，接口会直接告诉你 total_pages，翻到底就停。

query/operationName/variables 都是照着用户在浏览器 F12 Network 面板里
实测抓到的原样写的，不是猜的：
    GET https://www.tntsupermarket.com/graphql
        ?query=...&operationName=GetCategories&variables={"currentPage":N,"id":3222,...}

⚠️⚠️⚠️ 最关键的一步 ⚠️⚠️⚠️
就算用了 curl_cffi 模拟浏览器指纹，Akamai 还是会认 Cookie ——需要一个
"看起来像正常人逛出来的"session。打开浏览器，F12 -> Network，访问一次
    https://www.tntsupermarket.com/chs/weekly-special-er.html?isRealCate=true
往下滚动翻一页，找到 GraphQL 请求 (operationName=GetCategories)，
右键 -> Copy -> Copy as cURL (bash)，从里面把 -b "xxx" 引号里那一整段
（从 PIM-SESSION-ID= 开始到最后）复制出来，整段粘贴到下面 COOKIE_HEADER
里。这个 Cookie 是 Akamai 判断"这是不是真人在逛"的关键凭证。

⚠️ Cookie 会过期——具体能撑多久（几十分钟到几小时都有可能）没法保证，
过期了脚本会 403，重新抓一份 Cookie 换上就行，见下面 diagnose_403() 打印
的提示。
"""

import json
import re
import shutil
import sys
import time
from datetime import datetime
from typing import Optional

try:
    from curl_cffi import requests
    from curl_cffi.requests.exceptions import RequestException
    HAS_CURL_CFFI = True
except ImportError:
    import requests
    from requests.exceptions import RequestException
    HAS_CURL_CFFI = False
    print(
        "[tnt] ⚠️ 没装 curl_cffi，退回普通 requests 库——大概率会被 Akamai 403 拦下来。\n"
        "[tnt] 强烈建议先执行: pip install curl_cffi\n"
    )

# Windows 控制台默认是 cp1252/gbk 之类的编码，直接 print 中文经常崩溃
# （UnicodeEncodeError）。这里强制把 stdout/stderr 换成 utf-8，报不了错
# 就用 ? 占位，不会再整个脚本崩掉。
for _stream in (sys.stdout, sys.stderr):
    if hasattr(_stream, "reconfigure"):
        _stream.reconfigure(encoding="utf-8", errors="replace")

GRAPHQL_URL = "https://www.tntsupermarket.com/graphql"

CATEGORY_ID = 3222
PAGE_SIZE = 35

# ⚠️⚠️⚠️ 本地测试的时候不带 Cookie 也能过（curl_cffi 的 TLS 指纹在家庭网络下
# 够用）。实测在 GitHub Actions 上也不用 Cookie 就能过——光靠 curl_cffi
# 模拟的 TLS 指纹就够了，Akamai 这边目前看起来主要卡的是这个，不是 Cookie。
# 如果哪天情况变了（比如又开始被 403），把浏览器 F12 里复制的完整 Cookie
# 粘贴到这个字符串里就行，见文件最上面的说明。
COOKIE_HEADER = ""

# 这两个是"配送地址/门店"相关的头，抓包时用户本地环境是这个值。理论上
# 不同地区/门店库存价格可能有细微差异，不影响大方向，先照抄能跑就行；
# 如果你想换成自己所在地区，去官网切换地址/门店后重新抓包替换这两个值。
POSTCODE = "L3T"
PREFERED_STORE_CODE = "UV"


def extract_session_id(cookie_header: str) -> Optional[str]:
    """从 Cookie 字符串里把 PHPSESSID 的值抠出来。抓包发现浏览器实际发出的
    请求里，x-sid 请求头的值就是 PHPSESSID cookie 的值——这里自动同步，
    省得手动对两遍容易抄错/忘了同步导致不一致被识别成异常请求。"""
    if not cookie_header:
        return None
    m = re.search(r"PHPSESSID=([^;]+)", cookie_header)
    return m.group(1) if m else None


def build_headers() -> dict:
    headers = {
        "accept": "*/*",
        "accept-language": "en-US,en;q=0.9,zh-CN;q=0.8,zh;q=0.7",
        "adrum": "isAjax:true",
        "content-currency": "CAD",
        "content-type": "application/json",
        "priority": "u=1, i",
        "referer": "https://www.tntsupermarket.com/chs/weekly-special-er.html?isRealCate=true",
        "sec-ch-ua": '"Not=A?Brand";v="99", "Google Chrome";v="124", "Chromium";v="124"',
        "sec-ch-ua-mobile": "?0",
        "sec-ch-ua-platform": '"Windows"',
        "sec-fetch-dest": "empty",
        "sec-fetch-mode": "cors",
        "sec-fetch-site": "same-origin",
        "store": "cn",  # 简体中文站点视图（跟页面 URL 里的 /chs/ 对应）
        "user-agent": (
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
            "(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
        ),
        "x-current-region": "undefined",
        "x-current-shipping-method": "delivery",
        "x-postcode": POSTCODE,
        "x-prefered-store-code": PREFERED_STORE_CODE,
    }
    if COOKIE_HEADER:
        headers["cookie"] = COOKIE_HEADER
        session_id = extract_session_id(COOKIE_HEADER)
        if session_id:
            headers["x-sid"] = session_id
    return headers


HEADERS = build_headers()

REQUEST_DELAY_SECONDS = 2.5
MAX_PAGES = 150  # 安全上限：实测总共约21页（716条/35每页），这里留了充足余量

# 完整 GraphQL 查询文本，照用户抓包的原样解码出来的，一个字都没改。
GRAPHQL_QUERY = (
    "query GetCategories($id:Int!$pageSize:Int!$currentPage:Int!"
    "$filters:ProductAttributeFilterInput!$sort:ProductAttributeSortInput)"
    "{category(id:$id){id uid name image url_key url_path url_suffix uid level "
    "category_types category_name_color category_bg_pc category_bg_mobile "
    "category_name_image_mobile category_banner_pc category_banner_mobile "
    "gift_nav_categories{icon id name url_key url_path url_suffix __typename}"
    "same_level_categories{url_key url_path url_suffix name id __typename}"
    "children{url_key url_path url_suffix name uid anchor_icon __typename}"
    "...CategoryFragment __typename}"
    "products(pageSize:$pageSize currentPage:$currentPage filter:$filters sort:$sort)"
    "{...ProductsFragment __typename}}"
    "fragment CategoryFragment on CategoryTree{id uid meta_title meta_keywords "
    "meta_description __typename}"
    "fragment ProductsFragment on Products{items{id uid sku name type_id has_options "
    "is_pre_order_product is_reward_product reward_balance product_hottest_description "
    "availability_schedule_text price{regularPrice{amount{currency value __typename}"
    "__typename}__typename}price_notice{fee tax __typename}price_range{minimum_price"
    "{final_price{currency value __typename}__typename}__typename}was_price uom_type "
    "weight_uom small_image{url __typename}stock_status url_key url_suffix "
    "product_tags_v2{auto_tags{code text background_color text_color date_start "
    "date_end __typename}event_tag{text background_color text_color date_start "
    "date_end icon detail_image description tag_image product_img_border __typename}"
    "preorder_tag{text background_color text_color date_start date_end __typename}"
    "tags{tag_url tag_position __typename}__typename}__typename}"
    "page_info{total_pages current_page __typename}total_count __typename}"
)


def build_params(page: int) -> dict:
    variables = {
        "currentPage": page,
        "id": CATEGORY_ID,
        "filters": {"category_id": {"eq": str(CATEGORY_ID)}},
        "pageSize": PAGE_SIZE,
        "sort": {"position": "DESC"},
    }
    return {
        "query": GRAPHQL_QUERY,
        "operationName": "GetCategories",
        "variables": json.dumps(variables, separators=(",", ":")),
    }


def parse_date(text: Optional[str]) -> Optional[str]:
    """'2026-08-20 15:00:00' -> '2026-08-20'，格式不对就原样返回/返回 None。"""
    if not text:
        return None
    m = re.match(r"(\d{4}-\d{2}-\d{2})", text)
    return m.group(1) if m else None


def build_url(url_key: Optional[str], url_suffix: Optional[str]) -> Optional[str]:
    if not url_key:
        return None
    return f"https://www.tntsupermarket.com/chs/{url_key}{url_suffix or '.html'}"


def parse_item(raw: dict) -> dict:
    price_block = raw.get("price") or {}
    regular_price = (
        ((price_block.get("regularPrice") or {}).get("amount") or {}).get("value")
    )
    price_range = raw.get("price_range") or {}
    final_price = (
        ((price_range.get("minimum_price") or {}).get("final_price") or {}).get("value")
    )
    was_price = raw.get("was_price")

    # 折扣标签（auto_tags 第一条一般就是 "-XX%" 那个），顺便把有效期抠出来
    tags_v2 = raw.get("product_tags_v2") or {}
    auto_tags = tags_v2.get("auto_tags") or []
    discount_text = auto_tags[0].get("text") if auto_tags else None
    date_start = auto_tags[0].get("date_start") if auto_tags else None
    date_end = auto_tags[0].get("date_end") if auto_tags else None

    weight_uom = raw.get("weight_uom") or ""

    small_image = raw.get("small_image") or {}

    return {
        "id": raw.get("id"),
        "sku": raw.get("sku"),
        "name": (raw.get("name") or "").strip(),
        "price": final_price,
        "regularPrice": regular_price,
        "wasPrice": was_price,
        "discountText": discount_text,
        "weightUom": weight_uom,
        "stockStatus": raw.get("stock_status"),
        "image": small_image.get("url"),
        "url": build_url(raw.get("url_key"), raw.get("url_suffix")),
        "validFrom": parse_date(date_start),
        "validTo": parse_date(date_end),
    }


def make_session():
    if HAS_CURL_CFFI:
        # impersonate="chrome124" 让 curl_cffi 发出的 TLS 握手指纹跟真实
        # Chrome 124 一致，这是绕过 Akamai TLS 指纹检测的关键一步。
        return requests.Session(impersonate="chrome124")
    return requests.Session()


def diagnose_403(resp) -> None:
    """403 时打印点有用的信息，帮着判断是 Cookie 过期了还是别的问题，
    不然光看 HTTPError 完全不知道该往哪个方向排查。"""
    print("[tnt] ------------------------------------------------------------")
    print("[tnt] 收到 403，大概率是：")
    print("[tnt]   1) COOKIE_HEADER 是空的/过期了 —— 去浏览器重新抓一份最新的粘进去")
    print("[tnt]   2) 没装 curl_cffi，普通 requests 的 TLS 指纹被识别出来了")
    print("[tnt] 返回内容前300字符，供排查：")
    try:
        print("[tnt] " + resp.text[:300].replace("\n", " "))
    except Exception:
        pass
    print("[tnt] ------------------------------------------------------------")


def fetch_page(session, page: int):
    params = build_params(page)
    resp = session.get(GRAPHQL_URL, params=params, headers=HEADERS, timeout=20)
    print(f"[tnt] GET page={page} -> {resp.status_code}, {len(resp.text)} bytes")
    if resp.status_code == 403:
        diagnose_403(resp)
    resp.raise_for_status()
    try:
        return resp.json()
    except (json.JSONDecodeError, ValueError):
        print("[tnt] 返回的不是合法 JSON（可能是 Akamai 的验证页面），前300字符：")
        print("[tnt] " + resp.text[:300].replace("\n", " "))
        raise


def get_all_items() -> list:
    session = make_session()
    print(f"[tnt] curl_cffi 可用: {HAS_CURL_CFFI}（False 的话强烈建议 pip install curl_cffi 后重跑）")
    if not COOKIE_HEADER:
        print("[tnt] ⚠️ COOKIE_HEADER 是空的，很可能会被 403 —— 建议先按脚本顶部的说明粘贴一份最新 Cookie")

    all_items = []
    total_pages = None

    for page in range(1, MAX_PAGES + 1):
        try:
            data = fetch_page(session, page)
        except RequestException as e:
            print(f"[tnt] 第 {page} 页请求失败：{e}，等5秒后重试一次...")
            time.sleep(5)
            try:
                data = fetch_page(session, page)
            except RequestException as e2:
                print(f"[tnt] 第 {page} 页重试仍失败：{e2}，停止翻页。")
                break

        if "errors" in data:
            print(f"[tnt] 接口返回了 errors 字段（可能被 Akamai 拦了/请求头需要更新）：")
            print(json.dumps(data["errors"], ensure_ascii=False, indent=2)[:2000])
            break

        products = (data.get("data") or {}).get("products") or {}
        raw_items = products.get("items") or []
        page_info = products.get("page_info") or {}
        total_pages = page_info.get("total_pages")
        total_count = products.get("total_count")

        if page == 1:
            print(f"[tnt] 网站显示本周特价共 {total_count} 个商品，共 {total_pages} 页")

        if not raw_items:
            print(f"[tnt] 第 {page} 页没有商品，停止翻页。")
            break

        page_items = [parse_item(r) for r in raw_items]
        print(f"[tnt] 第 {page} 页解析到 {len(page_items)} 个商品")
        all_items.extend(page_items)

        if total_pages and page >= total_pages:
            print(f"[tnt] 已经翻到最后一页（{page}/{total_pages}），停止。")
            break

        time.sleep(REQUEST_DELAY_SECONDS)

    return all_items


if __name__ == "__main__":
    items = get_all_items()
    print(f"\n[tnt] 共抓到 {len(items)} 个商品")

    discounted_items = [i for i in items if i["price"] is not None and i["regularPrice"] not in (None, i["price"])]
    print(f"[tnt] 其中价格和原价不一样（有折扣）的有 {len(discounted_items)} 个")

    if items:
        print("\n[tnt] 前 3 条示例：")
        for it in items[:3]:
            print(json.dumps(it, ensure_ascii=False, indent=2))

    with open("tnt_raw.json", "w", encoding="utf-8") as f:
        json.dump(items, f, ensure_ascii=False, indent=2)
    print("\n[tnt] 已保存到 tnt_raw.json")

    backup_name = f"tnt_raw_backup_{datetime.now().strftime('%Y%m%d_%H%M%S')}.json"
    shutil.copy("tnt_raw.json", backup_name)
    print(f"[tnt] 已自动备份一份到 {backup_name}")

    if not items:
        sys.exit(1)
