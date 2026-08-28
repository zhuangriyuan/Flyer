"""
Galleria Supermarket (galleriasm.com) 每周特价 爬虫

依赖：pip install requests beautifulsoup4

用法：
    python galleria_scraper.py

输出：
    galleria_raw.json —— 抓到的原始商品数据

跟 Metro 不一样，这个页面看起来是服务端一次性把所有商品渲染出来的，
没有翻页/加载更多，所以不需要 metro_scraper.py 那套翻页逻辑，简单很多。

⚠️ 这个页面的网址（/Home/prodview/xxxxx 那串哈希）看起来像是某种活动/
每周特价专属链接，不排除以后会变。如果哪天脚本抓不到东西了，先去官网
确认一下"Weekly Sales"当前的真实链接是不是变了。
"""

import json
import re
import shutil
import sys
from datetime import datetime
from typing import Optional
from urllib.parse import urljoin

import requests
from bs4 import BeautifulSoup

# ⚠️ 这个 URL 是"每周特价"活动页，可能会不定期更换，抓不到东西时先来这里检查
PAGE_URL = "https://www.galleriasm.com/Home/prodview/dy9MFsYpCkOidpzOUKlHww"
BASE_URL = "https://www.galleriasm.com"

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
    ),
    "Accept-Language": "en-CA,en;q=0.9",
}


def parse_money(el) -> Optional[float]:
    if not el:
        return None
    m = re.search(r"[\d.]+", el.get_text())
    return float(m.group()) if m else None


def parse_tile(tile) -> Optional[dict]:
    img_link = tile.select_one("a.product-image")
    if not img_link:
        return None

    name = img_link.get("title")
    href = img_link.get("href")
    barcode = None
    if href:
        m = re.search(r"prodBarcode=([^&]+)", href)
        barcode = m.group(1) if m else None

    # ✅ 已用实测截图核对过——图片不在 <img> 标签里（那个 src 是固定的
    # /images/dummy.png 占位符，估计是给屏幕阅读器用的），真正的图片是
    # 设置在 a.product-image 这个链接自己的 CSS background-image 上：
    #     style="background-image:url('/images/Product/883298615237.jpg')"
    # 从这个 style 属性里用正则把网址抠出来，链接是相对路径，要拼上域名。
    image = None
    style_attr = img_link.get("style", "")
    m_bg = re.search(r"background-image\s*:\s*url\(['\"]?([^'\")]+)['\"]?\)", style_attr)
    if m_bg:
        image = urljoin(BASE_URL, m_bg.group(1))

    is_sale = tile.select_one(".sale-label") is not None

    price_box = tile.select_one(".price-box")
    old_price_el = None
    current_price_el = None
    unit_el = None
    if price_box:
        old_price_el = price_box.select_one(".old-price .price")
        # "当前价格"是 .price 里，但不能是嵌在 .old-price 里面那个
        for p in price_box.select(".price"):
            if p.find_parent("span", class_="old-price") is None:
                current_price_el = p
                break
        unit_el = price_box.select_one("small")

    return {
        "barcode": barcode,
        "name": name,
        "current_price": parse_money(current_price_el),
        "original_price": parse_money(old_price_el),
        "unit": unit_el.get_text(strip=True) if unit_el else None,
        "is_sale": is_sale,
        "link": urljoin(BASE_URL, href) if href else None,
        "image": image,
    }


def get_all_items() -> list:
    resp = requests.get(PAGE_URL, headers=HEADERS, timeout=20)
    print(f"[galleria] GET {PAGE_URL} -> {resp.status_code}, {len(resp.text)} bytes")
    resp.raise_for_status()

    soup = BeautifulSoup(resp.text, "html.parser")
    tiles = soup.select("div.item")
    print(f"[galleria] 找到 {len(tiles)} 个商品卡片")

    if not tiles:
        print(
            "[galleria] 一个商品都没找到 —— 选择器可能不对了，或者页面链接已经变了，"
            "需要重新用浏览器 F12 核对。"
        )

    items = []
    for tile in tiles:
        parsed = parse_tile(tile)
        if parsed and parsed.get("name"):
            items.append(parsed)

    return items


if __name__ == "__main__":
    items = get_all_items()
    print(f"\n[galleria] 共解析到 {len(items)} 个商品")

    sale_items = [i for i in items if i["is_sale"]]
    print(f"[galleria] 其中标记为打折(Sale)的有 {len(sale_items)} 个")

    if items:
        print("\n[galleria] 前 3 条示例：")
        for it in items[:3]:
            print(json.dumps(it, ensure_ascii=False, indent=2))

    with open("galleria_raw.json", "w", encoding="utf-8") as f:
        json.dump(items, f, ensure_ascii=False, indent=2)
    print("\n[galleria] 已保存到 galleria_raw.json")

    backup_name = f"galleria_raw_backup_{datetime.now().strftime('%Y%m%d_%H%M%S')}.json"
    shutil.copy("galleria_raw.json", backup_name)
    print(f"[galleria] 已自动备份一份到 {backup_name}")

    if not items:
        sys.exit(1)
