# -*- coding: utf-8 -*-
# =============================================================================
#  Essay Reader (terminal version)  v2
# -----------------------------------------------------------------------------
#  面向"文章会越攒越多"的场景设计：
#    · 按【日期分组】，先选日期、再选当天的第几篇（200 篇也只需点两下）
#    · 只显示最近 N 天，需要更多用 --all 或命令 d
#    · 支持筛选：u=只看未读  /关键词=按标题或目标词搜索
#    · 目录缓存到 .essay_index.json，几百篇也能秒开
#
#  用法：
#      python read_essay.py                 交互菜单（默认最近 7 天）
#      python read_essay.py --days 30       菜单显示最近 30 天
#      python read_essay.py --all           菜单显示全部日期
#      python read_essay.py 2026-10-13 2    直接读 2026-10-13 的第 2 篇
#      python read_essay.py latest          读最新一篇
#      python read_essay.py --find therapy  按目标词搜索（看哪篇含这个词）
#      python read_essay.py --list          纯文本清单
#      python read_essay.py --reset-read    清空已读标记
#
#  双击 read_essay.bat 即可使用。
# =============================================================================

import re
import sys
import json
import argparse
import datetime
from pathlib import Path

# 公共工具：.env 读取 + VS Code 定位（与主脚本共用一份，避免各写一遍）
sys.path.insert(0, str(Path(__file__).resolve().parent))
try:
    from common_utils import load_dotenv, find_vscode, open_files_in_vscode
except ImportError:      # 单文件运行时降级，不影响阅读功能
    def load_dotenv(path=None):
        return None

    def find_vscode():
        return ""

    def open_files_in_vscode(files, reuse_window=True, preview=False):
        return False

load_dotenv()

APP_DIR = Path(__file__).resolve().parent
SHORT_ESSAY_DIR = APP_DIR / "短文"
READ_STATE_FILE = APP_DIR / ".read_state.json"
INDEX_CACHE_FILE = APP_DIR / ".essay_index.json"

# 菜单默认显示最近多少天
DEFAULT_MENU_DAYS = 7


def setup_output_encoding() -> None:
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(encoding="utf-8", errors="replace")
        except Exception:
            pass


setup_output_encoding()

try:
    from rich.console import Console
    from rich.markdown import Markdown
    from rich.panel import Panel
    from rich.rule import Rule
    from rich.table import Table
    RICH_AVAILABLE = True
except ImportError:
    RICH_AVAILABLE = False


def log(msg: str) -> None:
    print(msg, flush=True)


# =============================================================================
# 数据层：扫描短文、提取元信息、缓存索引
# =============================================================================
def read_text(path: Path) -> str:
    for encoding in ("utf-8-sig", "utf-8", "gbk"):
        try:
            return path.read_text(encoding=encoding)
        except UnicodeDecodeError:
            continue
        except Exception as exc:
            return f"（读取失败：{type(exc).__name__}: {exc}）"
    return "（无法识别文件编码）"


def parse_essay(path: Path) -> dict:
    """解析一篇短文，取出菜单需要的信息。"""
    text = read_text(path)
    name = path.stem

    date = name.split("_")[0] if "_" in name else ""
    part = 0
    tail = name.rsplit("_", 1)[-1]
    if tail.isdigit():
        part = int(tail)

    title = ""
    words = []
    for line in text.splitlines():
        raw = line.strip()
        if not raw:
            continue
        if "今日单词" in raw:
            match = re.search(r"[:：]\s*\*{0,2}(.+?)\*{0,2}\s*$", raw)
            if match:
                words = [w.strip() for w in match.group(1).split(",") if w.strip()]
            continue
        if raw.startswith("#"):
            heading = raw.lstrip("#").strip().strip("* ")
            if not heading:
                continue
            if (date and date in heading) or "单词语境练习" in heading:
                continue
            title = heading
            break
        if raw.startswith("---") or raw.startswith("**今日单词") or raw.startswith(">"):
            continue
        if not title:
            title = raw.strip("* ")
            break

    return {
        "path": str(path),
        "name": path.name,
        "date": date,
        "part": part,
        "title": title,
        "words": words,
        "mtime": path.stat().st_mtime,
    }


def scan_essays(use_cache: bool = True) -> list:
    """扫描短文目录，返回按日期、篇号倒序排列的列表。"""
    if not SHORT_ESSAY_DIR.exists():
        return []

    files = [p for p in SHORT_ESSAY_DIR.glob("*.md") if p.is_file()]
    cache = {}
    if use_cache:
        try:
            cache = json.loads(INDEX_CACHE_FILE.read_text(encoding="utf-8"))
        except Exception:
            cache = {}

    items = []
    new_cache = {}
    for path in files:
        key = str(path)
        try:
            mtime = path.stat().st_mtime
        except Exception:
            continue
        cached = cache.get(key)
        if cached and abs(cached.get("mtime", 0) - mtime) < 1:
            record = cached
        else:
            record = parse_essay(path)
        new_cache[key] = record
        items.append(record)

    try:
        INDEX_CACHE_FILE.write_text(
            json.dumps(new_cache, ensure_ascii=False), encoding="utf-8"
        )
    except Exception:
        pass

    items.sort(key=lambda r: (r["date"], r["part"], r["name"]), reverse=True)
    return items


def load_read_state() -> set:
    try:
        return set(json.loads(READ_STATE_FILE.read_text(encoding="utf-8")).get("read", []))
    except Exception:
        return set()


def load_progress() -> str:
    """上次读到哪一篇（文件名）。用于恢复进度。"""
    try:
        return json.loads(READ_STATE_FILE.read_text(encoding="utf-8")).get("last", "")
    except Exception:
        return ""


def save_read_state(read_set: set, last: str = None) -> None:
    data = {"read": sorted(read_set)}
    if last is not None:
        data["last"] = last
    else:
        data["last"] = load_progress()
    try:
        READ_STATE_FILE.write_text(
            json.dumps(data, ensure_ascii=False, indent=1), encoding="utf-8"
        )
    except Exception:
        pass


def group_by_date(items: list) -> list:
    """把短文按日期分组，返回 [(日期, [篇...]), ...]（新的在前）。"""
    groups = {}
    for item in items:
        groups.setdefault(item["date"] or "(无日期)", []).append(item)
    result = []
    for date in sorted(groups.keys(), reverse=True):
        essays = sorted(groups[date], key=lambda r: r["part"])
        result.append((date, essays))
    return result


# =============================================================================
# 界面层
# =============================================================================
def console():
    return Console()


def show_date_menu(groups: list, read_set: set, days_limit: int, filter_text: str = "",
                   range_text: str = "", last_read: str = "") -> None:
    """一级菜单：按日期列出（默认只显示最近 N 天）。"""
    shown = groups[:days_limit] if days_limit > 0 else groups
    total_unread = sum(
        1 for _, essays in groups for e in essays if e["name"] not in read_set
    )
    total_all = sum(len(e) for _, e in groups)

    if RICH_AVAILABLE:
        c = console()
        c.print()
        subtitle = (f"[dim]共 {len(groups)} 天 / {total_all} 篇，"
                    f"未读 {total_unread} 篇[/dim]")
        if last_read:
            subtitle += f"\n[dim]上次读到：{last_read}[/dim]"
        if range_text:
            subtitle += f"\n[dim]时间范围：{range_text}[/dim]"
        if filter_text:
            subtitle += f"\n[dim]筛选：{filter_text}[/dim]"
        c.print(Panel.fit(
            "[bold cyan]短文阅读器[/bold cyan]\n"
            f"[dim]目录：{SHORT_ESSAY_DIR}[/dim]\n" + subtitle,
            border_style="cyan",
        ))
        c.print()

        table = Table(show_header=True, header_style="bold magenta", box=None, padding=(0, 2))
        table.add_column("#", justify="right", width=4)
        table.add_column("日期", width=12)
        table.add_column("篇数", justify="right", width=4)
        table.add_column("未读", justify="right", width=4)
        table.add_column("当天标题预览", overflow="ellipsis", max_width=48)

        for index, (date, essays) in enumerate(shown, 1):
            unread = sum(1 for e in essays if e["name"] not in read_set)
            preview = " ｜ ".join(
                f"{e['part']}.{e['title'][:24]}" for e in essays[:2] if e["title"]
            ) or "[dim](无标题)[/dim]"
            table.add_row(
                str(index),
                date,
                str(len(essays)),
                f"[bold green]{unread}[/bold green]" if unread else "[dim]0[/dim]",
                preview,
            )
        c.print(table)
        c.print()
        if len(groups) > len(shown):
            c.print(f"  [dim]（仅显示最近 {len(shown)} 天，输入 d 显示全部 "
                    f"{len(groups)} 天）[/dim]")
        c.print("  [bold yellow]编号[/bold yellow]=进入 · "
                "[bold yellow]l[/bold yellow]=最新 · "
                "[bold yellow]u[/bold yellow]=未读 · "
                "[bold yellow]t[/bold yellow]=时间范围 · "
                "[bold yellow]d[/bold yellow]=全部 · "
                "[bold yellow]r[/bold yellow]=刷新 · "
                "[bold yellow]q[/bold yellow]=退出")
        c.print("  [dim]直达某天：2026-07-01 2　搜索：直接输关键词[/dim]")
        c.print()
    else:
        print()
        print("=" * 78)
        print(f" 短文阅读器 ｜ {SHORT_ESSAY_DIR}")
        print(f" 共 {len(groups)} 天 / {total_all} 篇，未读 {total_unread} 篇")
        if last_read:
            print(f" 上次读到：{last_read}")
        if range_text:
            print(f" 时间范围：{range_text}")
        print("=" * 78)
        for index, (date, essays) in enumerate(shown, 1):
            unread = sum(1 for e in essays if e["name"] not in read_set)
            print(f"  [{index:>3}] {date}  {len(essays)}篇  未读{unread}")
        print()
        print("  编号=进入 · l 最新 · u 未读 · t 时间范围 · d 全部 · r 刷新 · q 退出")


def show_day_menu(date: str, essays: list, read_set: set) -> None:
    """二级菜单：某一天的所有短文。"""
    if RICH_AVAILABLE:
        c = console()
        c.print()
        c.print(Rule(f"[bold cyan]{date}[/bold cyan]　共 {len(essays)} 篇", style="cyan"))
        c.print()
        table = Table(show_header=True, header_style="bold magenta", box=None, padding=(0, 2))
        table.add_column("#", justify="right", width=4)
        table.add_column("状态", width=4)
        table.add_column("篇", justify="right", width=3)
        table.add_column("目标词", justify="right", width=6)
        table.add_column("标题", overflow="ellipsis", max_width=44)
        for index, item in enumerate(essays, 1):
            is_read = item["name"] in read_set
            table.add_row(
                str(index),
                "[dim]✓[/dim]" if is_read else "[bold green]●[/bold green]",
                str(item["part"]) if item["part"] else "-",
                str(len(item["words"])) if item["words"] else "-",
                item["title"] or "[dim](无标题)[/dim]",
            )
        c.print(table)
        c.print()
        c.print("  [bold yellow]编号[/bold yellow]=阅读 · "
                "[bold yellow]a[/bold yellow]=按顺序读完这一天 · "
                "[bold yellow]o 编号[/bold yellow]=VS Code 打开 · "
                "[bold yellow]b[/bold yellow]=返回日期列表")
        c.print()
    else:
        print()
        print("=" * 78)
        print(f" {date}　共 {len(essays)} 篇")
        print("=" * 78)
        for index, item in enumerate(essays, 1):
            mark = "✓" if item["name"] in read_set else "●"
            print(f"  [{index:>2}] {mark} 第{item['part']}篇 "
                  f"{len(item['words']):>3}词  {item['title'][:44]}")
        print()
        print("  编号=阅读 · a=顺序读完 · b=返回")


def show_essay(item: dict, read_set: set) -> None:
    path = Path(item["path"])
    text = read_text(path)
    if RICH_AVAILABLE:
        c = console()
        c.print()
        c.print(Rule(f"[bold cyan]{path.stem}[/bold cyan]", style="cyan"))
        c.print(f"[dim]{path}[/dim]")
        if item.get("words"):
            c.print(f"[dim]目标词 {len(item['words'])} 个："
                    f"{', '.join(item['words'][:12])}"
                    f"{' …' if len(item['words']) > 12 else ''}[/dim]")
        c.print()
        c.print(Markdown(text), justify="left")
        c.print()
        c.print(Rule(style="cyan"))
    else:
        print()
        print("=" * 78)
        print(f" {path.stem}\n {path}")
        print("=" * 78)
        print(text)
        print("=" * 78)

    read_set.add(item["name"])
    save_read_state(read_set, last=item["name"])   # 同时记录"上次读到"


def open_in_vscode(item: dict) -> None:
    """用 VS Code 打开这篇短文（路径探测与 .env 读取交给 common_utils）。"""
    try:
        from common_utils import open_files_in_vscode
    except ImportError:
        log("缺少 common_utils.py，跳过打开。")
        return
    if open_files_in_vscode([item["path"]]):
        log(f"已用 VS Code 打开：{item['name']}")
    else:
        log("没找到 VS Code（可在 .env 里用 VSCODE_PATH 指定路径），跳过打开。")


def search_items(items: list, keyword: str) -> list:
    """按标题或目标词搜索。"""
    kw = keyword.lower()
    hits = []
    for item in items:
        if kw in item["title"].lower() or any(kw in w.lower() for w in item["words"]):
            hits.append(item)
    return hits


def filter_by_range(items: list, start: str, end: str) -> list:
    """按日期区间过滤（含两端）。start/end 形如 2026-07-01，任一可为空。"""
    result = []
    for item in items:
        date = item["date"]
        if not date:
            continue
        if start and date < start:
            continue
        if end and date > end:
            continue
        result.append(item)
    return result


def days_ago(n: int) -> str:
    """返回 n 天前的日期字符串。"""
    return (datetime.date.today() - datetime.timedelta(days=n)).isoformat()


def show_range_prompt() -> tuple:
    """交互式询问日期区间。返回 (start, end)，都为空表示取消。"""
    print()
    print("  输入日期区间（格式 2026-07-01，留空表示不限）")
    print(f"  提示：今天是 {datetime.date.today().isoformat()}，"
          f"50 天前是 {days_ago(50)}，100 天前是 {days_ago(100)}")
    try:
        start = input("  起始日期：").strip()
        end = input("  结束日期：").strip()
    except (EOFError, KeyboardInterrupt):
        print()
        return "", ""
    return start, end


def pause() -> bool:
    """等回车；返回 False 表示用户中断（该退出）。"""
    print("按回车返回……")
    try:
        input()
        return True
    except (EOFError, KeyboardInterrupt):
        print()
        return False


# =============================================================================
# 交互主循环
# =============================================================================
def interactive(items: list, days_limit: int) -> int:
    read_set = load_read_state()
    filter_text = ""
    filter_hits = None          # 搜索命中的扁平列表
    range_start = ""
    range_end = ""

    # 当前视图（受时间范围影响）与按日期分组结果，循环内外都要用
    view_items = items
    groups = group_by_date(items)

    while True:
        if not items:
            log(f"短文目录里还没有文件：{SHORT_ESSAY_DIR}")
            log("先运行 启动-生成短文.bat 生成短文，再来阅读。")
            try:
                input("按回车退出……")
            except (EOFError, KeyboardInterrupt):
                print()
            return 1

        # ---------- 搜索结果视图 ----------
        if filter_hits is not None:
            if not filter_hits:
                log(f"没有匹配「{filter_text}」的短文。")
                filter_hits = None
                filter_text = ""
                continue
            if RICH_AVAILABLE:
                c = console()
                c.print()
                c.print(Rule(f"[bold cyan]搜索：{filter_text}[/bold cyan]"
                             f"　命中 {len(filter_hits)} 篇", style="cyan"))
                c.print()
                table = Table(show_header=True, header_style="bold magenta", box=None, padding=(0, 2))
                table.add_column("#", justify="right", width=4)
                table.add_column("状态", width=4)
                table.add_column("日期", width=12)
                table.add_column("篇", justify="right", width=3)
                table.add_column("标题", overflow="ellipsis", max_width=40)
                for index, item in enumerate(filter_hits[:30], 1):
                    table.add_row(
                        str(index),
                        "[dim]✓[/dim]" if item["name"] in read_set else "[bold green]●[/bold green]",
                        item["date"], str(item["part"]),
                        item["title"] or "[dim](无标题)[/dim]",
                    )
                c.print(table)
                c.print()
                c.print("  [bold yellow]编号[/bold yellow]=阅读 · [bold yellow]b[/bold yellow]=返回日期列表")
                c.print()
            else:
                print(f"\n搜索 {filter_text}：命中 {len(filter_hits)} 篇")
                for index, item in enumerate(filter_hits[:30], 1):
                    print(f"  [{index}] {item['date']} 第{item['part']}篇  {item['title'][:40]}")

            try:
                choice = input("请输入：").strip().lower()
            except (EOFError, KeyboardInterrupt):
                print()
                return 0

            if choice in ("b", "q", "quit", ""):
                filter_hits = None
                filter_text = ""
                continue
            if choice.isdigit():
                index = int(choice)
                if 1 <= index <= len(filter_hits):
                    show_essay(filter_hits[index - 1], read_set)
                    if not pause():
                        return 0
                continue
            continue

        # ---------- 日期列表视图 ----------
        # 先按时间范围过滤（如果设了范围），再分组
        view_items = filter_by_range(items, range_start, range_end) if (range_start or range_end) else items
        groups = group_by_date(view_items)
        range_text = f"{range_start or '最早'} ~ {range_end or '最新'}" if (range_start or range_end) else ""
        show_date_menu(groups, read_set, days_limit, filter_text, range_text, load_progress())
        try:
            choice = input("请输入：").strip()
        except (EOFError, KeyboardInterrupt):
            print()
            return 0

        low = choice.lower()
        if low in ("q", "quit", "exit"):
            return 0
        if low in ("r", "reload", ""):
            items = scan_essays()
            read_set = load_read_state()
            continue
        if low == "d":
            days_limit = 0          # 显示全部日期
            range_start = range_end = ""
            continue

        # 时间范围过滤（找"第 50 天"这种场景）
        if low == "t":
            start, end = show_range_prompt()
            if not start and not end:
                range_start = range_end = ""
                log("已清除时间范围。")
            else:
                range_start, range_end = start, end
                hit_items = filter_by_range(items, start, end)
                if not hit_items:
                    log(f"该范围内没有短文（{start or '最早'} ~ {end or '最新'}）。")
                    range_start = range_end = ""
                else:
                    days = len({it["date"] for it in hit_items})
                    log(f"范围内共 {days} 天 / {len(hit_items)} 篇。")
                    days_limit = 0
            continue

        # 只看未读
        if low == "u":
            unread_items = [it for it in items if it["name"] not in read_set]
            if not unread_items:
                log("全部都已读完了 🎉")
                continue
            filter_text = "未读"
            filter_hits = unread_items
            continue

        # 最新一天
        if low == "l":
            if groups:
                date, essays = groups[0]
                if enter_day(date, essays, read_set):
                    items = scan_essays()
                    read_set = load_read_state()
            continue

        # 只输入编号 → 进入某一天
        if choice.isdigit():
            index = int(choice)
            shown = groups[:days_limit] if days_limit > 0 else groups
            if 1 <= index <= len(shown):
                date, essays = shown[index - 1]
                if enter_day(date, essays, read_set):
                    items = scan_essays()
                    read_set = load_read_state()
            else:
                log(f"编号超出范围：1~{len(shown)}")
            continue

        # "2026-10-13 2" 这种一次到位
        parts = choice.split()
        if len(parts) == 2 and re.match(r"^\d{4}-\d{2}-\d{2}$", parts[0]) and parts[1].isdigit():
            date, part = parts[0], int(parts[1])
            target = next(
                (it for it in items if it["date"] == date and it["part"] == part), None
            )
            if target:
                show_essay(target, read_set)
                if not pause():
                    return 0
            else:
                log(f"没找到 {date} 的第 {part} 篇。")
            continue

        # 单独输入日期 → 进入该天
        if re.match(r"^\d{4}-\d{2}-\d{2}$", choice):
            essays = next((e for d, e in groups if d == choice), None)
            if essays:
                if enter_day(choice, essays, read_set):
                    items = scan_essays()
                    read_set = load_read_state()
            else:
                log(f"没有 {choice} 的短文。")
            continue

        # 其它输入 → 当作关键词搜索
        filter_text = choice
        filter_hits = search_items(items, choice)
        continue


def enter_day(date: str, essays: list, read_set: set) -> bool:
    """进入某一天的二级菜单。返回 True 表示需要刷新数据。"""
    while True:
        essays = sorted(essays, key=lambda r: r["part"])
        show_day_menu(date, essays, read_set)
        try:
            choice = input("请输入：").strip().lower()
        except (EOFError, KeyboardInterrupt):
            print()
            return True

        if choice in ("b", "q", "quit", ""):
            return True

        if choice == "a":
            # 顺序读完这一天（逐篇显示，按回车翻页）
            for item in essays:
                show_essay(item, read_set)
                try:
                    nxt = input("按回车读下一篇，输入 b 停止……").strip().lower()
                except (EOFError, KeyboardInterrupt):
                    print()
                    return True
                if nxt == "b":
                    break
            return True

        if choice.startswith("o"):
            target = choice[1:].strip()
            if target.isdigit() and 1 <= int(target) <= len(essays):
                open_in_vscode(essays[int(target) - 1])
            else:
                log("用法：o 2（打开当天的第 2 篇）")
            continue

        if choice.isdigit():
            index = int(choice)
            if 1 <= index <= len(essays):
                show_essay(essays[index - 1], read_set)
                if not pause():
                    return True
            else:
                log(f"编号超出范围：1~{len(essays)}")
            continue

        log("无效输入：编号 / a / o 编号 / b")


# =============================================================================
# 入口
# =============================================================================
def main() -> int:
    parser = argparse.ArgumentParser(description="命令行短文阅读器 v2（按日期分组 + 搜索）")
    parser.add_argument("target", nargs="*", default=None,
                        help="编号 / 日期 / 日期 篇号 / latest / 关键词")
    parser.add_argument("--days", type=int, default=DEFAULT_MENU_DAYS,
                        help=f"菜单显示最近多少天（默认 {DEFAULT_MENU_DAYS}，0=全部）")
    parser.add_argument("--all", action="store_true", help="显示全部日期")
    parser.add_argument("--list", action="store_true", help="纯文本清单")
    parser.add_argument("--find", default=None, help="按标题或目标词搜索")
    parser.add_argument("--range", nargs=2, metavar=("起始", "结束"), default=None,
                        help="只看某段日期，例如 --range 2026-07-01 2026-07-31")
    parser.add_argument("--jump", type=int, default=None, metavar="N",
                        help="跳到第 N 篇未读（1 = 最早那篇未读，即接着上次继续学）")
    parser.add_argument("--reset-read", action="store_true", help="清空已读标记")
    args = parser.parse_args()

    if args.reset_read:
        save_read_state(set(), last="")
        log("已清空已读标记与进度记录。")

    items = scan_essays()
    read_set = load_read_state()

    # 跳到第 N 篇未读（按时间正序，1 = 最早未读）
    if args.jump is not None:
        unread = sorted(
            (it for it in items if it["name"] not in read_set),
            key=lambda r: (r["date"], r["part"]),
        )
        if not unread:
            log("没有未读的短文了 🎉")
            return 0
        if not (1 <= args.jump <= len(unread)):
            log(f"未读共 {len(unread)} 篇，N 只能在 1~{len(unread)} 之间。")
            return 1
        item = unread[args.jump - 1]
        log(f"未读第 {args.jump}/{len(unread)} 篇：{item['date']} 第{item['part']}篇")
        show_essay(item, read_set)
        return 0

    # 只看某段日期
    if args.range:
        start, end = args.range
        hit_items = filter_by_range(items, start, end)
        if not hit_items:
            log(f"该范围内没有短文（{start} ~ {end}）。")
            return 1
        groups = group_by_date(hit_items)
        log(f"范围内共 {len(groups)} 天 / {len(hit_items)} 篇：")
        for date, essays in groups:
            log(f"  {date}（{len(essays)} 篇）")
            for item in essays:
                mark = "✓" if item["name"] in read_set else "●"
                log(f"     {mark} 第{item['part']}篇  {item['title']}")
        if not sys.stdin.isatty():
            return 0
        try:
            target = input("输入「日期 篇号」直接阅读（回车退出）：").strip()
        except (EOFError, KeyboardInterrupt):
            print()
            return 0
        if target:
            parts = target.split()
            if len(parts) == 2 and parts[1].isdigit():
                hit = next((it for it in hit_items
                            if it["date"] == parts[0] and it["part"] == int(parts[1])), None)
                if hit:
                    show_essay(hit, read_set)
                    return 0
            log("没找到对应的短文。")
        return 0

    if args.list:
        if not items:
            log(f"目录为空：{SHORT_ESSAY_DIR}")
            return 1
        for date, essays in group_by_date(items):
            log(f"{date}（{len(essays)} 篇）")
            for item in essays:
                mark = "✓" if item["name"] in read_set else "●"
                log(f"   {mark} 第{item['part']}篇 {len(item['words']):>3}词  {item['title']}")
        return 0

    if args.find:
        hits = search_items(items, args.find)
        if not hits:
            log(f"没有含「{args.find}」的短文。")
            return 1
        log(f"命中 {len(hits)} 篇：")
        for index, item in enumerate(hits, 1):
            mark = "✓" if item["name"] in read_set else "●"
            log(f"  [{index}] {mark} {item['date']} 第{item['part']}篇  {item['title']}")
        try:
            target = input("输入编号阅读（回车跳过）：").strip() if sys.stdin.isatty() else ""
        except (EOFError, KeyboardInterrupt):
            print()
            target = ""
        if target.isdigit() and 1 <= int(target) <= len(hits):
            show_essay(hits[int(target) - 1], read_set)
        return 0

    # 位置参数：支持 "1"、"latest"、"2026-10-13 2"、"2026-10-13"、"关键词"
    if args.target:
        target = args.target

        if target[0].lower() == "latest":
            if items:
                show_essay(items[0], read_set)
                return 0
            log(f"目录为空：{SHORT_ESSAY_DIR}")
            return 1

        # 日期 + 篇号
        if len(target) >= 2 and re.match(r"^\d{4}-\d{2}-\d{2}$", target[0]) and target[1].isdigit():
            date, part = target[0], int(target[1])
            hit = next((it for it in items if it["date"] == date and it["part"] == part), None)
            if hit:
                show_essay(hit, read_set)
                return 0
            log(f"没找到 {date} 的第 {part} 篇。")
            return 1

        # 单独日期
        if re.match(r"^\d{4}-\d{2}-\d{2}$", target[0]):
            essays = [it for it in items if it["date"] == target[0]]
            if essays:
                show_essay(sorted(essays, key=lambda r: r["part"])[0], read_set)
                return 0
            log(f"没有 {target[0]} 的短文。")
            return 1

        # 纯数字 → 当天的第几篇（最新一天）
        if target[0].isdigit():
            groups = group_by_date(items)
            index = int(target[0])
            if 1 <= index <= len(items):
                show_essay(items[index - 1], read_set)
                return 0
            log(f"编号超出范围：1~{len(items)}")
            return 1

        # 关键词
        hits = search_items(items, target[0])
        if hits:
            show_essay(hits[0], read_set)
            return 0
        log(f"找不到匹配：{target[0]}")
        return 1

    days_limit = 0 if args.all else args.days
    return interactive(items, days_limit)


if __name__ == "__main__":
    try:
        sys.exit(main())
    except KeyboardInterrupt:
        print()
        sys.exit(130)
