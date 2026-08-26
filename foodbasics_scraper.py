"""
Food Basics (foodbasics.ca) 本周特价 爬虫

依赖：pip install curl_cffi beautifulsoup4
    （不是 requests！这个网站挂在 Cloudflare 机器人防护后面（能看到
    cf_clearance 这个 cookie），跟 T&T 的 Akamai 是同一类问题——curl_cffi
    能模拟出真实 Chrome 的 TLS 握手指纹，普通 requests 大概率会被拦。）

用法：
    python foodbasics_scraper.py

输出：
    foodbasics_raw.json —— 抓到的原始商品数据

这家跟 Metro 是同一个电商平台（Metro Inc 旗下牌子，图片链接都是
product-images.metro.ca），接口是"点击'加载更多'时前端调的局部刷新接口"，
直接返回一段 HTML 片段（不是 JSON），每页塞满了 default-product-tile 这种
卡片，用 currentPage 翻页：
    GET https://www.foodbasics.ca/flyer/more-product
        ?currentPage=N&sortOrder=relevance&filter=:relevance:deal:Flyer+%26+Deals

比 Metro 那版好处理的地方：每个商品卡片外层 div 上直接带了一堆 data-*
属性（data-product-code、data-product-name-en、data-product-brand、
data-merchandise-category……），不用从零散文字里硬抠，价格数字也有
data-main-price 这种现成属性可以直接拿。

⚠️ 跟 T&T 一样，这个网站有 Cloudflare 防护，需要一份"看起来像真人逛出来的"
Cookie 才能稳定访问。打开浏览器，F12 -> Network，访问一次
https://www.foodbasics.ca/online-grocery/flyer?sortOrder=relevance&filter=%3Arelevance%3Adeal%3AFlyer+%26+Deals
点一下"加载更多"触发 more-product 请求，右键 Copy -> Copy as cURL，把
-b "xxx" 引号里那一整段 Cookie 复制出来，粘到下面 COOKIE_HEADER 里。
跟 T&T 那版一样，Cookie 可能会过期，过期了重新抓一份换上就行；也可能
（就像 T&T 那次一样）光靠 curl_cffi 的 TLS 指纹就够用，不一定非要带
Cookie，可以先留空试试。
"""

import json
import re
import shutil
import sys
import time
from datetime import datetime
from typing import Optional
from urllib.parse import urljoin

try:
    from curl_cffi import requests
    from curl_cffi.requests.exceptions import RequestException
    HAS_CURL_CFFI = True
except ImportError:
    import requests
    from requests.exceptions import RequestException
    HAS_CURL_CFFI = False
    print(
        "[foodbasics] ⚠️ 没装 curl_cffi，退回普通 requests 库——大概率会被 Cloudflare 拦下来。\n"
        "[foodbasics] 强烈建议先执行: pip install curl_cffi\n"
    )

from bs4 import BeautifulSoup

for _stream in (sys.stdout, sys.stderr):
    if hasattr(_stream, "reconfigure"):
        _stream.reconfigure(encoding="utf-8", errors="replace")

BASE_URL = "https://www.foodbasics.ca"
API_URL = f"{BASE_URL}/flyer/more-product"

# ⚠️ 把浏览器 F12 里复制的完整 Cookie 粘贴到这个字符串里（需要包含
# cf_clearance 这一项）。留空字符串 "" 表示不带 cookie 直接试。
COOKIE_HEADER = ""

FILTER_VALUE = ":relevance:deal:Flyer & Deals"

HEADERS = {
    "accept": "*/*",
    "accept-language": "en",
    "content-type": "application/json",
    "priority": "u=1, i",
    "referer": f"{BASE_URL}/online-grocery/flyer?sortOrder=relevance&filter=%3Arelevance%3Adeal%3AFlyer+%26+Deals",
    "sec-ch-ua": '"Not=A?Brand";v="99", "Google Chrome";v="124", "Chromium";v="124"',
    "sec-ch-ua-mobile": "?0",
    "sec-ch-ua-platform": '"Windows"',
    "sec-fetch-dest": "empty",
    "sec-fetch-mode": "cors",
    "sec-fetch-site": "same-origin",
    "user-agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
    ),
    "x-requested-with": "XMLHttpRequest",
}
if COOKIE_HEADER:
    HEADERS["cookie"] = COOKIE_HEADER

REQUEST_DELAY_SECONDS = 2.0
MAX_PAGES = 60

_UNIT_MAP = {
    "each": "each",
    "kilogram": "/kg",
    "gram": "/100g",
    "litre": "/l",
    "liter": "/l",
    "millilitre": "/ml",
    "milliliter": "/ml",
}


def money(text: Optional[str]) -> Optional[float]:
    if not text:
        return None
    m = re.search(r"\$(\d+(?:\.\d{1,2})?)", text)
    return float(m.group(1)) if m else None


def parse_unit(price_block) -> str:
    """价格区块里找第一个 <abbr title="Each/Kilogram/...">，映射成简短单位。"""
    if price_block is None:
        return "each"
    abbr = price_block.find("abbr")
    if abbr and abbr.get("title"):
        return _UNIT_MAP.get(abbr["title"].strip().lower(), "each")
    return "each"


def parse_tile(tile) -> Optional[dict]:
    sku = tile.get("data-product-code")
    name = tile.get("data-product-name-en") or tile.get("data-product-name")
    if not sku or not name:
        return None

    brand = tile.get("data-product-brand")
    category_en = tile.get("data-product-category-en") or tile.get("data-product-category")
    merch_category = tile.get("data-merchandise-category")
    is_weighted = (tile.get("data-is-weighted") or "").lower() == "true"

    link_el = tile.select_one("a.product-details-link")
    link = urljoin(BASE_URL, link_el["href"]) if link_el and link_el.has_attr("href") else None

    img_el = tile.select_one("picture img")
    image = img_el.get("src") if img_el else None

    before_price_el = tile.select_one(".pricing__before-price")
    sale_price_container = tile.select_one("[data-main-price]")
    sale_price_el = tile.select_one(".pricing__sale-price")

    original_price = money(before_price_el.get_text(" ", strip=True)) if before_price_el else None

    sale_price = None
    if sale_price_container and sale_price_container.get("data-main-price"):
        try:
            sale_price = float(sale_price_container["data-main-price"])
        except ValueError:
            sale_price = None
    if sale_price is None and sale_price_el:
        sale_price = money(sale_price_el.get_text(" ", strip=True))

    unit = parse_unit(sale_price_el or before_price_el)

    return {
        "sku": sku,
        "name": name.strip(),
        "brand": brand,
        "categoryEn": category_en,
        "merchandiseCategory": merch_category,
        "isWeighted": is_weighted,
        "price": sale_price,
        "originalPrice": original_price,
        "unit": unit,
        "link": link,
        "image": image,
    }


def build_params(page: int) -> dict:
    return {
        "currentPage": page,
        "sortOrder": "relevance",
        "filter": FILTER_VALUE,
    }


def make_session():
    if HAS_CURL_CFFI:
        return requests.Session(impersonate="chrome124")
    return requests.Session()


def diagnose_403(resp) -> None:
    print("[foodbasics] ------------------------------------------------------------")
    print("[foodbasics] 收到 403，大概率是：")
    print("[foodbasics]   1) COOKIE_HEADER 过期了/需要重新抓 —— 去浏览器重新抓一份最新的粘进去")
    print("[foodbasics]   2) 没装 curl_cffi，普通 requests 的 TLS 指纹被识别出来了")
    print("[foodbasics] 返回内容前300字符，供排查：")
    try:
        print("[foodbasics] " + resp.text[:300].replace("\n", " "))
    except Exception:
        pass
    print("[foodbasics] ------------------------------------------------------------")


def fetch_page(session, page: int) -> str:
    resp = session.get(API_URL, params=build_params(page), headers=HEADERS, timeout=20)
    print(f"[foodbasics] GET page={page} -> {resp.status_code}, {len(resp.text)} bytes")
    if resp.status_code == 403:
        diagnose_403(resp)
    resp.raise_for_status()
    return resp.text


def get_all_items() -> list:
    session = make_session()
    print(f"[foodbasics] curl_cffi 可用: {HAS_CURL_CFFI}")
    if not COOKIE_HEADER:
        print("[foodbasics] COOKIE_HEADER 是空的，先试试光靠 TLS 指纹能不能过（不一定需要 Cookie）")

    all_items = []

    for page in range(1, MAX_PAGES + 1):
        try:
            html = fetch_page(session, page)
        except RequestException as e:
            print(f"[foodbasics] 第 {page} 页请求失败：{e}，等5秒后重试一次...")
            time.sleep(5)
            try:
                html = fetch_page(session, page)
            except RequestException as e2:
                print(f"[foodbasics] 第 {page} 页重试仍失败：{e2}，停止翻页。")
                break

        soup = BeautifulSoup(html, "html.parser")

        has_more_el = soup.select_one("[data-has-more-product-to-load]")
        has_more = (has_more_el.get("data-has-more-product-to-load") == "true") if has_more_el else False

        tiles = soup.select("div.default-product-tile")
        if not tiles:
            print(f"[foodbasics] 第 {page} 页没有商品卡片，停止翻页。")
            break

        page_items = [parse_tile(t) for t in tiles]
        page_items = [i for i in page_items if i]
        print(f"[foodbasics] 第 {page} 页解析到 {len(page_items)} 个商品（has_more={has_more}）")
        all_items.extend(page_items)

        if not has_more:
            print(f"[foodbasics] 接口显示没有更多商品了（第 {page} 页），停止翻页。")
            break

        time.sleep(REQUEST_DELAY_SECONDS)

    return all_items


if __name__ == "__main__":
    items = get_all_items()
    print(f"\n[foodbasics] 共抓到 {len(items)} 个商品")

    has_discount = [i for i in items if i["price"] is not None and i["originalPrice"] is not None]
    print(f"[foodbasics] 其中现价+原价都有（能算折扣）的有 {len(has_discount)} 个")

    if items:
        print("\n[foodbasics] 前 3 条示例：")
        for it in items[:3]:
            print(json.dumps(it, ensure_ascii=False, indent=2))

    with open("foodbasics_raw.json", "w", encoding="utf-8") as f:
        json.dump(items, f, ensure_ascii=False, indent=2)
    print("\n[foodbasics] 已保存到 foodbasics_raw.json")

    if items:
        backup_name = f"foodbasics_raw_backup_{datetime.now().strftime('%Y%m%d_%H%M%S')}.json"
        shutil.copy("foodbasics_raw.json", backup_name)
        print(f"[foodbasics] 已自动备份一份到 {backup_name}")
