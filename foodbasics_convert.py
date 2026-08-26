"""
将 foodbasics_scraper.py 生成的 foodbasics_raw.json 转换成网站用的
data.json 格式。

用法：
    python foodbasics_convert.py

输入：foodbasics_raw.json
输出：foodbasics_converted.json —— 可以直接拼进主 data.json 的 "items" 数组

分类这块：拿"品牌 + 商品名 + 细分类目(merchandise_category)"一起去跑
classify()——细分类目（比如 "Broth-base-soup mix"、"Cracker-soda"、
"Cheddar cheese piece"）里的关键词能补上纯商品名里没有的信号，明显比
只看商品名准。

⚠️ 特意没有把 categoryEn 这个"粗分类"（Pantry / Snacks / Dairy & Eggs
这种）拼进去参与关键词匹配——试过了，"Dairy & Eggs" 这种粗分类字面上带了
"Eggs"，会把明明是奶酪/酸奶的商品误判成"鸡蛋"类，粗分类噪音大于信号，
所以只用 DIRECT_CATEGORY_MAP 里明确列出的几个没有歧义的粗分类做兜底
（比如 "Household & Cleaning" 肯定是日用品），其余的完全靠细分类目 + 商品名
关键词判断。
"""

import json
import sys
from pathlib import Path

from zh_dictionary import translate_name
from category_rules import classify, is_excluded_by_name

INPUT_FILE = "foodbasics_raw.json"
OUTPUT_FILE = "foodbasics_converted.json"

for _stream in (sys.stdout, sys.stderr):
    if hasattr(_stream, "reconfigure"):
        _stream.reconfigure(encoding="utf-8", errors="replace")

# 只放没有歧义、可以直接下结论的粗分类；Pantry/Snacks/Dairy & Eggs/Frozen/
# Bread & Bakery Products 这些一个大类底下横跨好几个我们的分类，不放在
# 这里，交给细分类目 + 商品名关键词处理。
DIRECT_CATEGORY_MAP = {
    "Household & Cleaning": "日用品",
    "Beverages": "饮料",
}


def convert():
    path = Path(INPUT_FILE)
    if not path.exists() or path.stat().st_size == 0:
        print(f"[convert] {INPUT_FILE} 不存在或是空文件——foodbasics_scraper.py 大概率没跑成功，"
              f"检查一下上一步的输出，先把抓取跑通再来转换。")
        return
    with open(path, encoding="utf-8") as f:
        raw_items = json.load(f)

    converted = []
    skipped_no_discount = 0
    skipped_excluded_by_name = 0
    fallback_other_count = 0

    for item in raw_items:
        price = item.get("price")
        original_price = item.get("originalPrice")
        if price is None or original_price is None or original_price <= price:
            skipped_no_discount += 1
            continue

        name_en = item.get("name") or ""
        if item.get("brand"):
            name_en = f"{item['brand']} {name_en}"

        classify_text = name_en
        if item.get("merchandiseCategory"):
            classify_text = f"{classify_text} {item['merchandiseCategory']}"

        if is_excluded_by_name(classify_text):
            skipped_excluded_by_name += 1
            continue

        category_zh = classify(classify_text)
        if category_zh is None:
            category_zh = DIRECT_CATEGORY_MAP.get(item.get("categoryEn"))
        if category_zh is None:
            category_zh = "其他"
            fallback_other_count += 1

        converted.append({
            "store": "foodbasics",
            "category": category_zh,
            "nameZh": translate_name(name_en),
            "nameEn": name_en,
            "price": price,
            "originalPrice": original_price,
            "unit": item.get("unit") or "each",
            "validFrom": None,
            "validTo": None,
            "url": item.get("link"),
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
