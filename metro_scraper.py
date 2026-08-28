"""
Metro.ca Flyer 爬虫 —— Playwright 版（已验证可用，含无头模式）

依赖：
    pip install playwright beautifulsoup4
    playwright install chromium

用法：
    python metro_scraper.py

输出：
    metro_raw.json —— 抓到的原始商品数据

============================================================
思路
============================================================
Metro 上了 Cloudflare 防护（跟同公司的 Food Basics 一样），之前 curl_cffi
那版在 GitHub Actions 上会被拦（数据中心 IP，Cloudflare 审得严）。这版改用
Playwright 打开真实 Chrome，实测能绕过去——包括无头模式（HEADLESS=True）
也验证过能用，可以直接部署到 GitHub Actions，不用再手动维护 Cookie 了。

翻页是点一个"Load More Deals"按钮触发的，不是无限滚动。踩过的坑，都处理了：
    1. 页面弹出的 OneTrust Cookie 同意横幅会挡住按钮的点击事件，
       不关掉的话点了也没反应——先找它的固定按钮 id 关掉。
    2. 按钮选择器用 data-load-more-ajax-url 这个属性匹配，不用"找文字"
       （文字匹配容易认错到别的元素）。
    3. 之前加的 navigator.plugins 伪装（返回假的插件列表数组）会把网站
       自己的 revealizr.js 特征检测脚本弄崩，级联搞挂后面一串初始化代码，
       导致按钮的点击事件压根没绑上——真实非无头 Chrome 本来就有真实
       plugins，不需要这个伪装，已经去掉，只留最基础的 navigator.webdriver
       这一条。
    4. 加了网络请求监听，点击后能直接确认有没有真的触发 more-product 请求，
       不用干等着肉眼判断"是不是卡住了"。

⚠️ 如果哪天这个网站又改版了、又抓不到东西了，把 HEADLESS 改成 False 弹出
真窗口看看卡在哪一步，是最快的排查方式。
"""

import json
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

# 从抓包报错日志里看到真实按钮长这样：
#   <button data-has-more-product-to-load-init="true" class="cta-secondary
#   medium load-more-btn" data-load-more-ajax-url="/en/flyer/more-product" ...>
# 用这个属性选择器比"找文字"准，不会认错到别的元素。
LOAD_MORE_BUTTON_SELECTOR = "button[data-load-more-ajax-url]"
LOAD_MORE_TEXT_CANDIDATES = ["Load More Deals", "Load More", "See More", "Show More"]

# OneTrust 是最常见的 Cookie 同意弹窗服务，几乎所有用它的网站"接受"按钮
# 的 id 都是这个固定值（OneTrust 自己的标准做法，不是猜的）。这个弹窗会
# 一直挡在页面上层拦截点击事件，不关掉的话点"加载更多"按钮会一直被拦截。
ONETRUST_ACCEPT_SELECTOR = "#onetrust-accept-btn-handler"


def dismiss_cookie_banner(page) -> None:
    try:
        btn = page.locator(ONETRUST_ACCEPT_SELECTOR)
        if btn.is_visible(timeout=3000):
            btn.click(timeout=3000)
            print("[metro] 关掉了 OneTrust Cookie 同意横幅")
            page.wait_for_timeout(500)
    except Exception:
        pass  # 没弹出来这个横幅就算了，不影响后续


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


_metro_debug_count = {"n": 0}


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

    # 商品卡片里有好几个 <img>（收藏心形图标、加拿大产地小旗子图标……），
    # 真正的商品图片链接域名固定是 product-images.metro.ca，用这个筛出来，
    # 比排除掉那些图标 class 更准（试过排除 class 的办法，41个tile里有
    # 10个会认错成旗子图标，换成认域名之后41个里40个都能拿到——这是拿
    # 用户手动滚动过、图片都加载出来之后截的样本测出来的结果）。
    #
    # ⚠️ 2026-08 发现：脚本自己用 Playwright 跑的时候图片全是 None，
    # 怀疑是懒加载问题——用户当时那份样本可能是手动滚动过全部加载出来
    # 之后截的，脚本自己截图的时候很多图片可能还没触发懒加载，src 还是
    # 占位图。加一段诊断，看看实际这个 <img> 标签当前长什么样。
    img_el = tile.select_one('img[src*="product-images"]')
    image = img_el.get("src") if img_el else None

    if image is None and _metro_debug_count["n"] < 5:
        _metro_debug_count["n"] += 1
        all_imgs = tile.select("img")
        dump = [dict(i.attrs) for i in all_imgs]
        print(f"[metro] 🔍 调试：这个 tile 里所有 <img> 标签的属性 = {dump}")

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


def scroll_through_page(page) -> None:
    """把当前页面从上到下慢慢滚一遍，触发所有已加载商品卡片的图片懒加载
    （不是死等一个固定秒数，而是主动"路过"每个位置逼图片加载）。滚完再
    回到底部（"加载更多"按钮一般在最底下，方便后续继续点）。"""
    try:
        height = page.evaluate("document.body.scrollHeight")
        step = 900
        pos = 0
        while pos < height:
            page.mouse.wheel(0, step)
            page.wait_for_timeout(200)
            pos += step
            new_height = page.evaluate("document.body.scrollHeight")
            if new_height > height:
                height = new_height  # 滚动过程中可能触发新内容，跟着往下滚够
        page.wait_for_timeout(500)  # 给最后一批图片留点加载时间
    except Exception:
        pass  # 滚动失败不影响主流程，最多就是有几张图没触发懒加载


def get_all_flyer_items() -> list:
    all_items = []
    seen_codes = set()

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

        print(f"[metro] 打开页面 {FLYER_URL} ...")
        try:
            page.goto(FLYER_URL, wait_until="domcontentloaded", timeout=60000)
        except Exception as e:
            print(f"[metro] 页面加载失败/超时：{e}")
            browser.close()
            return []

        page.wait_for_timeout(4000)
        dismiss_cookie_banner(page)
        scroll_through_page(page)  # 触发首屏所有商品的图片懒加载

        ajax_fired = {"count": 0}

        def on_response(response):
            if "more-product" in response.url:
                ajax_fired["count"] += 1

        page.on("response", on_response)

        def extract_from_current_page():
            html = page.content()
            soup = BeautifulSoup(html, "html.parser")
            tiles = soup.select("div.tile-product[data-product-code]")
            new_count = 0
            for t in tiles:
                item = parse_tile(t)
                code = item.get("product_code")
                if code and code not in seen_codes:
                    seen_codes.add(code)
                    all_items.append(item)
                    new_count += 1
            return len(tiles), new_count

        total_tiles, new_count = extract_from_current_page()
        print(f"[metro] 首屏解析到 {total_tiles} 个商品卡片（新增 {new_count} 个）")

        if total_tiles == 0:
            print(
                "[metro] 首屏就是空的——可能被 Cloudflare 拦了，或者网站结构变了。"
                "把 HEADLESS 改成 False 弹窗口出来看看是哪种情况。"
            )
            browser.close()
            return all_items

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

            before_ajax_count = ajax_fired["count"]
            try:
                button.scroll_into_view_if_needed(timeout=5000)
                page.wait_for_timeout(300)
                button.click(timeout=5000, force=True)
                clicks += 1
            except Exception as e:
                print(f"[metro] 点击按钮失败：{e}，停止。")
                break

            page.wait_for_timeout(4000)
            scroll_through_page(page)  # 触发这一批新加载商品的图片懒加载

            if ajax_fired["count"] == before_ajax_count:
                print(f"[metro] ⚠️ 第 {clicks} 次点击后没侦测到 more-product 请求，"
                      f"再试一轮看看是不是偶发的。")

            total_tiles, new_count = extract_from_current_page()
            print(f"[metro] 第 {clicks} 次点击后，页面共 {total_tiles} 个卡片（本轮新增 {new_count} 个）")

            if new_count == 0:
                stable_rounds += 1
                if stable_rounds >= 3:
                    print("[metro] 连续几次点击都没有新商品，判断到底了，停止。")
                    break
            else:
                stable_rounds = 0

        browser.close()

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

    backup_name = f"metro_raw_backup_{datetime.now().strftime('%Y%m%d_%H%M%S')}.json"
    shutil.copy("metro_raw.json", backup_name)
    print(f"[metro] 已自动备份一份到 {backup_name}")

    if not items:
        sys.exit(1)
