"""
Longo's (longos.com/flyers) 传单 爬虫 —— Playwright 浏览器版

依赖：
    pip install playwright
    playwright install chromium   # 第一次用需要额外下载浏览器本体，几百MB，
                                   # 只用装这一次，以后跑脚本不用重新下

用法：
    python longos_scraper.py

输出：
    longos_raw.json —— 抓到的原始商品数据

============================================================
为什么换成这个思路
============================================================
之前那版是手动填 PUBLICATION_ID / ACCESS_TOKEN——这两个是"这一期传单"
专属的，Longo's 每周出新传单就换号，得隔三差五去 F12 重新抓一次，很烦。

这版思路反过来：不猜编号了，直接用 Playwright 打开一个**真实的 Chromium
浏览器**去访问 https://www.longos.com/flyers，让它自己的前端 JS 去决定
该用哪个 publication_id、该带什么 access_token——我们在旁边"偷听"它自己
发出去的那个网络请求（打到 dam.flippenterprise.net/hosted/publication/
.../products 这个接口），把返回内容直接截下来。不管它这周用的是哪个
编号，反正是它自己现查出来的，我们跟着抄答案就行，不用自己维护过期的
编号。
"""

import json
import shutil
import sys
from datetime import datetime

from playwright.sync_api import sync_playwright

for _stream in (sys.stdout, sys.stderr):
    if hasattr(_stream, "reconfigure"):
        _stream.reconfigure(encoding="utf-8", errors="replace")

FLYER_PAGE_URL = "https://www.longos.com/flyers"

HEADLESS = True  # 被挡的话改成 False，弹出真窗口跑，能亲眼看看卡在哪
WAIT_AFTER_LOAD_MS = 8000  # 页面加载完之后再多等一会儿，确保接口请求已经发出去


def flatten_categories(item_categories: dict) -> list:
    """item_categories 是 {"l1": {...}, "l2": {...}, ...} 这种嵌套结构，
    每层是 None 或者 {"category_name": ..., "google_category_id": ...}。
    拍平成一个从细到粗排列的 category_name 列表（l7 在前，l1 在后），方便
    convert 那步"先看最细分类，没有再退到粗分类"地查表。"""
    if not item_categories:
        return []
    names = []
    for level in ("l7", "l6", "l5", "l4", "l3", "l2", "l1"):
        entry = item_categories.get(level)
        if entry and entry.get("category_name"):
            names.append(entry["category_name"])
    return names


def parse_item(raw: dict) -> dict:
    return {
        "id": raw.get("id"),
        "name": (raw.get("name") or "").strip(),
        "brand": (raw.get("brand") or "").strip(),
        "saleStory": raw.get("sale_story") or "",
        "prePriceText": raw.get("pre_price_text") or "",
        "priceText": raw.get("price_text") or "",
        "postPriceText": raw.get("post_price_text") or "",
        "originalPrice": raw.get("original_price"),  # 字符串或 null，convert 那步再转数字
        "categoryNames": flatten_categories(raw.get("item_categories")),
        "categoryL1": ((raw.get("item_categories") or {}).get("l1") or {}).get("category_name"),
        "categoryL2": ((raw.get("item_categories") or {}).get("l2") or {}).get("category_name"),
        "validFrom": raw.get("valid_from"),
        "validTo": raw.get("valid_to"),
        "imageUrl": raw.get("image_url"),
        "webUrl": raw.get("item_web_url"),
        "inStoreOnly": raw.get("in_store_only"),
    }


def capture_products_response() -> list:
    """打开真实浏览器访问传单页，截获它自己发出的那个 Flipp 商品接口请求，
    把响应内容（原始商品数组）截下来返回。可能会截到不止一次这个请求
    （比如页面初始化时打了好几个类似接口），全部收集起来去重。"""
    captured_batches = []
    seen_urls = set()

    def handle_response(response):
        url = response.url
        if "dam.flippenterprise.net/hosted/publication" not in url or "/products" not in url:
            return
        if url in seen_urls:
            return
        seen_urls.add(url)
        try:
            data = response.json()
        except Exception as e:
            print(f"[longos] 截到一个商品接口请求但解析 JSON 失败：{e}")
            return

        if isinstance(data, list):
            raw_items = data
        elif isinstance(data, dict):
            raw_items = data.get("items") or data.get("products") or []
        else:
            raw_items = []

        print(f"[longos] 截到商品接口请求：{url[:120]}... -> {len(raw_items)} 条")
        captured_batches.append(raw_items)

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=HEADLESS)
        page = browser.new_page(locale="en-CA")
        page.on("response", handle_response)

        print(f"[longos] 打开页面 {FLYER_PAGE_URL} ...")
        page.goto(FLYER_PAGE_URL, wait_until="domcontentloaded", timeout=60000)
        page.wait_for_timeout(WAIT_AFTER_LOAD_MS)

        browser.close()

    # 有的页面会重复请求同一份数据（比如换 tab/懒加载触发第二次），按 id 去重
    merged = {}
    for batch in captured_batches:
        for raw in batch:
            item_id = raw.get("id")
            key = item_id if item_id is not None else json.dumps(raw, sort_keys=True)
            merged[key] = raw

    return list(merged.values())


def get_all_items() -> list:
    raw_items = capture_products_response()
    if not raw_items:
        print(
            "\n[longos] ⚠️ 没截到任何商品接口请求。可能原因：\n"
            "[longos]   1) HEADLESS=True 被挡了 —— 改成 False 弹窗口出来看看卡在哪\n"
            "[longos]   2) 页面加载得比 WAIT_AFTER_LOAD_MS 还慢 —— 调大这个值再试\n"
            "[longos]   3) 页面结构变了（比如换了别的接口）—— 需要重新 F12 确认\n"
            "[longos]   4) playwright 浏览器没装 —— 执行一下 playwright install chromium"
        )
        return []

    return [parse_item(r) for r in raw_items if r.get("name")]


if __name__ == "__main__":
    print("[longos] 用 Playwright 打开真实浏览器抓取，不用手动维护 publication_id/access_token 了。")
    items = get_all_items()
    print(f"\n[longos] 共抓到 {len(items)} 个商品")

    has_price = [i for i in items if i["priceText"]]
    has_discount = [i for i in has_price if i["originalPrice"]]
    print(f"[longos] 其中有现价的 {len(has_price)} 个，现价+原价都有（能算折扣）的 {len(has_discount)} 个")

    if items:
        print("\n[longos] 前 3 条示例：")
        for it in items[:3]:
            print(json.dumps(it, ensure_ascii=False, indent=2))

    with open("longos_raw.json", "w", encoding="utf-8") as f:
        json.dump(items, f, ensure_ascii=False, indent=2)
    print("\n[longos] 已保存到 longos_raw.json")

    if items:
        backup_name = f"longos_raw_backup_{datetime.now().strftime('%Y%m%d_%H%M%S')}.json"
        shutil.copy("longos_raw.json", backup_name)
        print(f"[longos] 已自动备份一份到 {backup_name}")
