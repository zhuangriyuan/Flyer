"""
将 metro_scraper.py 生成的 metro_raw.json 转换成网站用的 data.json 格式。

用法：
    python metro_convert.py

输入：metro_raw.json（跟这个脚本放一个文件夹）
输出：metro_converted.json —— 里面是可以直接拼进主 data.json 的 "items" 数组

分类规则是关键词匹配，不是100%准，跑完之后建议你打开 metro_converted.json
扫一眼有没有明显分错类的（比如"未分类"堆了很多东西，或者某个东西分错了）。
"""

import json
import re
from typing import Optional

from zh_dictionary import translate_name
from category_rules import classify, CATEGORY_EN_FALLBACK_MAP, is_excluded_by_name

INPUT_FILE = "metro_raw.json"
OUTPUT_FILE = "metro_converted.json"


def extract_original_price(before_price_text: Optional[str]) -> Optional[float]:
    """从 '$6.59 /kg $2.99 /lb.' 或 '$3.29 ea.' 这种文本里抠出第一个 $ 金额。"""
    if not before_price_text:
        return None
    m = re.search(r"\$\s?(\d+\.\d{2})", before_price_text)
    return float(m.group(1)) if m else None


def convert():
    with open(INPUT_FILE, encoding="utf-8") as f:
        raw_items = json.load(f)

    converted = []
    skipped_not_promo = 0
    skipped_no_original_price = 0
    skipped_excluded_by_name = 0
    fallback_other_count = 0
    category_en_fallback_count = 0

    for item in raw_items:
        if not (item.get("is_promo") or item.get("discount_percent")):
            skipped_not_promo += 1
            continue

        name_en = item.get("name_en")

        # 2026-08 起不再排除美妆/护肤品类，is_excluded_by_name 恒返回 False，
        # 这行调用只是留着兼容，实际不会跳过任何商品了
        if is_excluded_by_name(name_en):
            skipped_excluded_by_name += 1
            continue

        original_price = extract_original_price(item.get("before_price_text"))
        if original_price is None:
            skipped_no_original_price += 1
            continue

        if item.get("price") is None:
            continue

        # 先按商品名分类；商品名分不出来的，再看 Metro 自己给的英文大类
        # 字段（比如 "Health & Beauty"）能不能兜底分类；两个都没有，
        # 才归"其他"——照样收录，至少商品名还能被搜到
        category_zh = classify(name_en)
        if category_zh is None:
            category_zh = CATEGORY_EN_FALLBACK_MAP.get(item.get("category_en"))
            if category_zh:
                category_en_fallback_count += 1
        if category_zh is None:
            category_zh = "其他"
            fallback_other_count += 1

        converted.append({
            "store": "metro",
            "category": category_zh,
            "nameZh": translate_name(name_en),
            "nameEn": name_en,
            "price": item["price"],
            "originalPrice": original_price,
            "unit": item.get("unit") or "each",
            "validFrom": None,
            "validTo": None,
            "url": item.get("link"),
        })

    with open(OUTPUT_FILE, "w", encoding="utf-8") as f:
        json.dump(converted, f, ensure_ascii=False, indent=2)

    print(f"[convert] 原始 {len(raw_items)} 条 -> 转换出 {len(converted)} 条可用商品")
    print(f"[convert] 跳过：非打折 {skipped_not_promo} 条")
    print(f"[convert] 跳过：找不到原价（没法算折扣）{skipped_no_original_price} 条")
    print(f"[convert] 跳过：按商品名排除 {skipped_excluded_by_name} 条（2026-08 起恒为0，不再排除）")
    print(f"[convert] 靠 Metro 自己的英文大类字段兜底分类的 {category_en_fallback_count} 条")
    print(f'[convert] 归到"其他"类（没匹配到具体类目，但照样收录）{fallback_other_count} 条')
    print(f"\n[convert] 已保存到 {OUTPUT_FILE}")


if __name__ == "__main__":
    convert()
