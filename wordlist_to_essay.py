# -*- coding: utf-8 -*-
# 本工具仅个人学习使用，请勿高频爬取。
# =============================================================================
#  单词表 → AI 考研风格语境短文（本地版，不依赖任何网页自动化）
# -----------------------------------------------------------------------------
#  为什么不背单词网页版用不了、改用这个：
#      不背单词没有可用的网页版（/lexis/newword 是 404，首页也没有学习页面），
#      任何基于 Playwright 抓网页的方案都注定拿不到单词。
#      所以改成「你导出单词 → 本脚本读文本 → AI 生成短文」，
#      完全不依赖对方的页面结构，永远不会因为改版失效，也不涉及任何爬取。
#
#  你的操作（每天或每周一次，20 秒）：
#      1) 在不背单词 App 里把今日新词 / 生词本导出或分享成文本
#      2) 粘贴到本目录下的 单词.txt（一行一个词，或一整段乱文本都行）
#      3) 运行： D:\python\python.exe wordlist_to_essay.py
#
#  运行方式：
#      python wordlist_to_essay.py                    # 读默认的 单词.txt
#      python wordlist_to_essay.py 我的生词.md         # 读指定文件
#      python wordlist_to_essay.py --all              # 批量处理目录下所有词表文件
#      python wordlist_to_essay.py --words "a,b,c"     # 直接命令行给词（快速测试）
#
#  产出：与源文件同名的 Markdown，例如 单词_单词语境练习_2026-02-14.md
#        单词多于 CHUNK_SIZE 个时自动拆成多篇短文（1、2、3 …）
# =============================================================================

import os
import re
import sys
import time
import argparse
import datetime
from pathlib import Path

# =============================================================================
# ============================== 配 置 区 =====================================
# =============================================================================
# 一、DeepSeek 配置 -----------------------------------------------------------
# 在下面引号里填入你自己的 API Key（也可设置同名环境变量 DEEPSEEK_API_KEY）
DEEPSEEK_API_KEY = os.getenv("DEEPSEEK_API_KEY", "sk-你的API密钥填在这里")
DEEPSEEK_API_URL = "https://api.deepseek.com/v1/chat/completions"
DEEPSEEK_MODEL = "deepseek-chat"
DEEPSEEK_TIMEOUT = 180          # 单次请求超时（秒）
DEEPSEEK_MAX_RETRY = 3          # 失败重试次数
DEEPSEEK_TEMPERATURE = 0.8      # 0.8 左右比较适合写作

# 二、短文生成参数 -----------------------------------------------------------
# 单词少时保底词数；单词多时按 ESSAY_WORDS_PER_TARGET 自动放长
ESSAY_WORD_COUNT = 180
ESSAY_WORDS_PER_TARGET = 8      # 每个目标词大约需要多少词的篇幅
ESSAY_WORD_COUNT_MAX = 450      # 单篇上限，太长就分篇
# 每次生成多少个单词的短文（超过就自动拆成多篇，避免模型漏词）
CHUNK_SIZE = 12
# 单词之间生成间隔（秒），避免连续高频请求
BETWEEN_REQUEST_SLEEP = 3

# 三、输入输出配置 -----------------------------------------------------------
# 默认词表文件名（放在脚本同级目录）
DEFAULT_WORD_FILE = "单词.txt"
# 输出目录（默认脚本同级目录）
OUTPUT_DIR = Path(__file__).resolve().parent / "短文"
# 输出文件名模板：{stem}=源文件名，{date}=日期，{part}=第几篇（>1 时才加）
OUTPUT_FILENAME_TEMPLATE = "{stem}_单词语境练习_{date}{part}.md"
OUTPUT_ENCODING = "utf-8"
# 是否在生成时打印完整短文（True 会把内容也打到终端）
PRINT_ESSAY = False

# 四、提示词模板 -------------------------------------------------------------
PROMPT_TEMPLATE = """你是考研英语命题组风格的外教，请用下面所有单词写一篇{word_count}词左右的短文，主题贴合考研阅读常考话题（科技、社会、教育、心理学等）。
要求：
1. 所有目标单词必须自然融入文中，并用 **加粗** 标记
2. 语言风格贴近真题阅读，用词准确，逻辑通顺
3. 文末附上完整的中文翻译
单词列表：{word_list}"""

# =============================================================================
# ============================== 配 置 区 结 束 ================================
# =============================================================================


def log(msg: str) -> None:
    """带时间戳的控制台进度提示。"""
    print(f"[{datetime.datetime.now():%H:%M:%S}] {msg}", flush=True)


def setup_console_encoding() -> None:
    """Windows 控制台默认可能是 GBK，中文提示会报 UnicodeEncodeError，这里统一切到 UTF-8。"""
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(encoding="utf-8", errors="replace")
        except Exception:
            pass


# -----------------------------------------------------------------------------
# 单词过滤
# -----------------------------------------------------------------------------
# 只保留英文单词/短语：2 个及以上字母，允许词内 ' 或 -
WORD_PATTERN = re.compile(r"^[A-Za-z][A-Za-z'-]{1,}$")

# 英文功能词：从 App 里整段复制时（会带上界面英文、例句等）需要过滤掉
ENGLISH_STOP_WORDS = {
    "the", "a", "an", "and", "or", "but", "if", "of", "to", "in", "on", "at",
    "by", "for", "with", "from", "as", "is", "are", "was", "were", "be", "been",
    "being", "am", "do", "does", "did", "done", "have", "has", "had", "this",
    "that", "these", "those", "it", "its", "he", "she", "they", "them", "his",
    "her", "their", "you", "your", "we", "our", "us", "i", "me", "my", "not",
    "no", "yes", "so", "than", "then", "there", "here", "when", "where", "which",
    "who", "whom", "what", "how", "why", "all", "any", "some", "such", "only",
    "also", "too", "very", "can", "could", "will", "would", "shall", "should",
    "may", "might", "must", "about", "into", "over", "after", "before", "up",
    "down", "out", "off", "again", "more", "most", "other", "one", "two",
}

# 界面/导航/提示类词汇，从页面或 App 复制时容易混进来
UI_STOP_WORDS = {
    "bbdc", "com", "cn", "http", "https", "www", "app", "android", "ios",
    "login", "logout", "signin", "signup", "home", "index", "next", "prev",
    "previous", "back", "more", "less", "search", "setting", "settings",
    "profile", "account", "help", "about", "contact", "privacy", "terms",
    "loading", "please", "wait", "ok", "cancel", "confirm", "submit", "close",
    "open", "review", "learn", "newword", "lexis", "word", "words", "dashboard",
    "today", "tomorrow", "yesterday", "calendar", "progress", "report", "share",
    "download", "wechat", "weibo", "qq", "error", "found", "not", "page",
    "server", "apache", "tomcat", "unit", "lesson", "book", "list", "example",
    "sentence", "phonetic", "definition", "meaning", "translation", "audio",
}

# 所有需要过滤掉的词
STOP_WORDS = ENGLISH_STOP_WORDS | UI_STOP_WORDS


def clean_words(raw_items) -> list:
    """
    从任意文本里提取干净的英文单词列表：
    去重 + 过滤空字符串 + 过滤非英文内容 + 过滤功能词/界面词，保持原有顺序。
    """
    seen = set()
    result = []
    for item in raw_items:
        word = (item or "").strip().strip(".,;:!?()[]{}\"'“”‘’、，。；：！？…·-/\\|").strip()
        if not word:
            continue
        tokens = word.split()          # 允许短语，如 take account of
        if not tokens or len(tokens) > 4:
            continue
        if not all(WORD_PATTERN.match(t) for t in tokens):
            continue
        if len(tokens) == 1 and word.lower() in STOP_WORDS:
            continue
        key = word.lower()
        if key in seen:
            continue
        seen.add(key)
        result.append(word)
    return result


def extract_words_from_text(text: str) -> list:
    """
    从一整段文本里提取单词。

    同时支持两种输入：
      - 一行一个词（导出格式）→ 保留短语
      - 一整段文章/例句（复制格式）→ 按空白拆词
    """
    # 先按行试：如果大多数行本身就是单个英文词，说明是词表格式，保留短语
    lines = [ln.strip() for ln in text.splitlines()]
    candidate_lines = [ln for ln in lines if ln and re.match(r"^[A-Za-z][A-Za-z'\- ]{0,40}$", ln)]
    if candidate_lines:
        words = clean_words(candidate_lines)
        if len(words) >= 3:
            return words

    # 否则当作整段文本，按空白切词
    tokens = re.split(r"[\s,，、;；/|\t]+", text)
    return clean_words(tokens)


def read_words_from_file(path: Path) -> list:
    """读词表文件（自动尝试 UTF-8 / UTF-8-BOM / GBK 编码）。"""
    for encoding in ("utf-8-sig", "utf-8", "gbk", "utf-16"):
        try:
            text = path.read_text(encoding=encoding)
            log(f"已读取 {path.name}（编码 {encoding}，{len(text)} 字符）")
            return extract_words_from_text(text)
        except UnicodeDecodeError:
            continue
        except Exception as exc:
            log(f"读取 {path.name} 失败：{type(exc).__name__}: {exc}")
            return []
    log(f"无法识别 {path.name} 的编码，请另存为 UTF-8 后重试。")
    return []


# -----------------------------------------------------------------------------
# AI 短文生成
# -----------------------------------------------------------------------------
def essay_target_words(word_count: int) -> int:
    """按本批单词数量决定短文目标词数（词多则写长一点，避免漏词）。"""
    needed = int(word_count * ESSAY_WORDS_PER_TARGET)
    return max(ESSAY_WORD_COUNT, min(ESSAY_WORD_COUNT_MAX, needed))


def generate_essay(words: list) -> str:
    """
    调用 DeepSeek 官方接口，用给定的单词生成考研英语风格短文。
    返回 Markdown 正文；失败时返回空字符串。
    """
    if not words:
        log("单词列表为空，跳过短文生成。")
        return ""
    if not DEEPSEEK_API_KEY or DEEPSEEK_API_KEY.startswith("sk-你的"):
        log("未配置 DEEPSEEK_API_KEY，请在脚本顶部配置区填入密钥（或设置同名环境变量）。")
        return ""

    try:
        import requests
    except ImportError:
        log("未安装 requests，请执行： D:\\python\\python.exe -m pip install requests")
        return ""

    target = essay_target_words(len(words))
    prompt = PROMPT_TEMPLATE.format(word_count=target, word_list=", ".join(words))
    payload = {
        "model": DEEPSEEK_MODEL,
        "messages": [
            {"role": "system", "content": "你是一位资深的考研英语外教，擅长用给定单词写出地道的考研阅读风格短文。"},
            {"role": "user", "content": prompt},
        ],
        "temperature": DEEPSEEK_TEMPERATURE,
        "stream": False,
    }
    headers = {
        "Authorization": f"Bearer {DEEPSEEK_API_KEY}",
        "Content-Type": "application/json",
    }

    log(f"正在调用 DeepSeek（{DEEPSEEK_MODEL}）生成约 {target} 词短文（{len(words)} 个目标词）……")
    last_error = ""
    for attempt in range(1, DEEPSEEK_MAX_RETRY + 1):
        try:
            response = requests.post(
                DEEPSEEK_API_URL,
                headers=headers,
                json=payload,
                timeout=DEEPSEEK_TIMEOUT,
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
# 保存 Markdown
# -----------------------------------------------------------------------------
def save_markdown(stem: str, words: list, essay: str, date_str: str = None, part: int = 1) -> str:
    """
    保存一篇练习为 Markdown。

    文件结构：
        # {日期} 单词语境练习
        **今日单词：** 单词1, 单词2, ...
        ---
        （短文 + 翻译）
    """
    date_str = date_str or datetime.date.today().isoformat()
    part_suffix = "" if part <= 1 else f"_{part}"
    filename = OUTPUT_FILENAME_TEMPLATE.format(stem=stem, date=date_str, part=part_suffix)
    file_path = OUTPUT_DIR / filename

    word_line = ", ".join(words) if words else "（本批未获取到单词）"
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


# -----------------------------------------------------------------------------
# 主流程
# -----------------------------------------------------------------------------
def process_words(words: list, stem: str, date_str: str) -> int:
    """把一批单词拆成若干份，逐份生成短文并保存。返回成功生成的文件数。"""
    if not words:
        log(f"{stem}：没有提取到任何英文单词。")
        log("请确认文件里确实是英文单词（一行一个，或用空格/逗号分隔都可以）。")
        return 0

    log(f"{stem}：共提取到 {len(words)} 个单词：{', '.join(words[:20])}"
        + ("……" if len(words) > 20 else ""))

    # 按 CHUNK_SIZE 分片，避免一篇短文塞太多词导致模型漏词
    chunks = [words[i:i + CHUNK_SIZE] for i in range(0, len(words), CHUNK_SIZE)]
    log(f"将分成 {len(chunks)} 篇生成（每篇最多 {CHUNK_SIZE} 个目标词）。")

    saved_count = 0
    for index, chunk in enumerate(chunks, 1):
        log(f"—— 第 {index}/{len(chunks)} 篇：{', '.join(chunk)}")
        essay = generate_essay(chunk)
        if PRINT_ESSAY and essay:
            print("-" * 68)
            print(essay)
            print("-" * 68)
        if save_markdown(stem, chunk, essay, date_str, index):
            saved_count += 1
        if index < len(chunks):
            time.sleep(BETWEEN_REQUEST_SLEEP)  # 避免连续高频请求

    return saved_count


def parse_args():
    parser = argparse.ArgumentParser(description="单词表 → AI 考研语境短文（本地版，不依赖网页自动化）")
    parser.add_argument("file", nargs="?", default=None, help=f"词表文件路径（默认 {DEFAULT_WORD_FILE}）")
    parser.add_argument("--all", action="store_true", help="批量处理脚本目录下所有词表文件")
    parser.add_argument("--words", default=None, help="直接用逗号分隔的单词生成（快速测试用）")
    parser.add_argument("--date", default=None, help="指定日期（YYYY-MM-DD），默认今天")
    return parser.parse_args()


def main() -> int:
    setup_console_encoding()
    args = parse_args()
    date_str = args.date or datetime.date.today().isoformat()

    print("=" * 68)
    print(" 单词表 → AI 考研语境短文   （仅个人学习使用）")
    print("=" * 68)

    # 方式一：命令行直接给词
    if args.words:
        words = clean_words(args.words.split(","))
        log(f"使用命令行传入的单词（共 {len(words)} 个）。")
        return 0 if process_words(words, "命令行", date_str) else 1

    # 方式二：批量处理目录下所有词表文件
    if args.all:
        patterns = ("*.txt", "*.md", "*.csv")
        files = []
        for pattern in patterns:
            for path in sorted(OUTPUT_DIR.glob(pattern)):
                if path.name.startswith("单词") and path.suffix.lower() == ".md":
                    continue  # 跳过本脚本生成的结果文件
                if "_单词语境练习_" in path.name:
                    continue
                files.append(path)
        if not files:
            log(f"目录里没找到词表文件（支持 {'、'.join(patterns)}）。")
            return 1
        log(f"批量模式：找到 {len(files)} 个词表文件。")
        total = 0
        for path in files:
            log(f"===== 处理 {path.name} =====")
            total += process_words(read_words_from_file(path), path.stem, date_str)
        log(f"批量完成：共生成 {total} 篇短文。")
        return 0 if total else 1

    # 方式三：读取单个词表文件（默认 单词.txt）
    target = Path(args.file) if args.file else (OUTPUT_DIR / DEFAULT_WORD_FILE)
    if not target.is_absolute():
        target = OUTPUT_DIR / target
    if not target.exists():
        log(f"找不到词表文件：{target}")
        log("请把从 App 导出的单词粘贴进这个文件（一行一个词，或一整段都可以），然后重新运行。")
        log(f"也可以临时用： python wordlist_to_essay.py --words \"abandon,absolute,compensate\"")
        return 1

    words = read_words_from_file(target)
    saved = process_words(words, target.stem, date_str)
    if not saved:
        return 1

    print("-" * 68)
    log(f"全部完成：{len(words)} 个单词，生成 {saved} 篇短文，都在 {OUTPUT_DIR}")
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except KeyboardInterrupt:
        print("\n已手动中断，退出。")
        sys.exit(130)
