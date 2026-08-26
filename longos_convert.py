"""
将 longos_scraper.py 生成的 longos_raw.json 转换成网站用的 data.json 格式。

用法：
    python longos_convert.py

输入：longos_raw.json
输出：longos_converted.json —— 可以直接拼进主 data.json 的 "items" 数组

这版比之前那个"从广告牌文字里硬抠价格"的方案简单可靠得多，因为接口直接
给了 original_price（不用再从 "SAVE $X" 这种促销语里反推），而且带了
item_categories 这个 Google 商品分类树（l1 最粗到 l7 最细），可以拿来分类，
比只看商品名关键词准得多。

价格逻辑：
    - price_text 是空字符串的（比如"买一送一"没标单价的那种）没法用，跳过
    - original_price 是 null 的（没有原价可比）没法算折扣，跳过
    - pre_price_text 是 "2 FOR" 这种"买N件合计价"的，price 和 original_price
      两个都除以 N，换算成单件价格再比较（接口里这两个字段本来就是同一个
      "N件的口径"，除法算出来的比例还是对的）

分类逻辑（2026-08 起不再排除任何商品，全部收录）：
    1. 先拿 category_names（从细到粗）去查 GOOGLE_CATEGORY_MAP，命中就用
    2. 查表没命中，退回到英文关键词那套 classify()（拿 品牌+商品名 去匹配）
    3. 还是没命中，看 l1/l2 能不能兜个粗分类：l1 是 "Health & Beauty" 的
       归"个护美妆"；l1 是 "Home & Garden" 但 l2 不是 "Household Supplies"
       的归"家居百货"（花束、装饰罐子、厨具这类）
    4. 还是没命中，归"其他"，照样收录
"""

import json
import re
import sys
from pathlib import Path
from typing import Optional

from zh_dictionary import translate_name
from category_rules import classify, classify_by_google_categories

INPUT_FILE = "longos_raw.json"
OUTPUT_FILE = "longos_converted.json"

for _stream in (sys.stdout, sys.stderr):
    if hasattr(_stream, "reconfigure"):
        _stream.reconfigure(encoding="utf-8", errors="replace")


def category_hint_from_l1_l2(l1: Optional[str], l2: Optional[str]) -> Optional[str]:
    """前面 GOOGLE_CATEGORY_MAP / classify() 都没分出来的时候，用粗一点的
    l1/l2 兜个底，好过全部堆进"其他"。"""
    if l1 == "Health & Beauty":
        return "个护美妆"
    if l1 == "Home & Garden" and l2 != "Household Supplies":
        return "家居百货"
    return None


def parse_bundle_count(pre_price_text: str) -> Optional[int]:
    m = re.match(r"^(\d+)\s+FOR$", (pre_price_text or "").strip(), re.IGNORECASE)
    return int(m.group(1)) if m else None


def parse_unit(post_price_text: str) -> str:
    text = (post_price_text or "").strip().lower()
    if "/lb" in text:
        return "/lb"
    if "/100g" in text:
        return "/100g"
    return "each"


def convert():
    path = Path(INPUT_FILE)
    if not path.exists() or path.stat().st_size == 0:
        print(f"[convert] {INPUT_FILE} 不存在或是空文件——longos_scraper.py 大概率没跑成功，"
              f"检查一下上一步的输出，先把抓取跑通再来转换。")
        return
    with open(path, encoding="utf-8") as f:
        raw_items = json.load(f)

    converted = []
    skipped_no_price = 0
    skipped_no_discount = 0
    fallback_other_count = 0

    for item in raw_items:
        price_text = item.get("priceText")
        if not price_text:
            skipped_no_price += 1
            continue

        try:
            price = float(price_text)
        except (TypeError, ValueError):
            skipped_no_price += 1
            continue

        original_price_text = item.get("originalPrice")
        original_price = None
        if original_price_text:
            try:
                original_price = float(original_price_text)
            except (TypeError, ValueError):
                original_price = None

        bundle_count = parse_bundle_count(item.get("prePriceText"))
        if bundle_count and bundle_count > 0:
            price = round(price / bundle_count, 2)
            if original_price is not None:
                original_price = round(original_price / bundle_count, 2)

        if original_price is None or original_price <= price:
            skipped_no_discount += 1
            continue

        name_en = item.get("name") or ""
        if item.get("brand"):
            name_en = f"{item['brand']} {name_en}"

        category_zh = classify_by_google_categories(item.get("categoryNames") or [])
        if category_zh is None:
            category_zh = classify(name_en)
        if category_zh is None:
            category_zh = category_hint_from_l1_l2(item.get("categoryL1"), item.get("categoryL2"))
        if category_zh is None:
            category_zh = "其他"
            fallback_other_count += 1

        converted.append({
            "store": "longos",
            "category": category_zh,
            "nameZh": translate_name(name_en),
            "nameEn": name_en,
            "price": price,
            "originalPrice": original_price,
            "unit": parse_unit(item.get("postPriceText")),
            "validFrom": item.get("validFrom"),
            "validTo": item.get("validTo"),
            "url": item.get("webUrl"),
        })

    with open(OUTPUT_FILE, "w", encoding="utf-8") as f:
        json.dump(converted, f, ensure_ascii=False, indent=2)

    print(f"[convert] 原始 {len(raw_items)} 条 -> 转换出 {len(converted)} 条可用商品")
    print(f"[convert] 跳过：没有现价 {skipped_no_price} 条")
    print(f"[convert] 跳过：没有折扣/原价算不出来 {skipped_no_discount} 条")
    print(f'[convert] 归到"其他"类（没匹配到具体类目，但照样收录）{fallback_other_count} 条')
    print(f"\n[convert] 已保存到 {OUTPUT_FILE}")


if __name__ == "__main__":
    convert()
