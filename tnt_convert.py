"""
将 tnt_scraper.py 生成的 tnt_raw.json 转换成网站用的 data.json 格式。

用法：
    python tnt_convert.py

输入：tnt_raw.json
输出：tnt_converted.json —— 可以直接拼进主 data.json 的 "items" 数组

跟别的超市不一样的地方：T&T 商品名本身就是中文，不是英文，所以分类用
category_rules.classify_zh()（中文子串匹配），不是英文那套 classify()。

nameEn 字段（网站实际展示用的那个）直接放原始中文名；nameZh 走一遍
translate_name() 只是为了以防万一名字里混了英文词能被处理掉，对纯中文名
基本是原样返回。

2026-08 起不再排除任何商品——之前 is_excluded_by_name_zh() 会把美妆个护/
小家电这些整个跳过不收录，现在改成正经分类（归到"个护美妆"/"家居百货"
这两个新类目），保留这个函数调用只是兼容旧代码，它现在恒返回 False，
不会跳过任何东西。
"""

import json
import sys
from pathlib import Path

from zh_dictionary import translate_name
from category_rules import classify_zh, is_excluded_by_name_zh

INPUT_FILE = "tnt_raw.json"
OUTPUT_FILE = "tnt_converted.json"

for _stream in (sys.stdout, sys.stderr):
    if hasattr(_stream, "reconfigure"):
        _stream.reconfigure(encoding="utf-8", errors="replace")


def convert():
    path = Path(INPUT_FILE)
    if not path.exists() or path.stat().st_size == 0:
        print(f"[convert] {INPUT_FILE} 不存在或是空文件——tnt_scraper.py 大概率没跑成功"
              f"（比如中途被 403 拦下来了），检查一下上一步的输出，先把抓取跑通再来转换。")
        return
    with open(path, encoding="utf-8") as f:
        raw_items = json.load(f)

    converted = []
    skipped_no_name = 0
    skipped_no_discount = 0
    skipped_excluded_by_name = 0
    fallback_other_count = 0

    for item in raw_items:
        name = item.get("name")
        if not name:
            skipped_no_name += 1
            continue

        price = item.get("price")
        # 原价优先用 regularPrice（跟 was_price 基本一样，多一层保险取到值）
        original_price = item.get("regularPrice") or item.get("wasPrice")

        # 没有原价，或者原价跟现价一样（没真的打折，比如"2件$X"这种捆绑价
        # 这个接口字段里体现不出折扣），没法算折扣，跳过——跟别的超市 convert
        # 脚本的处理逻辑一致。
        if price is None or original_price is None or original_price <= price:
            skipped_no_discount += 1
            continue

        if is_excluded_by_name_zh(name):  # 2026-08 起恒返回 False，不会跳过任何商品
            skipped_excluded_by_name += 1
            continue

        category_zh = classify_zh(name)
        if category_zh is None:
            category_zh = "其他"
            fallback_other_count += 1

        weight_uom = item.get("weightUom")
        unit = f"/{weight_uom}" if weight_uom else "each"

        converted.append({
            "store": "tnt",
            "category": category_zh,
            "nameZh": translate_name(name),
            "nameEn": name,
            "price": price,
            "originalPrice": original_price,
            "unit": unit,
            "validFrom": item.get("validFrom"),
            "validTo": item.get("validTo"),
            "url": item.get("url"),
            "image": item.get("image"),
        })

    with open(OUTPUT_FILE, "w", encoding="utf-8") as f:
        json.dump(converted, f, ensure_ascii=False, indent=2)

    print(f"[convert] 原始 {len(raw_items)} 条 -> 转换出 {len(converted)} 条可用商品")
    print(f"[convert] 跳过：没有商品名 {skipped_no_name} 条")
    print(f"[convert] 跳过：没有折扣/价格信息不全 {skipped_no_discount} 条")
    print(f"[convert] 跳过：按商品名排除 {skipped_excluded_by_name} 条（2026-08 起恒为0，不再排除）")
    print(f'[convert] 归到"其他"类（没匹配到具体类目，但照样收录）{fallback_other_count} 条')
    print(f"\n[convert] 已保存到 {OUTPUT_FILE}")


if __name__ == "__main__":
    convert()
