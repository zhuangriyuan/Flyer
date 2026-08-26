"""
Metro.ca Flyer 爬虫 (v2 —— 基于真实页面 HTML 结构重写)

依赖：pip install requests beautifulsoup4

用法：
    python metro_scraper.py

输出：
    metro_raw.json —— 抓到的原始商品数据

这一版的选择器是照着用户实际抓到的 flyer 页面 HTML 片段写的，
不再是靠开源库猜的，所以字段应该是准的。唯一还不确定的是"翻页"，
见下面 fetch_page() 里的说明。
"""

import json
import time
import sys
import random
import shutil
from datetime import datetime
from typing import Optional
from urllib.parse import urljoin

import requests
from bs4 import BeautifulSoup

BASE_URL = "https://www.metro.ca/en/online-grocery"
FLYER_PATH = "/flyer"
FLYER_FILTER = ":relevance:deal:Flyer & Deals"

# "Load More Deals" 按钮背后真正打的接口 —— 从浏览器 Network 面板抓到的，
# 不是猜的。第1页走普通的 /flyer 页面，第2页起换成这个。
MORE_PRODUCT_URL = "https://www.metro.ca/en/flyer/more-product"

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
    ),
    "Accept-Language": "en-CA,en;q=0.9",
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
}

REQUEST_DELAY_SECONDS = 4.0  # 放慢一点，别让请求节奏太规律、太密集
MAX_PAGES = 120  # 总共约1586个结果，每页约16个，需要约100页


def parse_before_price_text(tile) -> Optional[str]:
    """原价文字，格式不固定：'$6.59 /kg $2.99 /lb.' 或 '$2.49 ea.'，先原样存文本。"""
    el = tile.select_one(".pricing__before-price")
    if not el:
        return None
    return el.get_text(" ", strip=True).replace("Regular price", "").strip()


def parse_sale_price_text(tile) -> Optional[str]:
    """促销价文字。大部分是单价，少数是 '2 / $6.50' 这种捆绑价，原样保留方便人工核对。"""
    el = tile.select_one(".pricing__sale-price")
    if not el:
        return None
    return el.get_text(" ", strip=True)


def parse_main_price(tile) -> Optional[float]:
    price_el = tile.select_one("[data-main-price]")
    if not price_el:
        return None
    try:
        return float(price_el["data-main-price"])
    except (ValueError, KeyError):
        return None


def parse_tile(tile) -> dict:
    def attr(name, default=None):
        return tile.get(name, default)

    unit_el = tile.select_one(".head__unit-details")
    unit = unit_el.get_text(strip=True) if unit_el else None

    link_el = tile.select_one("a.product-details-link")
    link = urljoin(BASE_URL, link_el["href"]) if link_el and link_el.has_attr("href") else None

    sticker_el = tile.select_one(".visual__stickers")
    dimension = sticker_el.get("data-dimension-8") if sticker_el else None  # 'PROMO' or 'REG'

    discount_percent = attr("data-discount-percent")

    return {
        "product_code": attr("data-product-code"),
        "name_en": attr("data-product-name-en") or attr("data-product-name"),
        "category_en": attr("data-product-category-en") or attr("data-product-category"),
        "brand": attr("data-product-brand"),
        "unit": unit,
        "price": parse_main_price(tile),
        "before_price_text": parse_before_price_text(tile),
        "sale_price_text": parse_sale_price_text(tile),
        "discount_percent": int(discount_percent) if discount_percent else None,
        "is_promo": dimension == "PROMO",
        "link": link,
    }


def fetch_page(session: requests.Session, page: int) -> str:
    """
    page=1: 普通 flyer 页面（首屏自带的商品）。
    page>=2: "Load More Deals" 按钮背后的 AJAX 接口，currentPage 从 2 开始递增。
    这个接口是从浏览器 Network 面板里实测抓到的，不是猜的：
        GET https://www.metro.ca/en/flyer/more-product
            ?currentPage=N&sortOrder=relevance&filter=:relevance:deal:Flyer & Deals
    """
    if page == 1:
        url = f"{BASE_URL}{FLYER_PATH}"
        params = {"sortOrder": "relevance", "filter": FLYER_FILTER}
    else:
        url = MORE_PRODUCT_URL
        params = {"currentPage": page, "sortOrder": "relevance", "filter": FLYER_FILTER}

    request_headers = dict(HEADERS)
    if page > 1:
        # 这个接口是给页面内 JS 调用的，很多这类接口会检查这两个头，
        # 没有的话有可能返回不完整数据或直接拒绝。
        request_headers["X-Requested-With"] = "XMLHttpRequest"
        request_headers["Referer"] = (
            f"{BASE_URL}{FLYER_PATH}?sortOrder=relevance&filter={FLYER_FILTER}"
        )

    resp = session.get(url, params=params, headers=request_headers, timeout=20)
    print(f"[metro] GET {resp.url} -> {resp.status_code}, {len(resp.text)} bytes")
    resp.raise_for_status()
    return resp.text


def get_all_flyer_items() -> list:
    session = requests.Session()
    all_items = []
    seen_codes_by_page = []

    for page in range(1, MAX_PAGES + 1):
        try:
            html = fetch_page(session, page)
        except requests.RequestException as e:
            print(f"[metro] 第 {page} 页请求失败：{e}，重试一次...")
            time.sleep(5)
            try:
                html = fetch_page(session, page)
            except requests.RequestException as e2:
                print(f"[metro] 第 {page} 页重试仍失败：{e2}，停止翻页。")
                break

        soup = BeautifulSoup(html, "html.parser")

        # 只选真正的商品卡片，过滤掉 flyerPromo-a / flyerPromo-b 这种广告横幅
        tiles = soup.select("div.tile-product[data-product-code]")

        if not tiles:
            print(f"[metro] 第 {page} 页没有商品卡片，停止翻页。")
            if page == 1:
                print(
                    "[metro] 第一页就是空的 —— 选择器可能不匹配了，"
                    "网站结构可能又变了，需要重新用浏览器 F12 核对。"
                )
            break

        if page == 1:
            total_el = soup.select_one("[data-total-results]")
            if total_el:
                total = total_el["data-total-results"]
                print(f"[metro] 网站显示总共有 {total} 个结果（含非打折商品，实际能抓到的数量以最终结果为准）")

        page_items = [parse_tile(t) for t in tiles]
        page_codes = [i["product_code"] for i in page_items]
        seen_codes_by_page.append(page_codes[:3])

        # 翻页有效性检查：如果这页前3个商品编号和上一页完全一样，可能是网站
        # 偶尔的限流/缓存导致的临时问题，不一定是分页方式真的错了 —— 先等久一点重试一次。
        if page > 1 and seen_codes_by_page[-1] == seen_codes_by_page[-2]:
            print(f"[metro] ⚠️ 第 {page} 页内容和第 {page-1} 页前3个商品相同，等10秒后重试一次...")
            time.sleep(10)
            html_retry = fetch_page(session, page)
            soup_retry = BeautifulSoup(html_retry, "html.parser")
            tiles_retry = soup_retry.select("div.tile-product[data-product-code]")
            retry_codes = [t.get("data-product-code") for t in tiles_retry[:3]]

            if retry_codes == seen_codes_by_page[-2]:
                print(f"[metro] 重试后仍然重复，判断真的翻到底了，停止翻页。")
                break
            else:
                print(f"[metro] 重试后内容不一样了，继续正常翻页。")
                page_items = [parse_tile(t) for t in tiles_retry]
                seen_codes_by_page[-1] = retry_codes

        print(f"[metro] 第 {page} 页解析到 {len(page_items)} 个商品卡片")
        all_items.extend(page_items)

        time.sleep(REQUEST_DELAY_SECONDS + random.uniform(0, 2.0))  # 加点随机抖动

    return all_items


if __name__ == "__main__":
    items = get_all_flyer_items()
    print(f"\n[metro] 共抓到 {len(items)} 个商品卡片（含非打折的 REG 商品）")

    promo_items = [i for i in items if i["is_promo"] or i["discount_percent"]]
    print(f"[metro] 其中标记为打折(PROMO)的有 {len(promo_items)} 个")

    if items:
        print("\n[metro] 前 3 条示例：")
        for it in items[:3]:
            print(json.dumps(it, ensure_ascii=False, indent=2))

    with open("metro_raw.json", "w", encoding="utf-8") as f:
        json.dump(items, f, ensure_ascii=False, indent=2)
    print("\n[metro] 已保存全部到 metro_raw.json（打折与非打折都在里面，后续再筛）")

    # 自动备份一份带时间戳的副本，防止误删主文件后又要重新爬一次
    backup_name = f"metro_raw_backup_{datetime.now().strftime('%Y%m%d_%H%M%S')}.json"
    shutil.copy("metro_raw.json", backup_name)
    print(f"[metro] 已自动备份一份到 {backup_name}（这份千万别手滑删了）")

    if not items:
        sys.exit(1)
