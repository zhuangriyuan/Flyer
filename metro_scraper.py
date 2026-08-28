"""
Metro.ca Flyer 爬虫 —— Playwright 版（直接截网络响应，不读跑完JS之后的DOM）

依赖：
    pip install playwright beautifulsoup4
    playwright install chromium

用法：
    python metro_scraper.py

输出：
    metro_raw.json —— 抓到的原始商品数据

============================================================
这版改了什么、为什么改
============================================================
之前那版是等页面加载完/点完"加载更多"之后，读当前的 `page.content()`
（也就是浏览器里 JS 跑完之后的最终 DOM）来解析商品。后来发现一个关键问题：
服务器一开始返回的 HTML 响应里，图片链接本来就是对的（用真实 Cookie 直接
请求这个接口验证过，100% 有图）——但读 `page.content()` 的时候，部分商品
的图片却变成了"暂无图片"的占位图。也就是说**问题不是"没收到图"，是"收到
了正确的，但页面在浏览器里跑起来之后，被 Metro 自己的前端 JS（比如库存
核查之类的二次逻辑）给换掉了**。

这版思路反过来：不等 JS 跑完再看 DOM，而是直接在网络层"偷听"每个响应，
把服务器刚吐出来、还没被任何客户端 JS 碰过的原始内容截下来解析。截获的
东西：
    1. 首屏那次请求本身返回的 HTML（服务端直接渲染出来的）
    2. 点"加载更多"触发的每一次 more-product AJAX 响应

不管 Metro 的前端后来做了什么"暗改"，我们解析的都是最原始、最可靠的那份。

翻页还是靠 Playwright 驱动点击"Load More Deals"按钮（这个机制没变，
毕竟得先点了按钮才会触发新一次 AJAX 请求），只是数据提取的来源换了。
踩过的坑都还在处理：
    1. OneTrust Cookie 同意横幅挡住点击，先关掉。
    2. 按钮选择器用 data-load-more-ajax-url 这个属性匹配。
    3. 不用 navigator.plugins 这类伪装（会把网站自己的特征检测脚本弄崩）。

⚠️ 如果哪天这个网站又改版了、又抓不到东西了，把 HEADLESS 改成 False 弹出
真窗口看看卡在哪一步，是最快的排查方式。
"""

import json
import shutil
import sys
from datetime import datetime
from typing import Optional
from urllib.parse import urljoin, urlparse

from playwright.sync_api import sync_playwright
from bs4 import BeautifulSoup

for _stream in (sys.stdout, sys.stderr):
    if hasattr(_stream, "reconfigure"):
        _stream.reconfigure(encoding="utf-8", errors="replace")

BASE_URL = "https://www.metro.ca/en/online-grocery"
FLYER_URL = (
    "https://www.metro.ca/en/online-grocery/flyer"
    "?sortOrder=relevance&filter=%3Arelevance%3Adeal%3AFlyer+%26+Deals"
)

HEADLESS = True  # 部署到 GitHub Actions 用 True；本地排查问题想看窗口就改 False
USE_REAL_CHROME = True
MAX_CLICKS = 150  # "Load More" 最多点这么多次，安全上限

_STEALTH_INIT_SCRIPT = """
Object.defineProperty(navigator, 'webdriver', {get: () => undefined});
window.chrome = window.chrome || { runtime: {} };
"""

LOAD_MORE_BUTTON_SELECTOR = "button[data-load-more-ajax-url]"
LOAD_MORE_TEXT_CANDIDATES = ["Load More Deals", "Load More", "See More", "Show More"]

ONETRUST_ACCEPT_SELECTOR = "#onetrust-accept-btn-handler"


def dismiss_cookie_banner(page) -> None:
    try:
        btn = page.locator(ONETRUST_ACCEPT_SELECTOR)
        if btn.is_visible(timeout=3000):
            btn.click(timeout=3000)
            print("[metro] 关掉了 OneTrust Cookie 同意横幅")
            page.wait_for_timeout(500)
    except Exception:
        pass


def parse_before_price_text(tile) -> Optional[str]:
    el = tile.select_one(".pricing__before-price")
    if not el:
        return None
    return el.get_text(" ", strip=True).replace("Regular price", "").strip()


def parse_sale_price_text(tile) -> Optional[str]:
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
    dimension = sticker_el.get("data-dimension-8") if sticker_el else None

    discount_percent = attr("data-discount-percent")

    # 真正的商品图片链接域名固定是 product-images.metro.ca。因为这版解析的
    # 是刚截获的原始响应（没被客户端 JS 碰过），这里不再需要额外的诊断代码。
    img_el = tile.select_one('img[src*="product-images"]')
    image = img_el.get("src") if img_el else None

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
        "image": image,
        "link": link,
    }


def get_all_flyer_items() -> list:
    # 存的是 response 对象本身（不是 .text()），因为在 page.on("response",...)
    # 这个回调里立刻读 body 内容有时候会碰到内容还没完全下载完的问题——
    # 稳妥的做法是先把响应对象攒起来，等浏览器关闭之前统一读取。
    captured_responses = []

    def on_response(response):
        try:
            url = response.url
            parsed = urlparse(url)
            # ⚠️ 之前这里只判断 "flyer" 这个词是不是出现在网址里，结果把一堆
            # Google DoubleClick 广告统计像素也算进来了（那些追踪链接会把
            # 来源页面网址当参数带过去，"flyer" 这个词出现在参数里，凑巧命中）。
            # 改成先确认域名真的是 metro.ca，再看路径里有没有 /flyer，准确
            # 得多，也不会再截一堆无关的广告像素进来拖慢速度、污染日志。
            is_metro_domain = parsed.hostname == "www.metro.ca"
            is_flyer_document = (
                is_metro_domain
                and response.request.resource_type == "document"
                and "/flyer" in parsed.path
            )
            is_more_product_ajax = is_metro_domain and "more-product" in parsed.path
            if is_flyer_document or is_more_product_ajax:
                kind = "首屏文档" if is_flyer_document else "more-product AJAX"
                print(f"[metro] 🔍 截获响应：[{kind}] status={response.status} "
                      f"url={url[:110]}")
                captured_responses.append(response)
        except Exception as e:
            print(f"[metro] 🔍 on_response 回调本身出错（不影响主流程）：{e}")

    with sync_playwright() as p:
        if USE_REAL_CHROME:
            try:
                browser = p.chromium.launch(headless=HEADLESS, channel="chrome")
            except Exception as e:
                print(f"[metro] 用真 Chrome 启动失败：{e}，退回 Playwright 自带 Chromium。")
                browser = p.chromium.launch(headless=HEADLESS)
        else:
            browser = p.chromium.launch(headless=HEADLESS)

        page = browser.new_page(locale="en-CA")
        page.add_init_script(_STEALTH_INIT_SCRIPT)
        page.on("response", on_response)

        print(f"[metro] 打开页面 {FLYER_URL} ...")
        try:
            page.goto(FLYER_URL, wait_until="domcontentloaded", timeout=60000)
        except Exception as e:
            print(f"[metro] 页面加载失败/超时：{e}")
            browser.close()
            return []

        page.wait_for_timeout(4000)
        dismiss_cookie_banner(page)

        print(f"[metro] 首屏已截获 {len(captured_responses)} 个相关响应")

        clicks = 0
        stable_rounds = 0
        while clicks < MAX_CLICKS:
            button = page.locator(LOAD_MORE_BUTTON_SELECTOR).first
            found_by_attribute = True
            try:
                if not button.is_visible(timeout=2000):
                    found_by_attribute = False
            except Exception:
                found_by_attribute = False

            if not found_by_attribute:
                button = None
                for text in LOAD_MORE_TEXT_CANDIDATES:
                    try:
                        candidate = page.get_by_text(text, exact=False).first
                        if candidate.is_visible(timeout=1000):
                            button = candidate
                            break
                    except Exception:
                        continue

            if button is None:
                print(f"[metro] 第 {clicks} 次点击后找不到\"加载更多\"按钮了，判断已经到底，停止。")
                break

            before_count = len(captured_responses)
            try:
                button.scroll_into_view_if_needed(timeout=5000)
                page.wait_for_timeout(300)
                button.click(timeout=5000, force=True)
                clicks += 1
            except Exception as e:
                print(f"[metro] 点击按钮失败：{e}，停止。")
                break

            page.wait_for_timeout(3000)

            new_count = len(captured_responses) - before_count
            print(f"[metro] 第 {clicks} 次点击后，新截获 {new_count} 个响应"
                  f"（累计 {len(captured_responses)} 个）")

            if new_count == 0:
                stable_rounds += 1
                if stable_rounds >= 3:
                    print("[metro] 连续几次点击都没有新响应，判断到底了，停止。")
                    break
            else:
                stable_rounds = 0

        print(f"[metro] 🔍 交互结束，一共截获了 {len(captured_responses)} 个响应，"
              f"开始逐个读取内容...")

        captured_htmls = []
        for i, resp in enumerate(captured_responses):
            try:
                text = resp.text()
                captured_htmls.append(text)
                print(f"[metro] 🔍 第 {i+1}/{len(captured_responses)} 个响应，"
                      f"内容长度 {len(text)} 字节")
            except Exception as e:
                print(f"[metro] 读取第 {i+1} 个响应内容失败（跳过）：{e}")

        browser.close()

    all_items = []
    seen_codes = set()
    for i, html in enumerate(captured_htmls):
        soup = BeautifulSoup(html, "html.parser")
        tiles = soup.select("div.tile-product[data-product-code]")
        batch_with_image = 0
        batch_new = 0
        for t in tiles:
            item = parse_tile(t)
            code = item.get("product_code")
            if item.get("image"):
                batch_with_image += 1
            if code and code not in seen_codes:
                seen_codes.add(code)
                all_items.append(item)
                batch_new += 1
        print(f"[metro] 🔍 第 {i+1} 份响应解析出 {len(tiles)} 个卡片"
              f"（{batch_with_image} 个有图，新增 {batch_new} 个去重后的商品）")

    return all_items


if __name__ == "__main__":
    items = get_all_flyer_items()
    print(f"\n[metro] 共抓到 {len(items)} 个商品卡片（含非打折的 REG 商品）")

    promo_items = [i for i in items if i["is_promo"] or i["discount_percent"]]
    print(f"[metro] 其中标记为打折(PROMO)的有 {len(promo_items)} 个")

    with_image = [i for i in items if i.get("image")]
    print(f"[metro] 其中有图片链接的有 {len(with_image)} 个")

    if items:
        print("\n[metro] 前 3 条示例：")
        for it in items[:3]:
            print(json.dumps(it, ensure_ascii=False, indent=2))

    with open("metro_raw.json", "w", encoding="utf-8") as f:
        json.dump(items, f, ensure_ascii=False, indent=2)
    print("\n[metro] 已保存全部到 metro_raw.json（打折与非打折都在里面，后续再筛）")

    backup_name = f"metro_raw_backup_{datetime.now().strftime('%Y%m%d_%H%M%S')}.json"
    shutil.copy("metro_raw.json", backup_name)
    print(f"[metro] 已自动备份一份到 {backup_name}")

    if not items:
        sys.exit(1)
