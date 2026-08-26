"""
一键跑完全部超市：抓取 -> 转换 -> 合并进 data.json

用法：
    python run_all.py

跟 Windows 批处理文件的区别：这个是纯 Python 写的，Windows/Mac/Linux 本地
都能跑，GitHub Actions 的服务器（默认是 Linux）也能直接跑——批处理文件
（.bat）只有 Windows 认，GitHub Actions 默认的 ubuntu-latest 跑不了。

============================================================
失败处理策略
============================================================
每个超市的 scraper 单独跑，某一家失败（比如 T&T 的 Cookie 过期了）不会
中断整个流程，会继续跑下一家。跑完所有 scraper 才开始跑 convert（同理，
某一家 convert 失败不影响其他家）。

最后会打印一份汇总，告诉你哪几家成功了、哪几家失败了。这个脚本自己的
退出码（exit code）规则：
    - 全部超市都失败 -> 退出码 1（GitHub Actions 会标红，说明这次运行
      八成哪里出了大问题，比如网络整个不通）
    - 至少有一家成功 -> 退出码 0（正常，允许个别超市偶尔失败，比如 Cookie
      过期这种预期内的小问题，不该让整个自动化任务被标记成"失败"）

============================================================
GitHub Actions 里怎么用
============================================================
workflow yml 里装完依赖之后，一行搞定：

    - name: Scrape all stores and update data.json
      env:
        TNT_COOKIE: ${{ secrets.TNT_COOKIE }}
      run: python run_all.py

⚠️ Longo's 用 Playwright，跑之前得先在 workflow 里装浏览器（这个只用装
一次，跟 pip install 放一起）：

    - name: Install Python deps
      run: |
        pip install requests beautifulsoup4 curl_cffi playwright
        playwright install --with-deps chromium
"""

import subprocess
import sys
from pathlib import Path

for _stream in (sys.stdout, sys.stderr):
    if hasattr(_stream, "reconfigure"):
        _stream.reconfigure(encoding="utf-8", errors="replace")

# (显示名字, scraper 文件名, convert 文件名)
STORES = [
    ("T&T",         "tnt_scraper.py",        "tnt_convert.py"),
    ("Loblaws",     "loblaws_scraper.py",    "loblaws_convert.py"),
    ("Metro",       "metro_scraper.py",      "metro_convert.py"),
    ("No Frills",   "nofrills_scraper.py",   "nofrills_convert.py"),
    ("Galleria",    "galleria_scraper.py",   "galleria_convert.py"),
    ("Food Basics", "foodbasics_scraper.py", "foodbasics_convert.py"),
    ("Longo's",     "longos_scraper.py",     "longos_convert.py"),
]

MERGE_SCRIPT = "merge_into_site.py"


def run_script(path: str) -> bool:
    """跑一个 python 脚本，成功返回 True。跑之前检查文件存不存在，
    免得因为少个文件就整段 traceback 糊一脸。"""
    if not Path(path).exists():
        print(f"  ⚠️ 找不到 {path}，跳过")
        return False
    result = subprocess.run([sys.executable, path])
    return result.returncode == 0


def main():
    scraper_ok = {}
    convert_ok = {}

    print("=" * 60)
    print("  第一步：抓取全部超市")
    print("=" * 60)
    for i, (name, scraper, _) in enumerate(STORES, 1):
        print(f"\n[{i}/{len(STORES)}] {name} ...")
        scraper_ok[name] = run_script(scraper)

    print("\n" + "=" * 60)
    print("  第二步：转换格式")
    print("=" * 60)
    for i, (name, _, convert) in enumerate(STORES, 1):
        print(f"\n[{i}/{len(STORES)}] {name} ...")
        convert_ok[name] = run_script(convert)

    print("\n" + "=" * 60)
    print("  第三步：合并进 data.json")
    print("=" * 60 + "\n")
    merge_ok = run_script(MERGE_SCRIPT)

    print("\n" + "=" * 60)
    print("  汇总")
    print("=" * 60)
    any_success = False
    for name, _, _ in STORES:
        s_ok = scraper_ok.get(name, False)
        c_ok = convert_ok.get(name, False)
        if s_ok and c_ok:
            any_success = True
            print(f"  ✅ {name}")
        elif s_ok and not c_ok:
            print(f"  ⚠️ {name}（抓取成功，转换失败——检查一下 {name} 的 convert 脚本报错）")
        else:
            print(f"  ❌ {name}（抓取失败——大概率是 Cookie/token 过期了，或者网站结构变了）")
    print(f"  合并进 data.json: {'✅ 成功' if merge_ok else '❌ 失败'}")
    print("=" * 60)

    if not any_success:
        print("\n[run_all] 全部超市都失败了，退出码设为 1。")
        sys.exit(1)

    print("\n[run_all] 至少有一家超市跑成功了，退出码设为 0。")
    sys.exit(0)


if __name__ == "__main__":
    main()
