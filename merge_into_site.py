"""
把 metro_convert.py 生成的 metro_converted.json 合并进网站主数据文件 data.json。

用法：
    python merge_into_site.py

假设的文件位置（跟这个脚本放一起，或者按需改下面的路径变量）：
    metro_converted.json  —— 上一步转换好的 metro 数据
    data.json             —— 网站主数据文件（原来那个手动示例数据）

会做的事：
    1. 读取 data.json
    2. 把里面所有 store == "metro" 的旧数据删掉（避免重复跑脚本导致数据翻倍）
    3. 把 metro_converted.json 里的新数据加进去
    4. 更新 data.json 里的 "updated" 日期
    5. 覆盖保存 data.json
"""

"""
把各个超市 {store}_convert.py 生成的 {store}_converted.json 全部合并进网站
主数据文件 data.json。

用法：
    python merge_into_site.py

会自动找当前文件夹里所有 "*_converted.json" 文件（比如 metro_converted.json、
galleria_converted.json……以后加新超市，只要文件名符合这个规律，不用改这个
脚本），一次性全部合并进去。

会做的事（每个 *_converted.json 文件都会走一遍）：
    1. 读取 data.json
    2. 把里面属于这个超市的旧数据删掉（避免重复跑脚本导致数据翻倍）
    3. 把新数据加进去
    4. 更新 data.json 里的 "updated" 日期
    5. 覆盖保存 data.json
"""

import glob
import json
from datetime import date
from pathlib import Path

DATA_JSON = "data.json"

# 如果 data.json 不存在或是空文件，用这个骨架新建一个（9个超市的基本信息）
DEFAULT_STORES = [
    {"id": "loblaws",   "name": "Loblaws",        "nameZh": "Loblaws",   "color": "#F2B705"},
    {"id": "nofrills",  "name": "No Frills",      "nameZh": "No Frills", "color": "#E1483C"},
    {"id": "longos",    "name": "Longo's",        "nameZh": "Longo's",  "color": "#4A7862"},
    {"id": "foodbasics","name": "Food Basics",    "nameZh": "Food Basics","color": "#C9812E"},
    {"id": "tnt",       "name": "T&T",            "nameZh": "大统华",     "color": "#B4231F"},
    {"id": "metro",     "name": "Metro",          "nameZh": "Metro",    "color": "#E1483C"},
    {"id": "galleria",  "name": "Galleria",       "nameZh": "家乐",       "color": "#8C4A2F"},
]


def load_site_data() -> dict:
    path = Path(DATA_JSON)
    if not path.exists() or path.stat().st_size == 0:
        print(f"[merge] {DATA_JSON} 不存在或是空文件，用默认骨架新建一个。")
        return {"updated": "", "stores": DEFAULT_STORES, "items": []}
    with open(path, encoding="utf-8") as f:
        content = f.read().strip()
    if not content:
        print(f"[merge] {DATA_JSON} 内容是空的，用默认骨架新建一个。")
        return {"updated": "", "stores": DEFAULT_STORES, "items": []}
    return json.loads(content)


def merge():
    site_data = load_site_data()
    site_data.setdefault("items", [])
    site_data.setdefault("stores", DEFAULT_STORES)

    converted_files = sorted(glob.glob("*_converted.json"))
    if not converted_files:
        print("[merge] 当前文件夹里没找到任何 *_converted.json 文件，什么都没做。")
        return

    total_added = 0
    for filename in converted_files:
        with open(filename, encoding="utf-8") as f:
            new_items = json.load(f)

        if not new_items:
            print(f"[merge] {filename} 是空的，跳过。")
            continue

        store_id = new_items[0].get("store")
        if not store_id:
            print(f"[merge] {filename} 里的数据没有 store 字段，跳过，检查一下转换脚本。")
            continue

        before_count = len(site_data["items"])
        site_data["items"] = [i for i in site_data["items"] if i.get("store") != store_id]
        removed = before_count - len(site_data["items"])

        site_data["items"].extend(new_items)
        total_added += len(new_items)

        print(f"[merge] {filename} (store={store_id})：清掉旧数据 {removed} 条，加入新数据 {len(new_items)} 条")

    site_data["updated"] = date.today().isoformat()

    with open(DATA_JSON, "w", encoding="utf-8") as f:
        json.dump(site_data, f, ensure_ascii=False, indent=2)

    print(f"\n[merge] 本次共处理 {len(converted_files)} 个超市的数据文件")
    print(f"[merge] 合并后 data.json 共 {len(site_data['items'])} 条")
    print(f"[merge] 已保存 {DATA_JSON}")


if __name__ == "__main__":
    merge()
