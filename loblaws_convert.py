"""
将 loblaws_scraper.py 生成的 loblaws_raw.json 转换成网站用的 data.json 格式。

用法：
    python loblaws_convert.py

输入：loblaws_raw.json
输出：loblaws_converted.json —— 可以直接拼进主 data.json 的 "items" 数组

商品名是英文，用英文那套 classify()。

跟 nofrills_convert.py 不一样的地方：nofrills 那边只认 dealType=="SALE"
（"LIMIT"只是限购提示，价格没变）。这次 loblaws 抓取带了 Member Only
Price / Multi-Buy 这些筛选条件，dealType 具体会是什么字符串不确定，所以
改成看 wasPrice 是不是真的比 price 高——只要现价比原价低，不管 dealType
写的是什么，都算数；不高的话，就算 dealType 显示是什么促销类型，也没有
真正降价，不收录。

2026-08 起不再排除任何商品——is_excluded_by_name() 恒返回 False，保留
调用只是兼容旧代码，美妆个护/厨具这些以前会被排除的东西现在会被 classify()
正常分类。
"""

import json
import sys
from pathlib import Path

from zh_dictionary import translate_name
from category_rules import classify, is_excluded_by_name

INPUT_FILE = "loblaws_raw.json"
OUTPUT_FILE = "loblaws_converted.json"

for _stream in (sys.stdout, sys.stderr):
    if hasattr(_stream, "reconfigure"):
        _stream.reconfigure(encoding="utf-8", errors="replace")


def convert():
    path = Path(INPUT_FILE)
    if not path.exists() or path.stat().st_size == 0:
        print(f"[convert] {INPUT_FILE} 不存在或是空文件——loblaws_scraper.py 大概率没跑成功，"
              f"检查一下上一步的输出，先把抓取跑通再来转换。")
        return
    with open(path, encoding="utf-8") as f:
        raw_items = json.load(f)

    converted = []
    skipped_no_discount = 0
    skipped_excluded_by_name = 0
    fallback_other_count = 0

    for item in raw_items:
        was_price = item.get("wasPrice")
        price = item.get("price")

        # 只要现价比原价低就算数，不管 dealType 写的是什么（SALE/LIMIT/
        # 别的没见过的类型），price 和 wasPrice 才是最终判断依据。
        if was_price is None or price is None or was_price <= price:
            skipped_no_discount += 1
            continue

        name_en = item.get("title")
        if item.get("brand"):
            name_en = f"{item['brand']} {name_en}"

        if is_excluded_by_name(name_en):
            skipped_excluded_by_name += 1
            continue

        category_zh = classify(name_en)
        if category_zh is None:
            category_zh = "其他"
            fallback_other_count += 1

        converted.append({
            "store": "loblaws",
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
    print(f"[convert] 跳过：没有折扣/价格信息不全 {skipped_no_discount} 条")
    print(f"[convert] 跳过：按商品名排除 {skipped_excluded_by_name} 条（2026-08 起恒为0，不再排除）")
    print(f'[convert] 归到"其他"类（没匹配到具体类目，但照样收录）{fallback_other_count} 条')
    print(f"\n[convert] 已保存到 {OUTPUT_FILE}")


if __name__ == "__main__":
    convert()

