# -*- coding: utf-8 -*-
# 本工具仅个人学习使用，请勿高频爬取。
# =============================================================================
#  扇贝单词 · 今日词表自动翻页采集（只读，不改动任何学习数据）
# -----------------------------------------------------------------------------
#  自动执行你手动做的那套流程：
#      单词书 → 词表 → 今日复习 → 第 1 页翻到第 8 页，逐页记录
#
#  输出（都在 D:\不背\ 下）：
#      probe_out\今日复习_全部单词.txt     —— 每页单词 + 汇总，可直接看
#      probe_out\今日复习_采集报告.txt     —— 翻页过程日志（每页多少词、是否重复）
#
#  运行：
#      cd D:\不背
#      python shanbay_collect_words.py                    # 采集今日复习
#      python shanbay_collect_words.py --tab new          # 采集今日新词
#      python shanbay_collect_words.py --tab both         # 两个都采集
#      python shanbay_collect_words.py --show-browser     # 显示浏览器窗口
# =============================================================================

import re
import sys
import time
import random
import argparse
import datetime
from pathlib import Path

# ----------------------------- 配置 -----------------------------------------
WORDS_TABLE_URL = "https://web.shanbay.com/wordsweb/#/words-table"
BROWSER_DATA_DIR = Path(__file__).resolve().parent / "shanbay_browser_data"
OUTPUT_DIR = Path(__file__).resolve().parent / "probe_out"

# 左侧导航文字
TAB_LABELS = {
    "new": "今日新词",
    "review": "今日复习",
}

# 实测选择器：单词元素（class 带哈希后缀，用模糊匹配）
SEL_WORD = "div[class*='index_wordName__']"
SEL_NEXT = "text=下一页"
SEL_PREV = "text=上一页"

PAGE_LOAD_TIMEOUT_MS = 60_000
AFTER_CLICK_WAIT_MS = 2_000     # 点下一页后先等一会儿
MAX_PAGES = 40                  # 安全上限
# ---------------------------------------------------------------------------

# 音标特征（用来做自检：万一取到音标要能发现）
PHONETIC_MARK = re.compile(r"[/\[\]ˈˌːəɪʊɒæʌθðʃʒŋɜɡ]|\d")


def log(msg: str) -> None:
    print(f"[{datetime.datetime.now():%H:%M:%S}] {msg}", flush=True)


def read_words(page) -> list:
    """读当前页所有单词（每个元素只取第一行，避开音标）。"""
    words = []
    try:
        elements = page.query_selector_all(SEL_WORD)
    except Exception:
        return words
    for element in elements:
        try:
            text = (element.inner_text() or "").strip()
        except Exception:
            continue
        for line in text.splitlines():
            line = line.strip()
            if line:
                words.append(line)
                break
    return words


def count_words_text(page) -> str:
    """读页面上「共N词」的提示。"""
    try:
        body = page.inner_text("body") or ""
    except Exception:
        return ""
    m = re.search(r"共\s*(\d+)\s*词", body)
    return m.group(0) if m else ""


def total_pages(page) -> list:
    """读分页控件里的页码列表，例如 ['1','2',...,'8']。"""
    pages = []
    try:
        for element in page.query_selector_all("li, a, button, span"):
            try:
                text = (element.inner_text() or "").strip()
            except Exception:
                continue
            if text.isdigit() and len(text) <= 3:
                pages.append(int(text))
    except Exception:
        pass
    return sorted(set(pages))


def click_next(page) -> bool:
    """点「下一页」。"""
    try:
        locator = page.locator(SEL_NEXT).first
        if locator.count() == 0:
            return False
        try:
            if locator.is_disabled():
                return False
        except Exception:
            pass
        classes = ""
        try:
            classes = (locator.get_attribute("class") or "").lower()
        except Exception:
            pass
        if "disabled" in classes:
            return False
        locator.click(timeout=8000)
        return True
    except Exception as exc:
        log(f"    点「下一页」失败：{type(exc).__name__}")
        return False


def wait_for_change(page, old_first: str, timeout_ms: int = 15_000) -> list:
    """等页面翻页完成（首词变化），返回新一页的单词。"""
    deadline = time.time() + timeout_ms / 1000
    while time.time() < deadline:
        page.wait_for_timeout(500)
        now = read_words(page)
        if now and now[0] != old_first:
            return now
    return read_words(page)


def collect_tab(page, tab_key: str, report: list) -> dict:
    """
    采集一个词表的全部页面。

    返回 {'label':..., 'declared_total':..., 'pages':[(页码, [词...]), ...], 'words':[...]}
    """
    label = TAB_LABELS[tab_key]
    result = {"label": label, "declared_total": "", "pages": [], "words": []}

    log(f"切换词表 →「{label}」")
    try:
        page.locator(f"text={label}").first.click(timeout=10_000)
        page.wait_for_timeout(3_000)
    except Exception as exc:
        report.append(f"  ⚠ 切换「{label}」失败：{type(exc).__name__}: {exc}")
        log(f"切换「{label}」失败，继续用当前视图。")

    # 等单词出现
    deadline = time.time() + 45
    while time.time() < deadline:
        if read_words(page):
            break
        page.wait_for_timeout(1_000)

    first_page = read_words(page)
    if not first_page:
        report.append(f"  ⚠「{label}」页面上没读到任何单词")
        log(f"「{label}」没读到单词，跳过。")
        return result

    declared = count_words_text(page)
    nums = total_pages(page)
    result["declared_total"] = declared
    report.append(f"  页面标注：{declared or '（无）'}；分页页码：{nums if nums else '（未识别）'}")

    seen = set()
    old_first = first_page[0]
    for page_index in range(1, MAX_PAGES + 1):
        current = read_words(page) if page_index > 1 else first_page
        new_words = [w for w in current if w.lower() not in seen]
        for word in new_words:
            seen.add(word.lower())
        result["pages"].append((page_index, current))
        result["words"].extend(new_words)

        report.append(
            f"  第 {page_index} 页：{len(current)} 个词，新增 {len(new_words)} 个"
            f"（累计 {len(seen)}）｜{', '.join(current[:6])}…"
        )
        log(f"  第 {page_index} 页：{len(current)} 词，新增 {len(new_words)}（累计 {len(seen)}）")

        if page_index >= MAX_PAGES:
            report.append(f"  达到最大页数上限 {MAX_PAGES}，停止。")
            break

        old_first = current[0] if current else ""
        if not click_next(page):
            report.append("  没有「下一页」可点了，翻页结束。")
            break

        page.wait_for_timeout(AFTER_CLICK_WAIT_MS)
        after = wait_for_change(page, old_first)
        if after and after[0] == old_first:
            report.append("  翻页后内容没变化，判定已到最后一页。")
            break
        if not after:
            report.append("  翻页后读不到单词，停止。")
            break

    # 自检
    words = result["words"]
    bad = [w for w in words if PHONETIC_MARK.search(w)]
    if bad:
        report.append(f"  ⚠ 自检：{len(bad)} 个结果像音标或含数字，例如 {bad[:5]}")
    if declared:
        declared_num = int(re.search(r"\d+", declared).group())
        if declared_num == len(words):
            report.append(f"  ✅ 自检：采集数量 {len(words)} 与页面标注 {declared_num} 完全一致。")
            log(f"✅ 数量吻合：{len(words)} 词")
        elif declared_num > len(words):
            report.append(f"  ⚠ 自检：页面标注 {declared_num} 词，实际只采集 {len(words)} 词，"
                          f"疑似漏页（差 {declared_num - len(words)} 个），需要排查翻页。")
            log(f"⚠ 数量对不上：页面标注 {declared_num}，实际 {len(words)}，疑似漏页")
        else:
            report.append(f"  ℹ 自检：实际采集 {len(words)} 词，多于页面标注 {declared_num} 词"
                          f"（可能页面在采集期间加载了更多词）。")
            log(f"ℹ 实际 {len(words)} 多于标注 {declared_num}")

    return result


def write_collection(tab_key: str, data: dict) -> Path:
    """把采集结果写成可读的单词文件。"""
    label = data["label"]
    lines = []
    lines.append(f"扇贝 · {label} 全部单词")
    lines.append(f"采集时间：{datetime.datetime.now():%Y-%m-%d %H:%M:%S}")
    lines.append(f"页面标注总数：{data['declared_total'] or '未知'}")
    lines.append(f"实际采集数量：{len(data['words'])}")
    lines.append(f"共 {len(data['pages'])} 页")
    lines.append("")
    lines.append("=" * 60)
    lines.append("一、按页列出（对照网页上的分页）")
    lines.append("=" * 60)
    for page_index, page_words in data["pages"]:
        lines.append("")
        lines.append(f"【第 {page_index} 页】{len(page_words)} 个词")
        lines.append("  " + ", ".join(page_words))
    lines.append("")
    lines.append("=" * 60)
    lines.append("二、全部单词（去重后，可直接用于生成短文）")
    lines.append("=" * 60)
    lines.append(", ".join(data["words"]))
    lines.append("")

    out_file = OUTPUT_DIR / f"{label}_全部单词.txt"
    out_file.write_text("\n".join(lines), encoding="utf-8")
    return out_file


def main() -> int:
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass

    parser = argparse.ArgumentParser(description="扇贝今日词表自动翻页采集（只读）")
    parser.add_argument("--tab", choices=("new", "review", "both"), default="review",
                        help="采集哪个词表，默认 review（今日复习）")
    parser.add_argument("--show-browser", action="store_true", help="显示浏览器窗口")
    args = parser.parse_args()

    try:
        from playwright.sync_api import sync_playwright
    except ImportError:
        log("未安装 Playwright。请执行：")
        log("    python -m pip install playwright")
        log("    python -m playwright install chromium")
        return 1

    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    tabs = ["new", "review"] if args.tab == "both" else [args.tab]

    report = []
    report.append("扇贝 · 今日词表自动翻页采集报告")
    report.append(f"时间：{datetime.datetime.now():%Y-%m-%d %H:%M:%S}")
    report.append(f"词表：{' / '.join(TAB_LABELS[t] for t in tabs)}")
    report.append("")

    outputs = []
    with sync_playwright() as p:
        context = None
        try:
            context = p.chromium.launch_persistent_context(
                user_data_dir=str(BROWSER_DATA_DIR),
                headless=not args.show_browser,
                viewport={"width": 1440, "height": 900},
                locale="zh-CN",
            )
            page = context.pages[0] if context.pages else context.new_page()
            page.set_default_timeout(PAGE_LOAD_TIMEOUT_MS)

            log(f"打开词表页：{WORDS_TABLE_URL}")
            page.goto(WORDS_TABLE_URL, wait_until="domcontentloaded", timeout=PAGE_LOAD_TIMEOUT_MS)
            page.wait_for_timeout(4_000)

            for tab_key in tabs:
                log(f"===== 开始采集「{TAB_LABELS[tab_key]}」 =====")
                report.append("=" * 70)
                report.append(f"词表：{TAB_LABELS[tab_key]}")
                report.append("=" * 70)
                data = collect_tab(page, tab_key, report)
                report.append("")
                if data["words"]:
                    out_file = write_collection(tab_key, data)
                    outputs.append((out_file, len(data["words"])))
                    log(f"已写出：{out_file}（{len(data['words'])} 个词）")

        except Exception as exc:
            report.append(f"采集过程出错：{type(exc).__name__}: {exc}")
            log(f"采集过程出错：{type(exc).__name__}: {exc}")
        finally:
            try:
                if context is not None:
                    context.close()
            except Exception:
                pass

    report_file = OUTPUT_DIR / "今日词表_采集报告.txt"
    report_file.write_text("\n".join(report), encoding="utf-8")

    print("")
    print("=" * 70)
    if outputs:
        for out_file, count in outputs:
            print(f"✅ 采集完成：{count} 个单词 → {out_file}")
    else:
        print("⚠ 没有采集到任何单词，请看报告：")
    print(f"过程报告：{report_file}")
    print("=" * 70)
    return 0 if outputs else 1


if __name__ == "__main__":
    try:
        sys.exit(main())
    except KeyboardInterrupt:
        print("\n已手动中断。")
        sys.exit(130)
