# -*- coding: utf-8 -*-
"""
公共工具：.env 读取 + VS Code 定位

被 shanbay_daily_essay.py / read_essay.py / wordlist_to_essay.py 共用，
避免每个脚本各写一份（也避免把某个人的安装路径写死在代码里）。
"""

import os
import shutil
from pathlib import Path

APP_DIR = Path(__file__).resolve().parent


# -----------------------------------------------------------------------------
# .env 读取
# -----------------------------------------------------------------------------
def load_dotenv(path: Path = None) -> None:
    """
    极简 .env 解析：把 KEY=VALUE 读进环境变量（已存在的环境变量不覆盖）。

    不依赖 python-dotenv，少一个安装步骤：
      · 支持 # 注释、空行、值两端的引号
      · 系统环境变量优先，不会被 .env 覆盖
    """
    env_path = path or (APP_DIR / ".env")
    if not env_path.exists():
        return
    try:
        for raw in env_path.read_text(encoding="utf-8-sig").splitlines():
            line = raw.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            key, _, value = line.partition("=")
            key = key.strip()
            value = value.strip().strip('"').strip("'")
            if key and key not in os.environ:
                os.environ[key] = value
    except Exception:
        pass


def env_int(name: str, default: int, warn=None) -> int:
    """读整型配置：值非法时回退默认值，不让脚本因配置写错而崩溃。"""
    raw = (os.getenv(name) or "").strip()
    if not raw:
        return default
    try:
        return int(raw)
    except ValueError:
        if warn:
            warn(f"环境变量 {name}={raw!r} 不是整数，已改用默认值 {default}")
        return default


def env_bool(name: str, default: bool = True, warn=None) -> bool:
    """读布尔配置：1/true/yes/on 为真，0/false/no/off 为假。"""
    raw = (os.getenv(name) or "").strip().lower()
    if not raw:
        return default
    if raw in ("1", "true", "yes", "on"):
        return True
    if raw in ("0", "false", "no", "off"):
        return False
    if warn:
        warn(f"环境变量 {name}={raw!r} 不是布尔值，已改用默认值 {default}")
    return default


def env_str(name: str, default: str = "") -> str:
    """读字符串配置。"""
    raw = (os.getenv(name) or "").strip()
    return raw or default


# -----------------------------------------------------------------------------
# VS Code 定位
# -----------------------------------------------------------------------------
def _vscode_candidates() -> list:
    """跨平台的 VS Code 常见安装位置。"""
    home = Path.home()
    return [
        # Windows
        str(home / "AppData/Local/Programs/Microsoft VS Code/bin/code.cmd"),
        r"C:\Program Files\Microsoft VS Code\bin\code.cmd",
        r"C:\Program Files (x86)\Microsoft VS Code\bin\code.cmd",
        str(home / "vscode/Microsoft VS Code/bin/code.cmd"),
        # macOS
        "/Applications/Visual Studio Code.app/Contents/Resources/app/bin/code",
        str(home / "Applications/Visual Studio Code.app/Contents/Resources/app/bin/code"),
        # Linux
        "/usr/bin/code",
        "/usr/local/bin/code",
        "/snap/bin/code",
        str(home / ".local/bin/code"),
    ]


def find_vscode() -> str:
    """
    找 VS Code 的命令行程序，返回可执行文件路径；找不到返回空字符串。

    查找顺序：
      1) 环境变量 VSCODE_PATH（装在自定义目录时用它指定，最可靠）
      2) PATH 里的 code 命令
      3) 各平台常见安装位置
    """
    env_path = env_str("VSCODE_PATH")
    if env_path and Path(env_path).exists():
        return env_path

    for name in ("code.cmd", "code"):
        found = shutil.which(name)
        if found:
            return found

    for candidate in _vscode_candidates():
        try:
            if candidate and Path(candidate).exists():
                return candidate
        except Exception:
            continue
    return ""


def open_files_in_vscode(files, reuse_window: bool = True, preview: bool = False) -> bool:
    """
    用 VS Code 打开若干文件。

    files        —— 路径字符串列表
    reuse_window —— True 时复用当前窗口（-r），不会开一堆新窗口
    preview      —— True 时额外请求 Markdown 预览（markdown.showPreview）

    返回是否成功发起打开动作。
    """
    import subprocess
    import time

    files = [str(f) for f in (files or [])]
    if not files:
        return False

    code = find_vscode()
    if not code:
        return False

    args = [code]
    if reuse_window:
        args.append("-r")
    try:
        subprocess.Popen(
            args + files,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            shell=False,
        )
    except Exception:
        return False

    if preview:
        time.sleep(6)   # 等 VS Code 把文件加载进来
        for path in files:
            try:
                subprocess.Popen(
                    [code, "-r", "--command", "markdown.showPreview", path]
                    if reuse_window else
                    [code, "--command", "markdown.showPreview", path],
                    stdout=subprocess.DEVNULL,
                    stderr=subprocess.DEVNULL,
                    shell=False,
                )
                time.sleep(0.6)
            except Exception:
                continue
    return True
