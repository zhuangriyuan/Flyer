"""
将 galleria_scraper.py 生成的 galleria_raw.json 转换成网站用的 data.json 格式。

用法：
    python galleria_convert.py

输入：galleria_raw.json
输出：galleria_converted.json —— 可以直接拼进主 data.json 的 "items" 数组
"""

import json

from zh_dictionary import translate_name
from category_rules import classify, is_excluded_by_name

INPUT_FILE = "galleria_raw.json"
OUTPUT_FILE = "galleria_converted.json"


def convert():
    with open(INPUT_FILE, encoding="utf-8") as f:
        raw_items = json.load(f)

    converted = []
    skipped_not_sale = 0
    skipped_no_original_price = 0
    skipped_excluded_by_name = 0
    fallback_other_count = 0

    for item in raw_items:
        if not item.get("is_sale"):
            skipped_not_sale += 1
            continue

        original_price = item.get("original_price")
        current_price = item.get("current_price")
        if original_price is None or current_price is None:
            skipped_no_original_price += 1
            continue

        name_en = item.get("name")

        # 明显是美妆/护肤品之类的，才真正排除掉
        if is_excluded_by_name(name_en):
            skipped_excluded_by_name += 1
            continue

        # 没匹配到具体类目的，归到"其他"照样收录 —— 至少商品名还能被搜到
        category_zh = classify(name_en)
        if category_zh is None:
            category_zh = "其他"
            fallback_other_count += 1

        converted.append({
            "store": "galleria",
            "category": category_zh,
            "nameZh": translate_name(name_en),
            "nameEn": name_en,
            "price": current_price,
            "originalPrice": original_price,
            "unit": item.get("unit") or "each",
            "validFrom": None,
            "validTo": None,
            "url": item.get("link"),
        })

    with open(OUTPUT_FILE, "w", encoding="utf-8") as f:
        json.dump(converted, f, ensure_ascii=False, indent=2)

    print(f"[convert] 原始 {len(raw_items)} 条 -> 转换出 {len(converted)} 条可用商品")
    print(f"[convert] 跳过：非打折 {skipped_not_sale} 条")
    print(f"[convert] 跳过：价格信息不全 {skipped_no_original_price} 条")
    print(f"[convert] 跳过：按商品名排除 {skipped_excluded_by_name} 条（2026-08 起恒为0，不再排除）")
    print(f'[convert] 归到"其他"类（没匹配到具体类目，但照样收录）{fallback_other_count} 条')
    print(f"\n[convert] 已保存到 {OUTPUT_FILE}")


if __name__ == "__main__":
    convert()
