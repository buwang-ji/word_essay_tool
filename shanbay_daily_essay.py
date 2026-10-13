# -*- coding: utf-8 -*-
# 本工具仅个人学习使用，请勿高频爬取。
# =============================================================================
#  扇贝单词 · 每日词表自动提取 + AI 生成考研英语语境短文（单文件版）
# -----------------------------------------------------------------------------
#  流程：Playwright 打开扇贝网页版今日词表 → 翻页取完所有单词
#        → 调用 DeepSeek 生成考研风格短文（目标词加粗 + 中文翻译）→ 保存 Markdown
#
#  首次使用：
#      pip install playwright requests
#      python -m playwright install chromium
#      然后运行一次 python shanbay_daily_essay.py --show-browser 扫码登录
#      （登录状态存进 shanbay_browser_data，之后免登录）
#
#  日常运行：
#      python shanbay_daily_essay.py --headless          # 今日新词，后台静默
#      python shanbay_daily_essay.py --tab review        # 今日复习
#      python shanbay_daily_essay.py --tab all           # 今日任务（新词＋复习）
#
#  页面结构说明（2026-10 实测 web.shanbay.com/wordsweb/#/words-table）：
#      单词元素   div[class*='index_wordName__']
#      音标元素   span[class*='index_phonetic__']
#      分页       上一页 / 1 2 3 / 下一页，每页 20 词，共 50 词
#      左侧导航   今日任务 / 今日新词 / 今日复习 / 在学单词 / 未学单词 / 简单词
#  CSS 类名带哈希后缀（如 index_wordName__3VqeJ），所以选择器用模糊匹配。
# =============================================================================

import os
import re
import sys
import time
import random
import shutil
import argparse
import datetime
import subprocess
from pathlib import Path

# =============================================================================
# ============================== 配 置 区 =====================================
# =============================================================================
# 公共工具：.env 读取 + VS Code 定位（与 read_essay.py 共用同一份实现）
sys.path.insert(0, str(Path(__file__).resolve().parent))
from common_utils import (          # noqa: E402
    load_dotenv as _load_dotenv_impl,
    env_int as _env_int_impl,
    env_bool as _env_bool_impl,
    env_str as _env_str_impl,
    find_vscode,
    open_files_in_vscode,
)

# 一、密钥读取方式（推荐用 .env 文件，别把 key 写进代码）------------------------
#   1) 复制同目录下的 .env.example 为 .env
#   2) 在里面填：DEEPSEEK_API_KEY=sk-你的key
#   3) 优先级：系统环境变量 > .env 文件
_load_dotenv_impl()


def _env_int(name: str, default: int) -> int:
    return _env_int_impl(name, default, warn=lambda m: print(f"[配置提醒] {m}"))


def _env_bool(name: str, default: bool = True) -> bool:
    return _env_bool_impl(name, default, warn=lambda m: print(f"[配置提醒] {m}"))


def _env_str(name: str, default: str = "") -> str:
    return _env_str_impl(name, default)


# API Key 只从环境变量 / .env 读取，代码里不留明文默认值
DEEPSEEK_API_KEY = (os.getenv("DEEPSEEK_API_KEY") or "").strip()
DEEPSEEK_API_URL = "https://api.deepseek.com/v1/chat/completions"
DEEPSEEK_MODEL = _env_str("DEEPSEEK_MODEL", "deepseek-chat")
DEEPSEEK_TIMEOUT = 180
DEEPSEEK_MAX_RETRY = 3
DEEPSEEK_TEMPERATURE = 0.8

def _env_int(name: str, default: int) -> int:
    """读整型配置：值非法时回退默认值，不让脚本因配置写错而崩溃。"""
    raw = (os.getenv(name) or "").strip()
    if not raw:
        return default
    try:
        return int(raw)
    except ValueError:
        print(f"[配置提醒] 环境变量 {name}={raw!r} 不是整数，已改用默认值 {default}")
        return default


def _env_bool(name: str, default: bool = True) -> bool:
    """读布尔配置：1/true/yes/on 为真，0/false/no/off 为假。"""
    raw = (os.getenv(name) or "").strip().lower()
    if not raw:
        return default
    if raw in ("1", "true", "yes", "on"):
        return True
    if raw in ("0", "false", "no", "off"):
        return False
    print(f"[配置提醒] 环境变量 {name}={raw!r} 不是布尔值，已改用默认值 {default}")
    return default


# 二、短文生成参数 -----------------------------------------------------------
# ★ 每天生成几篇：所有单词按篇数均分（推荐 2 = 每天两篇长文）
ESSAYS_PER_DAY = _env_int("ESSAYS_PER_DAY", 2)
# 每篇目标词数 = 该篇单词数 × 下面系数，并夹在 [MIN, MAX] 之间
# 系数越大文章越长、行文越舒展；6 表示"每个目标词约配 6 个词的篇幅"
ESSAY_WORDS_PER_TARGET = _env_int("ESSAY_WORDS_PER_TARGET", 6)
ESSAY_WORD_COUNT_MIN = 180      # 单篇保底词数
ESSAY_WORD_COUNT_MAX = 1400     # 单篇上限（词很多时允许写得更长）
ESSAY_WORD_COUNT = 180          # 兜底值（正常走上面的自动计算）
# 分篇之间调用 API 的间隔（秒）
BETWEEN_REQUEST_SLEEP = 3

# 三、扇贝页面配置 -----------------------------------------------------------
# 今日词表页面（单页应用，用 #/ 路由）
BASE_URL = "https://web.shanbay.com/wordsweb/"
WORDS_TABLE_URL = "https://web.shanbay.com/wordsweb/#/words-table"
# 默认取哪个词表：new=今日新词，review=今日复习，all=今日任务（词表页默认视图）
DEFAULT_TAB = "review"
# 各词表对应的左侧导航文字（脚本会点击它来切换）
TAB_LABELS = {
    "new": "今日新词",
    "review": "今日复习",
    "all": None,          # None = 不点击，直接用词表页默认视图
}
# 浏览器用户数据目录（保存登录状态）
BROWSER_DATA_DIR = "shanbay_browser_data"
# 页面加载超时（毫秒）
PAGE_LOAD_TIMEOUT_MS = 60_000
# 等待单词元素出现的超时（秒）
WORD_WAIT_TIMEOUT = 45
# 首次运行等待手动扫码登录的最长时间（秒）
LOGIN_WAIT_TIMEOUT = 180
# 翻页之间、采集元素之间的随机停顿（秒），模拟真人节奏
PAGE_TURN_DELAY = (1.2, 2.5)
ELEMENT_DELAY = (0.02, 0.08)
# 最多翻多少页（安全上限）
MAX_PAGES = 30

# 四、输出配置 ---------------------------------------------------------------
# 短文保存目录（默认脚本同级目录下的「短文」；目录不存在会自动创建）
# 可用环境变量 OUTPUT_DIR 指定（相对路径按脚本目录解析，也支持绝对路径）
_out_dir_env = (os.getenv("OUTPUT_DIR") or "").strip()
OUTPUT_DIR = (Path(_out_dir_env) if _out_dir_env
              else Path(__file__).resolve().parent / "短文")
if not OUTPUT_DIR.is_absolute():
    OUTPUT_DIR = Path(__file__).resolve().parent / OUTPUT_DIR
OUTPUT_FILENAME_TEMPLATE = "{date}_单词语境练习.md"
OUTPUT_ENCODING = "utf-8"
# 生成新短文前是否自动备份旧短文（强烈建议保持 True）
AUTO_BACKUP = _env_bool("AUTO_BACKUP", True)
# 备份目录与保留份数（每份备份只占几 KB）
BACKUP_DIR = OUTPUT_DIR.parent / (OUTPUT_DIR.name + "_备份")
BACKUP_KEEP = _env_int("BACKUP_KEEP", 14)
# 生成完成后是否自动用 VS Code 打开（可用环境变量 AUTO_OPEN_VSCODE=false 关闭）
AUTO_OPEN_VSCODE = _env_bool("AUTO_OPEN_VSCODE", True)
# 打开方式：'preview' = 直接进 Markdown 预览（推荐，加粗/标题会渲染）；
#           'plain'   = 普通编辑视图（看到 ** 原始标记）
VSCODE_OPEN_MODE = "preview"
# 打开哪些：'all' = 本次生成的全部文件；'first' = 只打开第 1 篇
VSCODE_OPEN_TARGET = "all"
# VS Code 路径探测逻辑在 common_utils.find_vscode()：
#   环境变量 VSCODE_PATH → PATH 里的 code 命令 → 各平台常见安装位置

# 五、提示词模板 -------------------------------------------------------------
PROMPT_TEMPLATE = """你是考研英语命题组风格的外教，请用下面全部 {count} 个单词写一篇{word_count}词左右的短文，主题贴合考研阅读常考话题（科技、社会、教育、心理学等）。

硬性要求：
1. 全部 {count} 个单词必须**一个不漏**地用在文中，每个词至少出现一次，并在英文正文中用 **加粗** 标记
2. 生僻词、抽象词也要自然融入，不允许为了塞词而写出生硬句子；可适当使用词形变化（如名词变动词、形容词变副词）
3. 语言风格贴近考研真题阅读：长句与短句交替，逻辑连贯，用词准确
4. 同一词族的词（如 judge / judgment / judicial）尽量放在相邻段落，便于对比记忆
5. 文末附上完整的中文翻译，中文里与目标词对应的词也要用 **加粗** 标出，便于中英对照；
   但翻译必须是通顺的纯中文，**不允许夹带任何英文单词**
   （例如 captive 要译成"受困者/俘虏"并加粗，不能直接写 captive）

单词列表（共 {count} 个）：
{word_list}"""

# 六、输出长度控制 -----------------------------------------------------------
# 留空则自动按目标词数估算；写入数字则强制使用该值
# （100 个目标词的长文如果 max_tokens 太小会被截断，所以这里给足）
DEEPSEEK_MAX_TOKENS = None      # None = 自动（约 目标词数 × 6）

# =============================================================================
# ============================== 配 置 区 结 束 ================================
# =============================================================================


# -----------------------------------------------------------------------------
# 通用小工具
# -----------------------------------------------------------------------------
def log(msg: str) -> None:
    print(f"[{datetime.datetime.now():%H:%M:%S}] {msg}", flush=True)


def setup_console_encoding() -> None:
    """Windows 控制台默认可能是 GBK，中文提示会报 UnicodeEncodeError，这里统一切到 UTF-8。"""
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(encoding="utf-8", errors="replace")
        except Exception:
            pass


WORD_PATTERN = re.compile(r"^[A-Za-z][A-Za-z'\- ]{0,30}$")

# 页面上的导航/按钮文字，避免被误当成生词
STOP_WORDS = {
    "new", "word", "words", "today", "review", "learn", "learning", "list",
    "home", "index", "login", "logout", "search", "setting", "settings",
    "shanbay", "qwerty", "shanbaycom", "sbnav", "index", "wordbook",
    "python", "word", "excel", "skin", "app", "ios", "android",
}


def clean_words(raw_items) -> list:
    """去重 + 过滤空字符串 + 过滤非英文内容，保持页面原有顺序。"""
    seen = set()
    result = []
    for item in raw_items:
        word = (item or "").strip().strip(".,;:!?()[]{}\"'“”‘’、，。；：！？…·-/\\|").strip()
        if not word or not WORD_PATTERN.match(word):
            continue
        if len(word.split()) == 1 and word.lower() in STOP_WORDS:
            continue
        key = word.lower()
        if key in seen:
            continue
        seen.add(key)
        result.append(word)
    return result


def essay_target_words(word_count: int) -> int:
    """按本篇的单词数量决定短文目标词数（词多则写长一点，避免漏词）。"""
    needed = int(word_count * ESSAY_WORDS_PER_TARGET)
    return max(ESSAY_WORD_COUNT_MIN, min(ESSAY_WORD_COUNT_MAX, needed))


def split_into_essays(words: list, essays: int, min_per_essay: int = 15) -> list:
    """
    把单词按篇数均分。

    例如 200 个词、2 篇 → 每篇 100 个（余数摊到前面几篇）。
    单词太少时不会硬拆成碎篇：每篇至少 min_per_essay 个词，篇数自动减少。
    返回 [[第1篇的词...], [第2篇的词...], ...]
    """
    essays = max(1, int(essays))
    # 篇数不能超过"按最少词数算出来的上限"
    max_essays = max(1, len(words) // max(1, min_per_essay))
    essays = min(essays, max_essays)
    if essays <= 1:
        return [list(words)] if words else []

    base, extra = divmod(len(words), essays)
    chunks = []
    start = 0
    for index in range(essays):
        size = base + (1 if index < extra else 0)   # 余数分给前面几篇
        chunks.append(words[start:start + size])
        start += size
    # 万一最后一篇过短，把它并进前一篇，避免出现只有两三个词的"碎篇"
    while len(chunks) > 1 and len(chunks[-1]) < min_per_essay:
        chunks[-2].extend(chunks.pop())
    return chunks


# -----------------------------------------------------------------------------
# 模块一：从扇贝网页版提取单词（Playwright 前端自动化）
# -----------------------------------------------------------------------------
# 选择器用模糊匹配，避免 CSS Modules 的哈希后缀改版后失效
# 注意：index_wordName__ 是实测的单词元素；后面几个是改版时的备选
SEL_WORD = (
    "div[class*='index_wordName__'], "
    "div[class*='wordName'], "
    "span[class*='wordName'], "
    "[class*='wordsInner'] [class*='name']"
)
SEL_WORD_ROW = "[class*='index_word__'], [class*='wordsInner']"
SEL_NEXT_PAGE = "text=下一页"
SEL_EXPORT = "text=导出今日词表"
# 音标特征：如果"单词"里出现这些符号，说明选择器选到了音标/整行容器
PHONETIC_MARK = re.compile(r"[/\[\]ˈˌːəɪʊɒæʌθðʃʒŋɜɡ]|\d")


def validate_words(words: list) -> tuple:
    """
    自检：确认取到的确实是一批英文单词，而不是音标或界面文字。

    返回 (是否通过, 问题说明)。取词结果不对劲时，脚本会带着说明停下来，
    而不是把垃圾数据发给 AI 白白花钱。
    """
    if not words:
        return False, "一个词都没取到"

    bad_phonetic = [w for w in words if PHONETIC_MARK.search(w)]
    if len(bad_phonetic) > max(1, len(words) // 5):
        return False, (
            f"有 {len(bad_phonetic)}/{len(words)} 个结果像音标或含数字，"
            f"例如：{', '.join(bad_phonetic[:5])} → 选择器选错元素了"
        )

    too_long = [w for w in words if len(w) > 25]
    if len(too_long) > max(1, len(words) // 5):
        return False, f"有 {len(too_long)} 个结果过长（像整行文本），例如：{', '.join(too_long[:3])}"

    lowered = [w for w in words if w.islower()]
    if not lowered and len(words) > 3:
        return False, f"结果全是大写/非小写形式，例如：{', '.join(words[:5])}，可能取到了标题或导航"

    if len(words) == 1 and len(words[0]) < 4:
        return False, f"只取到一个可疑结果：{words[0]}"

    return True, ""


def _read_visible_words(page) -> list:
    """读取当前页所有可见单词（只取第一行文本，避开音标）。"""
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
        time.sleep(random.uniform(*ELEMENT_DELAY))
    return words


def _looks_like_login_page(page) -> bool:
    """判断当前是否停在登录页。"""
    try:
        text = (page.inner_text("body") or "")[:3000]
    except Exception:
        return False
    keywords = ("登录", "扫码", "二维码", "手机号", "验证码", "微信登录", "密码")
    return sum(1 for k in keywords if k in text) >= 2


def _click_tab(page, label: str) -> bool:
    """点击左侧导航（今日新词 / 今日复习 …）。"""
    if not label:
        return False
    try:
        locator = page.locator(f"text={label}").first
        locator.click(timeout=8000)
        page.wait_for_timeout(2500)
        log(f"已切换到「{label}」。")
        return True
    except Exception as exc:
        log(f"切换「{label}」失败（{type(exc).__name__}），继续用当前视图。")
        return False


def _collect_with_pagination(page) -> list:
    """
    翻页取完整个词表。

    页面结构：每页 20 词，底部分页「上一页 / 1 2 3 / 下一页」。
    做法：读当前页 → 记录已读单词集合 → 点「下一页」→ 等出现新词 → 再读，
    直到没有新词或没有下一页。
    """
    all_words = []
    seen = set()

    for page_index in range(1, MAX_PAGES + 1):
        page_words = _read_visible_words(page)
        new_words = [w for w in page_words if w.lower() not in seen]
        for word in new_words:
            seen.add(word.lower())
        all_words.extend(new_words)
        log(f"第 {page_index} 页：读到 {len(page_words)} 个词，其中 {len(new_words)} 个是新词"
            f"（累计 {len(all_words)}）")

        # 找「下一页」：没有、或不可点，就结束
        try:
            next_button = page.locator(SEL_NEXT_PAGE).first
            if next_button.count() == 0:
                break
            disabled = next_button.is_disabled()
            classes = (next_button.get_attribute("class") or "")
            if disabled or "disabled" in classes.lower():
                log("已经到最后一页。")
                break
        except Exception:
            break

        old_first = page_words[0] if page_words else ""
        try:
            next_button.click(timeout=8000)
        except Exception as exc:
            log(f"点击「下一页」失败（{type(exc).__name__}），结束翻页。")
            break

        # 等页面刷新出不同的内容
        changed = False
        for _ in range(20):
            page.wait_for_timeout(500)
            now_words = _read_visible_words(page)
            if now_words and now_words[0] != old_first:
                changed = True
                break
        if not changed:
            log("翻页后内容未变化，判定已到末尾。")
            break

        time.sleep(random.uniform(*PAGE_TURN_DELAY))

    return all_words


def get_today_words(headless: bool = None, tab: str = None) -> list:
    """
    模块一：打开扇贝网页版今日词表，翻页读完全部单词。

    返回：去重后的单词列表（可能为空，由调用方提示）。
    """
    headless = False if headless is None else headless
    tab = tab or DEFAULT_TAB

    try:
        from playwright.sync_api import sync_playwright
    except ImportError:
        log("未安装 Playwright，请先执行：")
        log("    python -m pip install playwright")
        log("    python -m playwright install chromium")
        return []

    data_dir = Path(BROWSER_DATA_DIR)
    if not data_dir.is_absolute():
        data_dir = Path(__file__).resolve().parent / data_dir
    data_dir.mkdir(parents=True, exist_ok=True)

    words = []
    with sync_playwright() as p:
        context = None
        try:
            context = p.chromium.launch_persistent_context(
                user_data_dir=str(data_dir),
                headless=headless,
                viewport={"width": 1440, "height": 900},
                locale="zh-CN",
                args=["--disable-blink-features=AutomationControlled"],
            )
            page = context.pages[0] if context.pages else context.new_page()
            page.set_default_timeout(PAGE_LOAD_TIMEOUT_MS)

            log(f"正在打开扇贝词表页：{WORDS_TABLE_URL}")
            page.goto(WORDS_TABLE_URL, wait_until="domcontentloaded", timeout=PAGE_LOAD_TIMEOUT_MS)
            page.wait_for_timeout(4000)

            # 登录处理
            if _looks_like_login_page(page):
                if headless:
                    log("检测到需要登录，但当前是无头模式。请运行：")
                    log("    python shanbay_daily_essay.py --show-browser")
                    return []
                log("检测到需要登录，请在浏览器窗口中扫码/输入账号登录……")
                deadline = time.time() + LOGIN_WAIT_TIMEOUT
                while time.time() < deadline and _looks_like_login_page(page):
                    page.wait_for_timeout(2000)
                if _looks_like_login_page(page):
                    log(f"登录等待超时（{LOGIN_WAIT_TIMEOUT} 秒），请重新运行。")
                    return []
                log("登录完成，继续取词。")
                page.goto(WORDS_TABLE_URL, wait_until="domcontentloaded", timeout=PAGE_LOAD_TIMEOUT_MS)
                page.wait_for_timeout(4000)

            # 切到指定词表
            label = TAB_LABELS.get(tab)
            if label:
                _click_tab(page, label)

            # 等单词元素出现
            log(f"正在等待单词列表加载（最多 {WORD_WAIT_TIMEOUT} 秒）……")
            deadline = time.time() + WORD_WAIT_TIMEOUT
            found = False
            while time.time() < deadline:
                try:
                    if page.query_selector_all(SEL_WORD):
                        found = True
                        break
                except Exception:
                    pass
                page.wait_for_timeout(1000)

            if not found:
                log(f"{WORD_WAIT_TIMEOUT} 秒内没等到单词元素。可能原因：")
                log("  1) 今天没有该词表的任务（今日新词/复习为空）")
                log("  2) 登录状态失效 → 用 --show-browser 重新登录")
                log("  3) 页面改版 → 把 probe_out 里的新截图发给开发者更新选择器")
                return []

            log("开始翻页取词……")
            words = _collect_with_pagination(page)
            log(f"页面共读到 {len(words)} 个词。")
            for index, word in enumerate(words[:10], 1):
                log(f"  {index}. {word}")

        except Exception as exc:
            log(f"浏览器自动化出错：{type(exc).__name__}: {exc}")
        finally:
            try:
                if context is not None:
                    context.close()
            except Exception:
                pass

    words = clean_words(words)

    # 自检：确认取到的是一批英文单词，而不是音标或界面文字
    ok, reason = validate_words(words)
    if not ok:
        log(f"取词结果自检未通过：{reason}")
        log("为避免把错误数据发给 AI，本次停在取词阶段，不生成短文。")
        log("请运行 python shanbay_probe.py 重新生成一份页面报告，交给开发者更新选择器。")
        return []

    log(f"自检通过：{len(words)} 个单词看起来正常。")
    return words


# -----------------------------------------------------------------------------
# 模块二：调用 DeepSeek 生成短文
# -----------------------------------------------------------------------------
def generate_essay(words: list) -> str:
    """
    调用 DeepSeek 官方接口，用给定单词生成考研英语风格短文。
    返回 Markdown 正文；失败时返回空字符串。
    """
    if not words:
        log("单词列表为空，跳过短文生成。")
        return ""
    if not DEEPSEEK_API_KEY:
        log("未配置 API Key。请任选一种方式：")
        log("  方式 1（推荐）：把同目录下的 .env.example 复制成 .env，填入 DEEPSEEK_API_KEY=sk-xxx")
        log("  方式 2：设置系统环境变量 DEEPSEEK_API_KEY")
        return ""

    try:
        import requests
    except ImportError:
        log("未安装 requests，请执行： python -m pip install requests")
        return ""

    target = essay_target_words(len(words))
    prompt = PROMPT_TEMPLATE.format(
        count=len(words), word_count=target, word_list=", ".join(words)
    )
    # 输出长度：英文正文 + 中文翻译，按目标词数估算，避免长文被截断
    max_tokens = DEEPSEEK_MAX_TOKENS or max(2000, int(target * 6))
    payload = {
        "model": DEEPSEEK_MODEL,
        "messages": [
            {"role": "system", "content": "你是一位资深的考研英语外教，擅长用给定单词写出地道的考研阅读风格短文。"},
            {"role": "user", "content": prompt},
        ],
        "temperature": DEEPSEEK_TEMPERATURE,
        "max_tokens": max_tokens,
        "stream": False,
    }
    headers = {
        "Authorization": f"Bearer {DEEPSEEK_API_KEY}",
        "Content-Type": "application/json",
    }

    log(f"正在调用 DeepSeek（{DEEPSEEK_MODEL}）生成约 {target} 词短文"
        f"（目标词 {len(words)} 个，输出上限 {max_tokens} tokens）……")
    last_error = ""
    for attempt in range(1, DEEPSEEK_MAX_RETRY + 1):
        try:
            response = requests.post(
                DEEPSEEK_API_URL, headers=headers, json=payload, timeout=DEEPSEEK_TIMEOUT
            )
            if response.status_code != 200:
                last_error = f"HTTP {response.status_code}：{response.text[:300]}"
                log(f"第 {attempt} 次调用失败：{last_error}")
            else:
                data = response.json()
                choices = data.get("choices") or [{}]
                message = choices[0].get("message") or {}
                content = (message.get("content") or "").strip()
                if content:
                    log("生成完成。")
                    return content
                last_error = f"接口返回内容为空：{str(data)[:300]}"
                log(f"第 {attempt} 次调用失败：{last_error}")
        except requests.exceptions.Timeout:
            last_error = f"请求超时（{DEEPSEEK_TIMEOUT} 秒）"
            log(f"第 {attempt} 次调用失败：{last_error}")
        except requests.exceptions.RequestException as exc:
            last_error = f"网络异常：{exc}"
            log(f"第 {attempt} 次调用失败：{last_error}")
        except Exception as exc:
            last_error = f"{type(exc).__name__}: {exc}"
            log(f"第 {attempt} 次调用失败：{last_error}")

        if attempt < DEEPSEEK_MAX_RETRY:
            time.sleep(2 * attempt)

    log(f"DeepSeek 调用最终失败，原因：{last_error}")
    return ""


# -----------------------------------------------------------------------------
# 模块三：保存 Markdown
# -----------------------------------------------------------------------------
def backup_essays() -> str:
    """
    生成新短文之前，先把「短文」目录里的旧文件备份一份。

    备份位置：短文_备份\\yyyy-MM-dd_HHmmss\\
    只备份，不删除任何原文件；失败只提示、不中断生成。
    这是为了防止误删/覆盖导致已生成的短文丢失。
    """
    if not AUTO_BACKUP:
        return ""
    if not OUTPUT_DIR.exists():
        return ""
    try:
        files = [p for p in OUTPUT_DIR.iterdir() if p.is_file()]
    except Exception:
        return ""
    if not files:
        return ""

    try:
        stamp = datetime.datetime.now().strftime("%Y-%m-%d_%H%M%S")
        backup_dir = BACKUP_DIR / stamp
        backup_dir.mkdir(parents=True, exist_ok=True)
        count = 0
        for src in files:
            try:
                shutil.copy2(src, backup_dir / src.name)
                count += 1
            except Exception:
                continue
        if count:
            log(f"已备份 {count} 个旧文件 → {backup_dir}")
            _prune_backups()
            return str(backup_dir)
    except Exception as exc:
        log(f"备份旧文件时出错（不影响生成）：{type(exc).__name__}: {exc}")
    return ""


def _prune_backups() -> None:
    """只保留最近 BACKUP_KEEP 份备份，避免无限堆积。"""
    try:
        dirs = sorted(
            (d for d in BACKUP_DIR.iterdir() if d.is_dir()),
            key=lambda d: d.name,
            reverse=True,
        )
        for old in dirs[BACKUP_KEEP:]:
            shutil.rmtree(old, ignore_errors=True)
    except Exception:
        pass


def save_markdown(words: list, essay: str, date_str: str = None, part: int = 1) -> str:
    """
    保存练习为 Markdown：
        # {日期} 单词语境练习
        **今日单词：** 单词1, 单词2, ...
        ---
        （短文 + 翻译）

    文件名：{日期}_单词语境练习_1.md、_2.md ……（第几篇就写几）
    """
    date_str = date_str or datetime.date.today().isoformat()
    filename = OUTPUT_FILENAME_TEMPLATE.format(date=date_str).replace(".md", f"_{part}.md")
    file_path = OUTPUT_DIR / filename

    word_line = ", ".join(words) if words else "（今日未获取到单词）"
    essay_body = essay.strip() if essay and essay.strip() else "（本次未能生成短文，请检查 DeepSeek 配置或网络后重试。）"

    content = (
        f"# {date_str} 单词语境练习\n\n"
        f"**今日单词：** {word_line}\n\n"
        f"---\n\n"
        f"{essay_body}\n"
    )

    try:
        OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
        file_path.write_text(content, encoding=OUTPUT_ENCODING)
        log(f"已保存：{file_path}")
        return str(file_path)
    except Exception as exc:
        log(f"保存失败：{type(exc).__name__}: {exc}")
        return ""


def process_words(words: list, date_str: str, essays: int = None) -> list:
    """把单词按篇数均分，逐篇生成短文并保存。返回成功保存的文件路径列表。"""
    essays = ESSAYS_PER_DAY if essays is None else essays
    chunks = split_into_essays(words, essays)

    note = "" if len(chunks) == essays else f"（单词较少，实际生成 {len(chunks)} 篇）"
    log(f"共 {len(words)} 个单词，分 {len(chunks)} 篇："
        + "，".join(f"第 {i} 篇 {len(c)} 词" for i, c in enumerate(chunks, 1)) + note)

    saved_files = []
    for index, chunk in enumerate(chunks, 1):
        log(f"—— 第 {index}/{len(chunks)} 篇：{', '.join(chunk[:10])}"
            + ("……" if len(chunk) > 10 else ""))
        essay = generate_essay(chunk)
        path = save_markdown(chunk, essay, date_str, index)
        if path:
            saved_files.append(path)
        if index < len(chunks):
            time.sleep(BETWEEN_REQUEST_SLEEP)
    return saved_files


# -----------------------------------------------------------------------------
# 模块四：自动用 VS Code 打开生成的短文
# -----------------------------------------------------------------------------
def open_in_vscode(files: list) -> bool:
    """
    用 VS Code 打开刚生成的短文（路径探测与打开动作由 common_utils 提供）。

    preview 模式：打开后请求 Markdown 预览，加粗/标题会渲染。
    plain 模式：  只打开文件，看到 ** 原始 Markdown 标记。
    """
    if not AUTO_OPEN_VSCODE:
        return False
    if not files:
        log("没有生成文件，跳过自动打开。")
        return False

    if not find_vscode():
        log("没找到 VS Code，跳过自动打开。")
        log("如需此功能：在 .env 里设置 VSCODE_PATH 指向你的 code.cmd 路径。")
        return False

    targets = files if VSCODE_OPEN_TARGET == "all" else files[:1]
    log(f"正在用 VS Code 打开 {len(targets)} 个文件……")

    use_preview = (VSCODE_OPEN_MODE == "preview")
    if not open_files_in_vscode(targets, reuse_window=True, preview=use_preview):
        log("调用 VS Code 失败（不影响短文生成）。")
        return False

    if use_preview:
        log("已请求 Markdown 预览（没弹出预览就按 Ctrl+Shift+V）。")
    else:
        log("已用普通编辑视图打开（按 Ctrl+Shift+V 可切换预览）。")
    log("VS Code 窗口应该已经弹出来了。")
    return True


# -----------------------------------------------------------------------------
# 主入口
# -----------------------------------------------------------------------------
def parse_args():
    parser = argparse.ArgumentParser(description="扇贝单词每日词表 → AI 考研语境短文（仅个人学习使用）")
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument("--headless", action="store_true", help="无头（后台静默）运行")
    mode.add_argument("--show-browser", action="store_true", help="显示浏览器窗口（首次登录用）")
    parser.add_argument("--tab", choices=("new", "review", "all"), default=None,
                        help="取哪个词表：new=今日新词（默认），review=今日复习，all=今日任务")
    parser.add_argument("--words", default=None, help="跳过浏览器，直接用逗号分隔的单词生成（调试用）")
    parser.add_argument("--date", default=None, help="指定日期（YYYY-MM-DD），默认今天")
    parser.add_argument("--essays", type=int, default=None,
                        help=f"每天生成几篇（默认 {ESSAYS_PER_DAY}），所有单词按篇数均分")
    parser.add_argument("--no-open", action="store_true", help="生成后不要自动用 VS Code 打开")
    return parser.parse_args()


def main() -> int:
    setup_console_encoding()
    args = parse_args()

    headless = False
    if args.headless:
        headless = True
    elif args.show_browser:
        headless = False

    tab = args.tab or DEFAULT_TAB
    tab_label = {"new": "今日新词", "review": "今日复习", "all": "今日任务"}.get(tab, tab)
    date_str = args.date or datetime.date.today().isoformat()

    print("=" * 68)
    print(" 扇贝单词 · 每日词表 → AI 考研语境短文   （仅个人学习使用，请勿高频爬取）")
    print("=" * 68)

    # 1) 取词
    if args.words:
        words = clean_words(args.words.split(","))
        log(f"使用命令行传入的单词（共 {len(words)} 个），跳过浏览器取词。")
    else:
        log(f"运行模式：{'无头（后台）' if headless else '显示浏览器窗口'}｜词表：{tab_label}")
        words = get_today_words(headless=headless, tab=tab)

    if not words:
        log(f"没有从「{tab_label}」取到单词，本次不生成短文。")
        log("排查建议：1) 确认今天该词表有任务；")
        log("          2) 用 --show-browser 观察页面是否正常登录；")
        log("          3) 页面改版的话，重新跑 shanbay_probe.py 生成新报告。")
        return 1

    log(f"获取到 {len(words)} 个单词：{', '.join(words)}")

    # 备份旧短文（防止覆盖/误删造成丢失）
    backup_essays()

    # 2) 生成 + 3) 保存
    saved_files = process_words(words, date_str, essays=args.essays)
    if not saved_files:
        return 1

    print("-" * 68)
    log(f"全部完成：{len(words)} 个单词，生成 {len(saved_files)} 篇短文，输出目录 {OUTPUT_DIR}")

    # 4) 自动用 VS Code 打开（--no-open 可跳过）
    if args.no_open:
        log("已按 --no-open 跳过自动打开。")
    else:
        open_in_vscode(saved_files)

    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except KeyboardInterrupt:
        print("\n已手动中断，退出。")
        sys.exit(130)
