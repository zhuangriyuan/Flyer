"""
Food Basics (foodbasics.ca) 本周特价 爬虫 —— Playwright 版（已验证可用，含无头模式）

依赖：
    pip install playwright beautifulsoup4
    playwright install chromium

用法：
    python foodbasics_scraper.py

输出：
    foodbasics_raw.json —— 抓到的原始商品数据

============================================================
思路
============================================================
跟 Metro（同公司旗下）是同一个电商平台，同样上了 Cloudflare 防护，之前
curl_cffi 那版在 GitHub Actions 上会被拦。这版改用 Playwright 打开真实
Chrome，实测能绕过去——包括无头模式（HEADLESS=True）也验证过能用，可以
直接部署到 GitHub Actions，不用再手动维护 Cookie 了。

跟 Metro 那版踩过一样的坑，都处理了：
    1. OneTrust Cookie 同意横幅挡住点击事件，先关掉。
    2. 按钮选择器优先用 data-load-more-ajax-url 这个属性匹配，找不到再退回
       文字匹配，找不到按钮的话最后退一步试试滚动触发。
    3. 不用 navigator.plugins/languages 这类伪装——之前发现这类伪装会把
       网站自己的特征检测脚本弄崩，级联搞挂初始化代码，导致按钮点击事件
       压根没绑上。真实非无头 Chrome 本来就不需要这些伪装。
    4. 加了网络请求监听，点击/滚动后能直接确认有没有真的触发 more-product
       请求。

商品卡片本身带一堆 data-* 属性（data-product-code、data-merchandise-
category 这些），解析这块比 Metro 更省事，不用从零散文字里硬抠。

⚠️ 如果哪天这个网站又改版了、又抓不到东西了，把 HEADLESS 改成 False 弹出
真窗口看看卡在哪一步，是最快的排查方式。
"""

import json
import re
import shutil
import sys
from datetime import datetime
from typing import Optional
from urllib.parse import urljoin

from playwright.sync_api import sync_playwright
from bs4 import BeautifulSoup

for _stream in (sys.stdout, sys.stderr):
    if hasattr(_stream, "reconfigure"):
        _stream.reconfigure(encoding="utf-8", errors="replace")

BASE_URL = "https://www.foodbasics.ca"
FLYER_URL = (
    "https://www.foodbasics.ca/online-grocery/flyer"
    "?sortOrder=relevance&filter=%3Arelevance%3Adeal%3AFlyer+%26+Deals"
)

HEADLESS = True  # 部署到 GitHub Actions 用 True；本地排查问题想看窗口就改 False
USE_REAL_CHROME = True
MAX_ROUNDS = 100  # "加载更多"（点击或滚动）最多尝试这么多轮，安全上限

_STEALTH_INIT_SCRIPT = """
Object.defineProperty(navigator, 'webdriver', {get: () => undefined});
window.chrome = window.chrome || { runtime: {} };
"""

LOAD_MORE_BUTTON_SELECTOR = "button[data-load-more-ajax-url]"
LOAD_MORE_TEXT_CANDIDATES = ["Load More", "See More", "Show More", "View More"]

ONETRUST_ACCEPT_SELECTOR = "#onetrust-accept-btn-handler"

_UNIT_MAP = {
    "each": "each",
    "kilogram": "/kg",
    "gram": "/100g",
    "litre": "/l",
    "liter": "/l",
    "millilitre": "/ml",
    "milliliter": "/ml",
}


def dismiss_cookie_banner(page) -> None:
    try:
        btn = page.locator(ONETRUST_ACCEPT_SELECTOR)
        if btn.is_visible(timeout=3000):
            btn.click(timeout=3000)
            print("[foodbasics] 关掉了 OneTrust Cookie 同意横幅")
            page.wait_for_timeout(500)
    except Exception:
        pass  # 没弹出来这个横幅就算了，不影响后续


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


def get_all_items() -> list:
    all_items = []
    seen_skus = set()

    with sync_playwright() as p:
        if USE_REAL_CHROME:
            try:
                browser = p.chromium.launch(headless=HEADLESS, channel="chrome")
            except Exception as e:
                print(f"[foodbasics] 用真 Chrome 启动失败：{e}，退回 Playwright 自带 Chromium。")
                browser = p.chromium.launch(headless=HEADLESS)
        else:
            browser = p.chromium.launch(headless=HEADLESS)

        page = browser.new_page(locale="en-CA")
        page.add_init_script(_STEALTH_INIT_SCRIPT)

        print(f"[foodbasics] 打开页面 {FLYER_URL} ...")
        try:
            page.goto(FLYER_URL, wait_until="domcontentloaded", timeout=60000)
        except Exception as e:
            print(f"[foodbasics] 页面加载失败/超时：{e}")
            browser.close()
            return []

        page.wait_for_timeout(4000)
        dismiss_cookie_banner(page)

        ajax_fired = {"count": 0}

        def on_response(response):
            if "more-product" in response.url:
                ajax_fired["count"] += 1

        page.on("response", on_response)

        def extract_from_current_page():
            html = page.content()
            soup = BeautifulSoup(html, "html.parser")
            tiles = soup.select("div.default-product-tile")
            new_count = 0
            for t in tiles:
                item = parse_tile(t)
                if not item:
                    continue
                sku = item.get("sku")
                if sku and sku not in seen_skus:
                    seen_skus.add(sku)
                    all_items.append(item)
                    new_count += 1
            return len(tiles), new_count

        total_tiles, new_count = extract_from_current_page()
        print(f"[foodbasics] 首屏解析到 {total_tiles} 个商品卡片（新增 {new_count} 个）")

        if total_tiles == 0:
            print(
                "[foodbasics] 首屏就是空的——可能被 Cloudflare 拦了，或者网站结构变了。"
                "把 HEADLESS 改成 False 弹窗口出来看看是哪种情况。"
            )
            browser.close()
            return all_items

        rounds = 0
        stable_rounds = 0
        while rounds < MAX_ROUNDS:
            before_count = len(all_items)
            before_ajax_count = ajax_fired["count"]

            button = page.locator(LOAD_MORE_BUTTON_SELECTOR).first
            found_by_attribute = True
            try:
                if not button.is_visible(timeout=1500):
                    found_by_attribute = False
            except Exception:
                found_by_attribute = False

            if not found_by_attribute:
                button = None
                for text in LOAD_MORE_TEXT_CANDIDATES:
                    try:
                        candidate = page.get_by_text(text, exact=False).first
                        if candidate.is_visible(timeout=800):
                            button = candidate
                            break
                    except Exception:
                        continue

            if button is not None:
                try:
                    button.scroll_into_view_if_needed(timeout=5000)
                    page.wait_for_timeout(300)
                    button.click(timeout=5000, force=True)
                except Exception as e:
                    print(f"[foodbasics] 点击按钮失败：{e}，改试滚动。")
                    page.mouse.wheel(0, 3000)
            else:
                page.mouse.wheel(0, 3000)

            rounds += 1
            page.wait_for_timeout(4000)

            if ajax_fired["count"] == before_ajax_count:
                print(f"[foodbasics] ⚠️ 第 {rounds} 轮之后没侦测到 more-product 请求。")

            total_tiles, new_count = extract_from_current_page()
            print(f"[foodbasics] 第 {rounds} 轮后，累计 {len(all_items)} 个商品（本轮新增 {new_count} 个）")

            if len(all_items) == before_count:
                stable_rounds += 1
                if stable_rounds >= 5:
                    print("[foodbasics] 连续几轮都没有新商品，判断到底了，停止。")
                    break
            else:
                stable_rounds = 0

        browser.close()

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

    if not items:
        sys.exit(1)
