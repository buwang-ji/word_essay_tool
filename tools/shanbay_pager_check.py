# -*- coding: utf-8 -*-
# 本工具仅个人学习使用，请勿高频爬取。
# =============================================================================
#  扇贝词表 · 翻页机制检测（只读，只点击分页按钮，不改动任何学习数据）
# -----------------------------------------------------------------------------
#  回答一个问题：词表到底怎么翻页？
#      a) 传统分页（有「下一页」按钮，每页 N 个词）
#      b) 无限滚动（滚到底自动加载更多）
#      c) 一次性全展示
#      d) 有「加载更多」按钮
#
#  做法：读当前页词数 → 找分页控件 → 反复点「下一页」/滚动 → 记录每页词数
#        最后自动点「上一页」回到你原来的位置
#
#  运行：
#      cd D:\不背
#      python shanbay_pager_check.py
#      python shanbay_pager_check.py --tab review     # 测今日复习
#
#  输出：probe_out\翻页检测报告.txt  +  翻页检测_第N页.png
# =============================================================================

import sys
import argparse
import datetime
from pathlib import Path

# ----------------------------- 配置 -----------------------------------------
BASE_URL = "https://web.shanbay.com/wordsweb/"
WORDS_TABLE_URL = "https://web.shanbay.com/wordsweb/#/words-table"
BROWSER_DATA_DIR = Path(__file__).resolve().parent / "shanbay_browser_data"
OUTPUT_DIR = Path(__file__).resolve().parent / "probe_out"

TAB_LABELS = {
    "new": "今日新词",
    "review": "今日复习",
    "all": "今日任务",
    "learning": "在学单词",
}

SEL_WORD = "div[class*='index_wordName__'], div[class*='wordName'], span[class*='wordName']"
PAGE_LOAD_TIMEOUT_MS = 60_000
# 最多点多少次「下一页」
MAX_PAGES = 40
# 每次点击后等待的时间（毫秒）
AFTER_CLICK_WAIT_MS = 2_500
# ---------------------------------------------------------------------------


def log(msg: str) -> None:
    print(f"[{datetime.datetime.now():%H:%M:%S}] {msg}", flush=True)


# 采集分页控件的结构信息
JS_PAGER_INFO = r"""
() => {
  const info = { found: [], totalText: '' };

  // 1) 词数提示，例如「共50词」
  const bodyText = document.body ? (document.body.innerText || '') : '';
  const m = bodyText.match(/共\s*(\d+)\s*词/);
  if (m) info.totalText = m[0];

  // 2) 找所有可能是分页控件的元素：包含"上一页/下一页"或纯数字的容器
  const seen = new Set();
  for (const el of document.querySelectorAll('div, ul, li, nav, span, button, a')) {
    const t = (el.innerText || '').replace(/\s+/g, ' ').trim();
    if (!t || t.length > 60) continue;
    const isPager = /上一页|下一页|加载更多|查看更多|load more/i.test(t);
    if (!isPager) continue;
    const cls = (typeof el.className === 'string' ? el.className : '').trim();
    const key = el.tagName.toLowerCase() + '|' + cls + '|' + t.slice(0, 20);
    if (seen.has(key)) continue;
    seen.add(key);
    info.found.push({
      tag: el.tagName.toLowerCase(),
      cls: cls,
      text: t,
      childCount: el.children.length,
      // 子元素明细，用来判断哪个是可点的「下一页」
      children: Array.from(el.children).slice(0, 8).map(c => ({
        tag: c.tagName.toLowerCase(),
        cls: (typeof c.className === 'string' ? c.className : '').trim(),
        text: (c.innerText || '').replace(/\s+/g, ' ').trim().slice(0, 20),
      })),
    });
  }

  // 3) 有没有无限滚动的迹象
  info.scrollHeight = document.body ? document.body.scrollHeight : 0;
  info.viewportHeight = window.innerHeight;
  info.windowScrollY = window.scrollY;

  return info;
}
"""


def read_words(page) -> list:
    """读当前可见的单词。"""
    words = []
    try:
        for element in page.query_selector_all(SEL_WORD):
            try:
                text = (element.inner_text() or "").strip()
            except Exception:
                continue
            for line in text.splitlines():
                line = line.strip()
                if line:
                    words.append(line)
                    break
    except Exception:
        pass
    return words


def find_pager(page):
    """返回 (下一页定位器, 上一页定位器)，找不到则为 None。"""
    next_loc = None
    prev_loc = None
    for candidate in ("下一页", "下页", "Next"):
        try:
            loc = page.locator(f"text={candidate}").first
            if loc.count() > 0:
                next_loc = loc
                break
        except Exception:
            continue
    for candidate in ("上一页", "上页", "Prev"):
        try:
            loc = page.locator(f"text={candidate}").first
            if loc.count() > 0:
                prev_loc = loc
                break
        except Exception:
            continue
    return next_loc, prev_loc


def main() -> int:
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass

    parser = argparse.ArgumentParser(description="扇贝词表翻页机制检测（只读）")
    parser.add_argument("--tab", choices=tuple(TAB_LABELS.keys()), default="review",
                        help="测哪个词表，默认 review（今日复习）")
    parser.add_argument("--show-browser", action="store_true", help="显示浏览器窗口")
    parser.add_argument("--max-pages", type=int, default=MAX_PAGES, help="最多翻多少页")
    args = parser.parse_args()

    try:
        from playwright.sync_api import sync_playwright
    except ImportError:
        log("未安装 Playwright。请执行： python -m pip install playwright && python -m playwright install chromium")
        return 1

    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    BROWSER_DATA_DIR.mkdir(parents=True, exist_ok=True)
    label = TAB_LABELS[args.tab]

    report = []
    report.append("扇贝词表 · 翻页机制检测报告")
    report.append(f"时间：{datetime.datetime.now():%Y-%m-%d %H:%M:%S}")
    report.append(f"测试词表：{label}")
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

            log(f"打开词表页：{WORDS_TABLE_URL}")
            page.goto(WORDS_TABLE_URL, wait_until="domcontentloaded", timeout=PAGE_LOAD_TIMEOUT_MS)
            page.wait_for_timeout(4000)

            # 切到目标词表
            if args.tab != "all":
                try:
                    page.locator(f"text={label}").first.click(timeout=8000)
                    page.wait_for_timeout(3000)
                    log(f"已切换到「{label}」")
                except Exception as exc:
                    log(f"切换「{label}」失败：{type(exc).__name__}，继续用当前视图")

            # 等单词出现
            deadline = datetime.datetime.now().timestamp() + 45
            while datetime.datetime.now().timestamp() < deadline:
                if read_words(page):
                    break
                page.wait_for_timeout(1000)

            first_words = read_words(page)
            log(f"当前页读到 {len(first_words)} 个词：{', '.join(first_words[:8])}……")

            # 分页控件结构
            try:
                pager = page.evaluate(JS_PAGER_INFO)
            except Exception as exc:
                pager = {"found": [], "totalText": "", "error": str(exc)}

            report.append("=" * 70)
            report.append("一、词表概况")
            report.append("=" * 70)
            report.append(f"当前页词数：{len(first_words)}")
            report.append(f"页面标注的总词数：{pager.get('totalText') or '（页面上没找到「共N词」）'}")
            report.append(f"单词样例：{', '.join(first_words[:10])}")
            report.append("")

            report.append("=" * 70)
            report.append("二、分页控件结构")
            report.append("=" * 70)
            if not pager.get("found"):
                report.append("  ⚠ 没找到含「上一页/下一页/加载更多」的控件")
            for item in pager.get("found") or []:
                report.append(f"  <{item['tag']} class=\"{item['cls']}\"> 文字：{item['text']!r}"
                              f"  子元素 {item['childCount']} 个")
                for child in item.get("children") or []:
                    report.append(f"      └ <{child['tag']} class=\"{child['cls']}\"> {child['text']!r}")
            report.append("")

            # 翻页测试
            report.append("=" * 70)
            report.append("三、翻页测试（反复点「下一页」，看每页词数和是否有新词）")
            report.append("=" * 70)

            next_loc, prev_loc = find_pager(page)
            if next_loc is None:
                report.append("  ⚠ 没有找到「下一页」按钮")
                log("没找到「下一页」按钮，测试滚动加载……")
                # 试无限滚动
                seen = set(w.lower() for w in first_words)
                for step in range(1, 11):
                    page.evaluate("window.scrollTo(0, document.body.scrollHeight)")
                    page.wait_for_timeout(2000)
                    now = read_words(page)
                    new = [w for w in now if w.lower() not in seen]
                    report.append(f"  第 {step} 次滚到底：共 {len(now)} 词，新增 {len(new)} 个")
                    if not new:
                        report.append("  → 没有新词，说明滚动加载已到底或不存在滚动加载")
                        break
                    seen.update(w.lower() for w in now)
            else:
                seen = set(w.lower() for w in first_words)
                total_pages = 1
                for page_index in range(1, args.max_pages + 1):
                    old_first = read_words(page)[:1]
                    try:
                        next_loc.click(timeout=8000)
                    except Exception as exc:
                        report.append(f"  第 {page_index} 次点击「下一页」失败：{type(exc).__name__} {exc}")
                        break
                    page.wait_for_timeout(AFTER_CLICK_WAIT_MS)
                    now = read_words(page)
                    new = [w for w in now if w.lower() not in seen]
                    changed = bool(now) and now[:1] != old_first
                    report.append(f"  第 {page_index} 次点下一页：本页 {len(now)} 词，新增 {len(new)} 个，"
                                  f"内容{'已变化' if changed else '未变化'}")
                    if page_index <= 3:
                        try:
                            page.screenshot(path=str(OUTPUT_DIR / f"翻页检测_第{page_index + 1}页.png"))
                        except Exception:
                            pass
                    if not changed or not new:
                        report.append("  → 内容不再变化，判定已到最后一页")
                        break
                    seen.update(w.lower() for w in now)
                    total_pages = page_index + 1
                report.append("")
                report.append(f"  合计翻到约 {total_pages} 页，累计不同单词 {len(seen)} 个")
                # 回到第一页
                if prev_loc is not None:
                    for _ in range(total_pages):
                        try:
                            prev_loc.click(timeout=5000)
                            page.wait_for_timeout(1500)
                        except Exception:
                            break
                    report.append("  已尝试点「上一页」回到第一页")

            report.append("")
            report.append("=" * 70)
            report.append("四、结论")
            report.append("=" * 70)
            if pager.get("found"):
                report.append("  页面存在分页控件 → 主脚本的翻页循环可用。")
            else:
                report.append("  页面没有传统分页控件 → 需要按滚动加载处理（把本报告发给开发者）。")
            report.append("")

            log("检测完成。")

        except Exception as exc:
            report.append(f"检测过程出错：{type(exc).__name__}: {exc}")
            log(f"检测过程出错：{type(exc).__name__}: {exc}")
        finally:
            try:
                if context is not None:
                    context.close()
            except Exception:
                pass

    report_file = OUTPUT_DIR / "翻页检测报告.txt"
    report_file.write_text("\n".join(report), encoding="utf-8")
    print("")
    print("=" * 70)
    print(f"检测完成，报告：{report_file}")
    print("=" * 70)
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except KeyboardInterrupt:
        print("\n已手动中断。")
        sys.exit(130)
