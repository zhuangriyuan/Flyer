"""
将 nofrills_scraper.py 生成的 nofrills_raw.json 转换成网站用的 data.json 格式。

用法：
    python nofrills_convert.py

输入：nofrills_raw.json
输出：nofrills_converted.json —— 可以直接拼进主 data.json 的 "items" 数组
"""

import json

from zh_dictionary import translate_name
from category_rules import classify, is_excluded_by_name

INPUT_FILE = "nofrills_raw.json"
OUTPUT_FILE = "nofrills_converted.json"


def convert():
    with open(INPUT_FILE, encoding="utf-8") as f:
        raw_items = json.load(f)

    converted = []
    skipped_not_sale = 0
    skipped_no_was_price = 0
    skipped_excluded_by_name = 0
    fallback_other_count = 0

    for item in raw_items:
        # dealType == "SALE" 才是真降价，"LIMIT" 只是限购提示，价格没变
        if item.get("dealType") != "SALE":
            skipped_not_sale += 1
            continue

        was_price = item.get("wasPrice")
        price = item.get("price")
        if was_price is None or price is None:
            skipped_no_was_price += 1
            continue

        name_en = item.get("title")

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
            "store": "nofrills",
            "category": category_zh,
            "nameZh": translate_name(name_en),
            "nameEn": name_en,
            "price": price,
            "originalPrice": was_price,
            "unit": item.get("packageSizing") or "each",
            "validFrom": None,
            "validTo": None,
            "url": item.get("link"),
            "image": item.get("image"),
        })

    with open(OUTPUT_FILE, "w", encoding="utf-8") as f:
        json.dump(converted, f, ensure_ascii=False, indent=2)

    print(f"[convert] 原始 {len(raw_items)} 条 -> 转换出 {len(converted)} 条可用商品")
    print(f"[convert] 跳过：非真降价(LIMIT等) {skipped_not_sale} 条")
    print(f"[convert] 跳过：价格信息不全 {skipped_no_was_price} 条")
    print(f"[convert] 跳过：按商品名排除 {skipped_excluded_by_name} 条（2026-08 起恒为0，不再排除）")
    print(f'[convert] 归到"其他"类（没匹配到具体类目，但照样收录）{fallback_other_count} 条')
    print(f"\n[convert] 已保存到 {OUTPUT_FILE}")


if __name__ == "__main__":
    convert()
