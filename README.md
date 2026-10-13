# 单词 → AI 语境短文

> 把每天要背的单词，自动变成一篇考研风格的英语短文：目标词加粗、附中文翻译、按天分篇保存，
> 并在终端里按日期浏览阅读。

[![Python](https://img.shields.io/badge/Python-3.9%2B-blue.svg)](https://www.python.org/)
[![Playwright](https://img.shields.io/badge/Playwright-Chromium-2EAD33.svg)](https://playwright.dev/python/)
[![License](https://img.shields.io/badge/License-MIT-yellow.svg)](LICENSE)

背单词最大的问题是**孤立记忆**：单词表上的 `obligation`、`identical`、`judge` 彼此无关，
背完就忘。这个工具做一件事——**把你今天的单词塞进一篇有逻辑的文章里**，让你在语境中记住它们。

```
单词表  ──▶  扇贝网页版自动取词  ──▶  DeepSeek 生成短文  ──▶  按天分篇的 Markdown  ──▶  终端阅读
 (任意来源)      (可选，可替换)          (加粗+翻译)          (自动备份)          (按日期/搜索)
```

---

## 目录

- [功能特性](#功能特性)
- [效果预览](#效果预览)
- [快速开始](#快速开始)
- [配置说明](#配置说明)
- [使用方式](#使用方式)
- [工作原理](#工作原理)
- [常见问题](#常见问题)
- [已知限制](#已知限制)
- [合规声明](#合规声明)
- [文件说明](#文件说明)

---

## 功能特性

**取词**

- 从扇贝单词网页版自动取回今日词表（今日新词 / 今日复习 / 今日任务）
- **自动翻页**：识别分页控件，逐页读完（实测 8 页 150 词全部取回）
- **数量自检**：把采集结果与页面标注的「共 N 词」比对，不一致就报警，不会把错误数据发给 AI
- 登录态持久化：第一次扫码登录，之后免登录
- 随机停顿 + 模拟滚动，节奏接近真人操作，避免高频请求

**生成**

- 调用 DeepSeek 官方 API，生成考研阅读风格的短文
- 目标词**一个不漏**并加粗；附完整中文翻译，中文对应词也加粗
- 允许词形变化（`judge → judgment`），不为了塞词写生硬句子
- 同词族的词尽量放相邻段落，便于对比记忆
- 单篇过长或词数过多时，按配置**自动分篇**（默认每天 2 篇）
- 失败自动重试（超时、限流、网络异常），打印明确的错误原因

**保存与阅读**

- 按 `YYYY-MM-DD_单词语境练习_N.md` 命名，日期补零 → 字符串排序即时间排序
- **生成前自动备份**旧短文（保留最近 14 份），防止覆盖或误删
- 生成后自动用 VS Code 打开（可关闭）
- **终端阅读器**：按日期分组浏览、关键词搜索、未读筛选、进度跳转（`--jump N`）、时间范围过滤

**也可以完全不用扇贝**

- `wordlist_to_essay.py`：从任意文本文件读词表生成短文（手动粘贴、导出文件都行），不依赖任何网站
  （注意：该脚本用的是简化提示词，不包含中文翻译部分；需要翻译请用主脚本的 `--words` 模式）

---

## 效果预览

生成的 Markdown 长这样：

```markdown
# 2026-10-13 单词语境练习

**今日单词：** obligation, identical, judge, scene, journey, make, captive, provide

---

**The Pace of Change: Why Old Ideas Lag Behind**

In an age of **widespread** technological innovation, one **obvious** yet often
overlooked **observation** is that human **behaviour** **lags** far behind the
**pace** of invention. We **maintain** outdated habits, **embrace** **obsolete**
practices, and **barely** notice when our **judgement** is clouded by tradition.

---

**中文翻译：**

**广泛**的技术创新时代，一个**显而易见**却常被忽视的**观察**是：人类的**行为**
远远**滞后**于发明的**步伐**。我们**维持**过时的习惯，**拥抱**已**过时**的做法，
**几乎**察觉不到自己的**判断**被传统所蒙蔽。
```

终端阅读器的菜单：

```
┌──────────────────────────────────────┐
│ 短文阅读器                           │
│ 共 100 天 / 200 篇，未读 198 篇      │
│ 上次读到：2026-10-13_单词语境练习_2  │
└──────────────────────────────────────┘

     #    日期            篇数    未读    当天标题预览
     1    2026-10-13         2       0    1.The Pace of Change ｜ 2.The Shifting…
     2    2026-10-12         2       2    1.Truth in the Age of Media ｜ …

  编号=进入 · l=最新 · u=未读 · t=时间范围 · d=全部 · r=刷新 · q=退出
  直达某天：2026-10-01 2　搜索：直接输关键词
```

---

## 快速开始

### 1. 环境要求

- Python **3.9+**（开发环境为 3.12）
- 能访问 `api.deepseek.com` 与 `web.shanbay.com`
- 不需要安装 Chrome，Playwright 会自带 Chromium

### 2. 安装依赖

```bash
pip install -r requirements.txt

# 下载浏览器内核（只需一次，约 130MB）
python -m playwright install chromium
```

> **常见坑**：如果机器上有多个 Python，`pip install` 可能装到了另一个解释器上，
> 导致运行时报 `ModuleNotFoundError`。用 `python -m pip install -r requirements.txt`
> 可以确保装进当前解释器。

### 3. 配置密钥

```bash
# Windows
copy .env.example .env
# macOS / Linux
cp .env.example .env
```

编辑 `.env`，填入你的 DeepSeek API Key（[申请地址](https://platform.deepseek.com/)）：

```ini
DEEPSEEK_API_KEY=sk-你的密钥
```

> `.env` 已被 `.gitignore` 排除，**不会被提交**。也可以改用系统环境变量，优先级高于 `.env`。

### 4. 第一次运行（需要扫码登录）

```bash
python shanbay_daily_essay.py --show-browser
```

会弹出浏览器窗口。首次使用需要扫码登录扇贝，登录状态保存在 `shanbay_browser_data/`，
之后就不用再登录了。脚本会自动翻页取词、生成短文并打开 VS Code。

**Windows 用户**也可以直接双击 `启动-生成短文.bat`，按提示选择词表。

---

## 配置说明

所有配置有两种方式：**改代码顶部的配置区**，或**写进 `.env`**（推荐后者，不污染代码）。

| 配置项 | 默认值 | 说明 |
|---|---|---|
| `DEEPSEEK_API_KEY` | *（必填）* | DeepSeek API Key |
| `DEEPSEEK_MODEL` | `deepseek-chat` | 模型名 |
| `ESSAYS_PER_DAY` | `2` | 每天生成几篇，所有单词按篇数均分 |
| `ESSAY_WORDS_PER_TARGET` | `6` | 每个目标词配多少词的篇幅（越大文章越长） |
| `OUTPUT_DIR` | `短文` | 短文保存目录 |
| `AUTO_BACKUP` | `true` | 生成前是否备份旧短文 |
| `BACKUP_KEEP` | `14` | 备份保留份数 |
| `AUTO_OPEN_VSCODE` | `true` | 生成后是否自动打开 VS Code |
| `VSCODE_PATH` | *（自动探测）* | VS Code 可执行文件路径，装在自定义目录时指定 |

想改**提示词**（比如换个主题方向、要求更贴近某年真题风格），改
`shanbay_daily_essay.py` 里的 `PROMPT_TEMPLATE` 即可，是纯文本，改完立即生效。

---

## 使用方式

### 命令行

```bash
# 取今日复习词，生成短文（并自动打开 VS Code）
python shanbay_daily_essay.py

# 取今日新词
python shanbay_daily_essay.py --tab new

# 后台静默运行（适合定时任务）
python shanbay_daily_essay.py --headless

# 生成 3 篇而不是默认的 2 篇
python shanbay_daily_essay.py --essays 3

# 不自动打开 VS Code
python shanbay_daily_essay.py --no-open

# 跳过浏览器，直接用给定单词生成（试用/调试，不需要扇贝账号）
python shanbay_daily_essay.py --words "abandon,absolute,compensate,inevitable"

# 读指定文本文件里的词表（不依赖任何网站）
python wordlist_to_essay.py 我的生词.txt
```

### 终端阅读

```bash
# 交互菜单（按日期分组）
python read_essay.py

# 直接读某天的第 2 篇
python read_essay.py 2026-10-13 2

# 读最新一篇
python read_essay.py latest

# 跳到第 5 篇未读（接着上次继续学）
python read_essay.py --jump 5

# 只看某段日期
python read_essay.py --range 2026-09-01 2026-09-30

# 按目标词搜索：找出所有包含 therapy 的短文
python read_essay.py --find therapy

# 纯文本清单
python read_essay.py --list
```

菜单内的快捷键：

| 输入 | 作用 |
|---|---|
| 编号 | 进入该天 / 阅读该篇 |
| `n` / `p` | 下一篇 / 上一篇 |
| `u` | 只看未读 |
| `l` | 直接进最新一天 |
| `t` | 按日期区间过滤 |
| `d` | 展开全部日期 |
| `o 2` | 用 VS Code 打开第 2 篇 |
| `关键词` | 搜索标题或目标词 |
| `r` / `q` | 刷新 / 退出 |

### 每天自动跑（Windows 任务计划程序）

1. 任务计划程序 → 创建基本任务
2. 触发器：每天 8:00
3. 操作：程序填 `python`，参数填 `D:\path\to\shanbay_daily_essay.py --headless`，
   起始位置填脚本所在目录

---

## 工作原理

```
┌─────────────────────┐
│ 1. 取词（Playwright）│  打开词表页 → 等待渲染 → 定位单词元素
│                     │  → 逐页点击「下一页」→ 读到没有新词为止
└──────────┬──────────┘
           │  单词列表
           ▼
┌─────────────────────┐
│ 2. 自检             │  与页面标注的「共 N 词」比对
│                     │  检查是否混入音标、导航文字、重复项
└──────────┬──────────┘
           │  通过
           ▼
┌─────────────────────┐
│ 3. 备份旧短文       │  复制到 短文_备份/时间戳/，保留最近 14 份
└──────────┬──────────┘
           │
           ▼
┌─────────────────────┐
│ 4. 分篇             │  按 ESSAYS_PER_DAY 均分（单词太少不硬拆）
└──────────┬──────────┘
           │  每篇一组单词
           ▼
┌─────────────────────┐
│ 5. 调用 DeepSeek    │  提示词要求：全部词覆盖 + 加粗 + 中文翻译
│                     │  失败退避重试；max_tokens 按目标词数自动估算
└──────────┬──────────┘
           │  Markdown 正文
           ▼
┌─────────────────────┐
│ 6. 保存 + 打开      │  {日期}_单词语境练习_{N}.md → VS Code 预览
└─────────────────────┘
```

**几个设计取舍**：

- **为什么按天分篇而不是一篇塞完？** 60 个目标词塞进 180 词的短文，平均每 3 个词就出现一个目标词，
  模型必然漏词。分篇是"覆盖完整"与"行文自然"的折中。
- **为什么保留词形变化？** 要求 `judge` 只能以原形出现会写出很别扭的句子。允许变形成 `judgment`
  更符合真实语言使用，也不影响记忆效果。
- **为什么不用编号做导航？** 编号会随新文章加入而变化（今天的第 50 篇明天变成第 52 篇）。
  所以阅读器用**日期**（稳定）+ **未读进度**（`--jump`）+ **关键词搜索** 三个锚点定位。

---

## 常见问题

**Q：报错 `ModuleNotFoundError: No module named 'playwright'`，但我明明装了？**

机器上有多个 Python，`pip` 装到了另一个解释器。用 `python -m pip list` 确认，
或者统一用 `python -m pip install ...` 安装。Windows 上常见于同时装了 MSYS2/Conda 的情况。

**Q：取词时报「45 秒内没等到单词元素」？**

可能是：① 今天该词表没有任务；② 登录态失效（用 `--show-browser` 重新登录）；
③ **网页改版导致选择器失效**（见[已知限制](#已知限制)）。可先用 `shanbay_probe.py`
导出页面结构，据此更新选择器。

**Q：生成失败，报 HTTP 401 / 402？**

401 = 密钥无效或已吊销；402 = DeepSeek 账户余额不足（一次生成约一分钱）。

**Q：中文出现乱码？**

Windows 控制台默认 GBK 代码页。脚本内部已统一切 UTF-8；若在外部终端运行，
先执行 `chcp 65001`。

**Q：不想用扇贝，能只用 AI 生成部分吗？**

可以。用 `wordlist_to_essay.py`（读文本文件）或 `--words "a,b,c"`（命令行直接给词），
完全不触碰任何网站。

**Q：短文会被覆盖吗？**

同名文件会被覆盖，但**生成前会自动备份**到 `短文_备份/时间戳/`，保留最近 14 份。

---

## 已知限制

**说实话，这个项目有明显的脆弱点：**

1. **网页抓取依赖对方页面结构。** 取词模块通过 CSS 类名（如 `div[class*='index_wordName__']`）定位元素，
   扇贝一旦改版就可能失效。这类项目最大的死因就是这个。
   - 缓解措施：选择器用模糊匹配（`class*=`）而非全名，避免构建哈希后缀变化导致失效；
     提供 `shanbay_probe.py` 可在失效时导出新结构，快速修复。
   - **替代方案**：如果不想依赖网页，用 `wordlist_to_essay.py` 手动喂词表，永不失效。

2. **只在 Windows + 中文环境下实测过。** 代码里的 VS Code 探测、终端编码处理已做跨平台兼容，
   但 macOS/Linux 未经过真实测试。

3. **只验证过一个扇贝账号。** 不同账号的词表规模、页面加载行为可能有差异。

4. **抓取商业服务的数据存在合规灰色地带。** 详见下方声明，请自行判断风险。

5. **AI 生成的质量不稳定。** 温度 0.8 意味着每次结果不同，偶尔可能漏词或句子生硬。
   脚本会打印目标词数量，但**不自动校验生成结果是否覆盖全部单词**（可以用
   `read_essay.py` 查看，或自行比对）。

欢迎提 Issue 反馈失效情况或提交适配其他单词平台的 fetcher。

---

## 合规声明

- 本项目**仅供个人学习使用**。请勿用于批量抓取、商业用途或任何形式的再分发。
- 取词模块通过**真实浏览器访问公开网页**实现，不抓包、不逆向、不调用非公开接口、
  不绕过任何验证机制。
- 请**每天运行一次**即可，不要高频请求。脚本内置了随机停顿与页数上限，请勿移除这些限制。
- 使用本工具产生的任何后果由使用者自行承担。请遵守目标网站的服务条款。

---

## 文件说明

| 文件 | 作用 |
|---|---|
| `shanbay_daily_essay.py` | **主脚本**：取词 → 生成 → 保存 → 打开 |
| `read_essay.py` | 终端阅读器：按日期浏览、搜索、进度管理 |
| `wordlist_to_essay.py` | 从任意文本词表生成短文（不依赖网站） |
| `启动-生成短文.bat` | Windows 双击启动生成（可选词表） |
| `read_essay.bat` | Windows 双击启动阅读器 |
| `shanbay_probe.py` | 网页改版时用它导出页面结构，便于修复选择器 |
| `shanbay_pager_check.py` | 检测词表翻页机制（分页 / 滚动加载） |
| `shanbay_collect_words.py` | 只取词、不生成短文，输出词表清单 |
| `shanbay_verify_collect.py` | 对照验证取词准确性（两遍采集 + 逐页截图） |
| `.env.example` | 配置模板，复制为 `.env` 使用 |
| `requirements.txt` | 依赖清单 |

**运行后自动产生的目录**（均已被 `.gitignore` 排除）：

| 目录 / 文件 | 内容 |
|---|---|
| `短文/` | 生成的短文（`YYYY-MM-DD_单词语境练习_N.md`） |
| `短文_备份/` | 生成前的自动备份（保留最近 14 份） |
| `shanbay_browser_data/` | 浏览器登录态（含账号信息，**请勿提交**） |
| `.read_state.json` | 已读标记与阅读进度 |
| `.essay_index.json` | 短文索引缓存 |
| `probe_out/` | 诊断输出（页面结构、截图） |

---

## License

[MIT](LICENSE)
