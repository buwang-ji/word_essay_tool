# -*- coding: utf-8 -*-
# 本工具仅个人学习使用，请勿高频爬取。
# =============================================================================
#  扇贝单词网页版 · 抓词侦查脚本（只读，不改动任何数据、不提交任何内容）
# -----------------------------------------------------------------------------
#  目的：把「扇贝单词网页版到底长什么样」如实导出来，用来写抓词选择器：
#        真实网址 / 单词卡片的 HTML 结构 / 页面发出的请求 / 本地存储的键名
#
#  你只需要：
#      1) 运行本脚本（会弹出浏览器窗口）
#      2) 在浏览器里登录扇贝，并点进你要抓的那个页面
#         （例如「今日新词」或「复习 / 生词本」）
#      3) 等单词都显示出来后，回到终端按回车
#      4) 把生成的 probe_out\扇贝侦查报告.txt 发给开发者
#
#  运行：
#      cd D:\不背
#      python shanbay_probe.py
# =============================================================================

import sys
import datetime
from pathlib import Path

# ----------------------------- 可修改的配置 ---------------------------------
# 扇贝单词网页版入口（打开后你在浏览器里自己点进目标页面）
START_URL = "https://web.shanbay.com/wordsweb/"
# 输出目录
OUTPUT_DIR = Path(__file__).resolve().parent / "probe_out"
# 浏览器用户数据目录（保存登录状态）
BROWSER_DATA_DIR = Path(__file__).resolve().parent / "shanbay_browser_data"
# 页面加载超时（毫秒）
PAGE_LOAD_TIMEOUT_MS = 60_000
# 是否记录网络请求（只记录，不篡改、不重放）
RECORD_NETWORK = True
# 最多记录多少条请求
MAX_REQUESTS = 300
# ---------------------------------------------------------------------------


def log(msg: str) -> None:
    print(f"[{datetime.datetime.now():%H:%M:%S}] {msg}", flush=True)


def wait_page_stable(page, timeout_ms: int = 30_000) -> None:
    """等页面加载完并且标签页不再变化，避免采集时正好赶上跳转导致上下文被销毁。"""
    import time as _time

    deadline = _time.time() + timeout_ms / 1000
    while _time.time() < deadline:
        try:
            page.wait_for_load_state("domcontentloaded", timeout=8_000)
        except Exception:
            pass
        try:
            url1 = page.url
        except Exception:
            return
        page.wait_for_timeout(1_200)
        try:
            url2 = page.url
        except Exception:
            return
        if url1 == url2:          # 地址没变，说明稳定了
            return
    log("页面似乎一直在跳转，将按当前状态采集。")


def inspect_with_retry(page, attempts: int = 3) -> dict:
    """
    采集页面结构，失败自动重试。

    单页应用在采集瞬间可能正在重渲染，evaluate 有时会抛
    "Execution context was destroyed" —— 这种情况等一下重试即可。
    """
    last_error = None
    for index in range(1, attempts + 1):
        try:
            wait_page_stable(page)
            return page.evaluate(JS_INSPECT)
        except Exception as exc:
            last_error = exc
            log(f"第 {index} 次采集失败（{type(exc).__name__}），等 2 秒后重试……")
            try:
                page.wait_for_timeout(2_000)
            except Exception:
                pass
    raise RuntimeError(f"采集失败（已重试 {attempts} 次）：{last_error}")


def _try_screenshot(context, preferred_page, path):
    """
    截图：优先截你操作的那个标签页；如果它在采集过程中被关掉/跳转走了，
    就自动改用浏览器里剩下的任意一个可用标签页，保证截图一定有产出。
    """
    candidates = []
    for candidate in [preferred_page] + list(reversed(context.pages)):
        try:
            if not candidate.is_closed() and candidate not in candidates:
                candidates.append(candidate)
        except Exception:
            continue
    for candidate in candidates:
        try:
            candidate.bring_to_front()
            candidate.wait_for_timeout(400)
            candidate.screenshot(path=str(path), full_page=True)
            return candidate.url
        except Exception:
            continue
    return ""


# 采集页面结构的 JS：找出重复出现的容器、可能的单词元素、所有可见文本
JS_INSPECT = r"""
() => {
  const info = {};

  // 1) 通用容器候选：相同 tag+class 重复出现的元素，最可能是单词卡片
  const groups = {};
  for (const el of document.querySelectorAll('div, li, a, article, section, p, span')) {
    const cls = (typeof el.className === 'string' ? el.className : '').trim();
    if (!cls) continue;
    const text = (el.innerText || '').replace(/\s+/g, ' ').trim();
    if (!text || text.length > 120) continue;
    const key = el.tagName.toLowerCase() + '|' + cls;
    if (!groups[key]) groups[key] = { tag: el.tagName.toLowerCase(), cls: cls, count: 0, samples: [] };
    groups[key].count++;
    if (groups[key].samples.length < 6) groups[key].samples.push(text.slice(0, 60));
  }
  info.containers = Object.values(groups)
    .filter(g => g.count >= 2)
    .sort((a, b) => b.count - a.count)
    .slice(0, 30);

  // 2) 只含单个英文单词的元素（最像目标词）
  const wordLike = {};
  for (const el of document.querySelectorAll('*')) {
    if (el.children.length > 0) continue;
    const text = (el.innerText || '').trim();
    if (!/^[A-Za-z][A-Za-z' \-]{1,30}$/.test(text)) continue;
    const cls = (typeof el.className === 'string' ? el.className : '').trim();
    const key = el.tagName.toLowerCase() + '|' + cls;
    if (!wordLike[key]) wordLike[key] = { tag: el.tagName.toLowerCase(), cls: cls, count: 0, samples: [] };
    wordLike[key].count++;
    if (wordLike[key].samples.length < 10) wordLike[key].samples.push(text);
  }
  info.wordLike = Object.values(wordLike)
    .sort((a, b) => b.count - a.count)
    .slice(0, 30);

  // 3) 页面所有可见文本行
  const lines = [];
  for (const el of document.querySelectorAll('*')) {
    if (el.children.length > 0) continue;
    const t = (el.innerText || '').trim();
    if (t && t.length <= 40) lines.push(t);
    if (lines.length > 400) break;
  }
  info.textLines = lines;

  // 4) 本地存储键名（只看键名，不导出值，避免泄露登录凭证）
  try { info.localStorageKeys = Object.keys(localStorage); } catch (e) { info.localStorageKeys = ['读取失败']; }
  try { info.sessionStorageKeys = Object.keys(sessionStorage); } catch (e) { info.sessionStorageKeys = ['读取失败']; }

  info.url = location.href;
  info.title = document.title;
  info.bodyText = (document.body ? (document.body.innerText || '') : '').slice(0, 3000);
  return info;
}
"""


def main() -> int:
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass

    try:
        from playwright.sync_api import sync_playwright
    except ImportError:
        log("未安装 Playwright。请先执行：")
        log("    python -m pip install playwright")
        log("    python -m playwright install chromium")
        return 1

    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    BROWSER_DATA_DIR.mkdir(parents=True, exist_ok=True)

    report = []
    requests_log = []

    print("=" * 70)
    print(" 扇贝单词网页版 · 抓词侦查")
    print("=" * 70)
    print(" 接下来会弹出浏览器，请：")
    print("   1) 登录扇贝（扫码或账号密码都可以）")
    print("   2) 点进你要抓的那个页面（今日新词 / 复习 / 生词本）")
    print("   3) 等单词都显示出来")
    print("   4) 回到这个窗口，按回车")
    print("=" * 70)
    print("")

    with sync_playwright() as p:
        context = None
        try:
            context = p.chromium.launch_persistent_context(
                user_data_dir=str(BROWSER_DATA_DIR),
                headless=False,               # 必须看得见，你要在里面登录和点页面
                viewport={"width": 1440, "height": 900},
                locale="zh-CN",
            )
            page = context.pages[0] if context.pages else context.new_page()
            page.set_default_timeout(PAGE_LOAD_TIMEOUT_MS)

            # 记录网络请求（只记录：方法、地址、类型、状态码）
            if RECORD_NETWORK:
                def on_request(request):
                    if len(requests_log) < MAX_REQUESTS:
                        requests_log.append({
                            "method": request.method,
                            "url": request.url,
                            "type": request.resource_type,
                            "status": "",
                        })

                def on_response(response):
                    for item in reversed(requests_log):
                        if item["url"] == response.url and not item["status"]:
                            item["status"] = str(response.status)
                            break

                page.on("request", on_request)
                page.on("response", on_response)

            log(f"正在打开：{START_URL}")
            try:
                page.goto(START_URL, wait_until="domcontentloaded", timeout=PAGE_LOAD_TIMEOUT_MS)
            except Exception as exc:
                log(f"打开失败（{type(exc).__name__}: {exc}），你可以在浏览器地址栏手动输入网址。")
            log("请在浏览器里登录并点进目标页面，完成后回到这里按回车……")

            try:
                input()
            except (EOFError, KeyboardInterrupt, OSError):
                print()
                log("读不到回车输入，等待 15 秒后自动采集当前页面。")
                page.wait_for_timeout(15_000)

            # 给页面几秒钟把跳转/渲染收尾，避免正好卡在导航中间采集
            log("收到，等页面稳定下来……")
            try:
                page.wait_for_timeout(3_000)
            except Exception:
                pass

            # 定位你最后操作的那个标签页（SPA 里很可能不是 pages[-1]）
            active_page = page
            try:
                for candidate in reversed(context.pages):
                    try:
                        if not candidate.is_closed():
                            active_page = candidate
                            break
                    except Exception:
                        continue
            except Exception:
                pass
            try:
                if active_page is not page:
                    log(f"检测到多个标签页，改用最后打开的那个：{active_page.url[:100]}")
                page = active_page
            except Exception:
                pass

            # 等页面稳定（关键：你按回车那一刻可能正好在跳转）
            wait_page_stable(page)
            log(f"当前页面：{page.url[:120]}")

            # 缓慢滚动，触发懒加载
            try:
                height = page.evaluate("() => document.body.scrollHeight")
                position = 0
                while position < min(height, 8000):
                    position += 700
                    page.evaluate(f"window.scrollTo(0, {position})")
                    page.wait_for_timeout(600)
                    height = page.evaluate("() => document.body.scrollHeight")
                page.evaluate("window.scrollTo(0, 0)")
                page.wait_for_timeout(1200)
            except Exception as exc:
                log(f"滚动时出了点问题（不影响采集）：{type(exc).__name__}")

            log("正在采集页面结构……")
            info = inspect_with_retry(page)

            # 截图 + 源码
            try:
                shot = OUTPUT_DIR / "扇贝_页面截图.png"
                shot_url = _try_screenshot(context, page, shot)
                if shot_url:
                    log(f"已截图（{shot_url[:80]}）：{shot.name}")
                else:
                    log("截图失败：没有可用标签页。")
            except Exception as exc:
                log(f"截图失败：{exc}")
            try:
                (OUTPUT_DIR / "扇贝_页面源码.html").write_text(page.content(), encoding="utf-8")
            except Exception:
                pass

            # ---------------- 拼报告 ----------------
            report.append("扇贝单词网页版 · 抓词侦查报告")
            report.append(f"时间：{datetime.datetime.now():%Y-%m-%d %H:%M:%S}")
            report.append("")
            report.append("=" * 70)
            report.append("一、页面基本信息")
            report.append("=" * 70)
            report.append(f"真实网址：{info.get('url')}")
            report.append(f"页面标题：{info.get('title')}")
            report.append("")
            report.append("页面可见文本（前 1500 字）：")
            report.append((info.get("bodyText") or "（空）")[:1500])
            report.append("")

            report.append("=" * 70)
            report.append("二、单词元素候选（只含单个英文单词的元素，按出现次数排序）")
            report.append("   ★ 这里最上面那个通常就是目标词元素，写选择器就看它")
            report.append("=" * 70)
            for item in info.get("wordLike") or []:
                report.append(f"  [{item['count']:>4} 个] <{item['tag']} class=\"{item['cls']}\">")
                report.append(f"          样例：{' | '.join(item['samples'])}")
            report.append("")

            report.append("=" * 70)
            report.append("三、重复容器候选（相同 class 重复出现，可能是卡片外层）")
            report.append("=" * 70)
            for item in info.get("containers") or []:
                report.append(f"  [{item['count']:>4} 个] <{item['tag']} class=\"{item['cls']}\">")
                report.append(f"          样例：{' | '.join(item['samples'])}")
            report.append("")

            report.append("=" * 70)
            report.append("四、页面可见文本行")
            report.append("=" * 70)
            for line in (info.get("textLines") or [])[:200]:
                report.append(f"  {line}")
            report.append("")

            report.append("=" * 70)
            report.append("五、本地存储键名（只有键名，没有值，不涉及凭证泄露）")
            report.append("=" * 70)
            report.append(f"localStorage：{', '.join(info.get('localStorageKeys') or [])}")
            report.append(f"sessionStorage：{', '.join(info.get('sessionStorageKeys') or [])}")
            report.append("")

            if RECORD_NETWORK:
                report.append("=" * 70)
                report.append("六、页面发出的请求（诊断参考：能看出数据是从哪个地址取的）")
                report.append("=" * 70)
                for item in requests_log:
                    report.append(f"  {item['method']:>4} {item['status'] or '---':>4}  [{item['type']}] {item['url'][:160]}")
                report.append("")

            log("采集完成。")

        except Exception as exc:
            report.append(f"侦查过程出错：{type(exc).__name__}: {exc}")
            log(f"侦查过程出错：{type(exc).__name__}: {exc}")
        finally:
            try:
                if context is not None:
                    context.close()
            except Exception:
                pass

    report_file = OUTPUT_DIR / "扇贝侦查报告.txt"
    report_file.write_text("\n".join(report), encoding="utf-8")

    print("")
    print("=" * 70)
    print("侦查完成！请把下面这两个文件发给开发者：")
    print(f"  报告：{report_file}")
    print(f"  截图：{OUTPUT_DIR / '扇贝_页面截图.png'}")
    print("（源码文件 扇贝_页面源码.html 也留着，需要时再发）")
    print("=" * 70)
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except KeyboardInterrupt:
        print("\n已手动中断。")
        sys.exit(130)
