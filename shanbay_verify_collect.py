# -*- coding: utf-8 -*-
# 本工具仅个人学习使用，请勿高频爬取。
# =============================================================================
#  扇贝今日词表 · 采集结果对照验证（只读）
# -----------------------------------------------------------------------------
#  验证逻辑（两遍采集 + 截图）：
#    第一遍：逐页翻页采集，给每一页截图存档
#    第二遍：回到第 1 页，逐页重新读一次，与第一遍结果逐词对照
#    最后：  报告"两遍是否完全一致""每页词数是否吻合""有没有重复/遗漏"
#
#  输出：
#    probe_out\验证_今日复习_第1页.png ... 每页截图（可直接用眼睛核对）
#    probe_out\验证报告_今日复习.txt        对照结果
#
#  运行：
#      cd D:\不背
#      python shanbay_verify_collect.py --tab review
# =============================================================================

import re
import sys
import time
import argparse
import datetime
from pathlib import Path

WORDS_TABLE_URL = "https://web.shanbay.com/wordsweb/#/words-table"
BROWSER_DATA_DIR = Path(__file__).resolve().parent / "shanbay_browser_data"
OUTPUT_DIR = Path(__file__).resolve().parent / "probe_out"

TAB_LABELS = {"new": "今日新词", "review": "今日复习"}
SEL_WORD = "div[class*='index_wordName__']"
SEL_NEXT = "text=下一页"
SEL_PREV = "text=上一页"
PAGE_LOAD_TIMEOUT_MS = 60_000
MAX_PAGES = 40


def log(msg: str) -> None:
    print(f"[{datetime.datetime.now():%H:%M:%S}] {msg}", flush=True)


def read_words(page) -> list:
    """读当前页所有单词。"""
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


def declared_total(page) -> str:
    try:
        body = page.inner_text("body") or ""
    except Exception:
        return ""
    m = re.search(r"共\s*(\d+)\s*词", body)
    return m.group(0) if m else ""


def click_next(page) -> bool:
    try:
        locator = page.locator(SEL_NEXT).first
        if locator.count() == 0:
            return False
        try:
            if locator.is_disabled():
                return False
        except Exception:
            pass
        if "disabled" in (locator.get_attribute("class") or "").lower():
            return False
        locator.click(timeout=8000)
        return True
    except Exception:
        return False


def click_page_number(page, number: int) -> bool:
    """直接点页码（用于第二遍回到第 1 页）。"""
    try:
        locator = page.locator(f"text={number}").first
        locator.click(timeout=8000)
        return True
    except Exception:
        return False


def wait_change(page, old_first: str, timeout_ms: int = 15_000) -> list:
    deadline = time.time() + timeout_ms / 1000
    while time.time() < deadline:
        page.wait_for_timeout(500)
        now = read_words(page)
        if now and now[0] != old_first:
            return now
    return read_words(page)


def pass_collect(page, screenshot_prefix: str, report: list) -> list:
    """第一遍：逐页采集 + 截图。返回 [(页码, [词...]), ...]"""
    pages = []
    for index in range(1, MAX_PAGES + 1):
        current = read_words(page)
        pages.append((index, current))
        log(f"    采集第 {index} 页：{len(current)} 个词")
        try:
            page.screenshot(path=str(OUTPUT_DIR / f"{screenshot_prefix}_第{index}页.png"),
                            full_page=True)
        except Exception as exc:
            log(f"    截图失败：{exc}")

        old_first = current[0] if current else ""
        if not click_next(page):
            report.append(f"  第一遍：第 {index} 页后没有「下一页」，采集结束")
            break
        page.wait_for_timeout(2_000)
        after = wait_change(page, old_first)
        if not after or after[0] == old_first:
            report.append(f"  第一遍：第 {index} 页后内容未变化，采集结束")
            break
    return pages


def pass_recheck(page, expected_pages: list, report: list) -> list:
    """第二遍：回到第 1 页，逐页重读，用于与第一遍对照。"""
    # 回到第一页：反复点「上一页」
    for _ in range(len(expected_pages) + 3):
        try:
            prev = page.locator(SEL_PREV).first
            if prev.count() == 0 or prev.is_disabled():
                break
            prev.click(timeout=6000)
            page.wait_for_timeout(1_500)
        except Exception:
            break
    if not click_page_number(page, 1):
        report.append("  第二遍：无法回到第 1 页，改用「上一页」方式（可能已在第 1 页）")
    page.wait_for_timeout(2_500)

    pages = []
    for index in range(1, len(expected_pages) + 1):
        current = read_words(page)
        pages.append((index, current))
        old_first = current[0] if current else ""
        if not click_next(page):
            break
        page.wait_for_timeout(2_000)
        after = wait_change(page, old_first)
        if not after or after[0] == old_first:
            break
    return pages


def main() -> int:
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass

    parser = argparse.ArgumentParser(description="扇贝词表采集结果对照验证（只读）")
    parser.add_argument("--tab", choices=("new", "review"), default="review")
    parser.add_argument("--show-browser", action="store_true", help="显示浏览器窗口（可亲眼看着它翻）")
    args = parser.parse_args()

    try:
        from playwright.sync_api import sync_playwright
    except ImportError:
        log("未安装 Playwright。请执行： python -m pip install playwright && python -m playwright install chromium")
        return 1

    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    label = TAB_LABELS[args.tab]
    report = []
    report.append("扇贝词表 · 采集结果对照验证报告")
    report.append(f"时间：{datetime.datetime.now():%Y-%m-%d %H:%M:%S}")
    report.append(f"词表：{label}")
    report.append("")
    report.append("验证方法：同一账号、同一时刻，采集两遍并逐词对照；同时给每页截图存档。")
    report.append("")

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

            log(f"打开词表页，切到「{label}」……")
            page.goto(WORDS_TABLE_URL, wait_until="domcontentloaded", timeout=PAGE_LOAD_TIMEOUT_MS)
            page.wait_for_timeout(4_000)
            try:
                page.locator(f"text={label}").first.click(timeout=10_000)
                page.wait_for_timeout(3_000)
            except Exception as exc:
                report.append(f"  ⚠ 切换「{label}」失败：{type(exc).__name__}")

            deadline = time.time() + 45
            while time.time() < deadline and not read_words(page):
                page.wait_for_timeout(1_000)

            total_text = declared_total(page)
            report.append("=" * 70)
            report.append("一、第一遍采集 + 逐页截图")
            report.append("=" * 70)
            log("第一遍采集（含逐页截图）……")
            first_pass = pass_collect(page, f"验证_{label}", report)

            report.append("")
            report.append("=" * 70)
            report.append("二、第二遍采集（用于对照）")
            report.append("=" * 70)
            log("第二遍采集（回第一页重新读）……")
            second_pass = pass_recheck(page, first_pass, report)

            # ------------------- 对照分析 -------------------
            first_words = [w for _, ws in first_pass for w in ws]
            second_words = [w for _, ws in second_pass for w in ws]

            report.append("")
            report.append("=" * 70)
            report.append("三、对照结果")
            report.append("=" * 70)
            report.append(f"页面标注总数：{total_text or '（未读到）'}")
            report.append(f"第一遍：{len(first_pass)} 页，{len(first_words)} 个词")
            report.append(f"第二遍：{len(second_pass)} 页，{len(second_words)} 个词")
            report.append("")

            report.append("-- 逐页对照 --")
            max_pages = max(len(first_pass), len(second_pass))
            for i in range(max_pages):
                a = first_pass[i][1] if i < len(first_pass) else []
                b = second_pass[i][1] if i < len(second_pass) else []
                same = (a == b)
                report.append(f"  第 {i+1} 页：第一遍 {len(a)} 词，第二遍 {len(b)} 词，"
                              f"{'✅ 完全一致' if same else '❌ 不一致'}")
                if not same:
                    only_a = [w for w in a if w not in b]
                    only_b = [w for w in b if w not in a]
                    if only_a:
                        report.append(f"      仅第一遍有：{', '.join(only_a)}")
                    if only_b:
                        report.append(f"      仅第二遍有：{', '.join(only_b)}")
            report.append("")

            set_a = set(w.lower() for w in first_words)
            set_b = set(w.lower() for w in second_words)
            report.append(f"-- 整体对照 --")
            report.append(f"  两遍都出现的词：{len(set_a & set_b)} 个")
            report.append(f"  仅第一遍出现：{sorted(set_a - set_b) if set_a - set_b else '无'}")
            report.append(f"  仅第二遍出现：{sorted(set_b - set_a) if set_b - set_a else '无'}")
            report.append(f"  第一遍内部是否有重复：{'有' if len(first_words) != len(set_a) else '没有'}")
            report.append("")

            # 与页面标注比对
            if total_text:
                num = int(re.search(r"\d+", total_text).group())
                report.append("-- 与页面标注比对 --")
                report.append(f"  页面标注 {num} 词；第一遍采集 {len(set_a)} 个不同词；"
                              f"第二遍 {len(set_b)} 个不同词")
                if num == len(set_a) == len(set_b):
                    report.append("  ✅ 三方一致：采集数量可信")
                else:
                    report.append("  ⚠ 数量不一致，需要人工核对截图")
            report.append("")

            report.append("-- 截图存档 --")
            shots = sorted(OUTPUT_DIR.glob(f"验证_{label}_第*页.png"))
            for shot in shots:
                report.append(f"  {shot.name}")
            report.append("")
            report.append("请打开这些截图，与报告中对应页的单词逐个核对，即可确认抓取是否准确。")
            report.append("")

            log("验证完成。")

        except Exception as exc:
            report.append(f"验证过程出错：{type(exc).__name__}: {exc}")
            log(f"验证过程出错：{type(exc).__name__}: {exc}")
        finally:
            try:
                if context is not None:
                    context.close()
            except Exception:
                pass

    report_file = OUTPUT_DIR / f"验证报告_{label}.txt"
    report_file.write_text("\n".join(report), encoding="utf-8")
    print("")
    print("=" * 70)
    print(f"验证报告：{report_file}")
    print(f"逐页截图：{OUTPUT_DIR}\\验证_{label}_第N页.png")
    print("=" * 70)
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except KeyboardInterrupt:
        print("\n已手动中断。")
        sys.exit(130)
