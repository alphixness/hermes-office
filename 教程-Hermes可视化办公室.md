# 零基础给 Hermes 搭一个「可视化办公室」：让你的 AI 员工坐在工位上干活

> 本文是**手把手教程**：从零装好 Hermes → 招几个 AI 员工（多 Agent）→ 给它们派活 → 最后跑起一个「办公室」页面，能看见每个员工坐在自己的工位上、谁在干活、干了什么、花了多少 Token。
>
> 全文命令都在 Windows / macOS / Linux 上实测过，代码只用 **Python 标准库**（不需要 pip install 任何东西）。

---

## 一、先说清楚：这东西的原理是什么

视频里那种"AI 员工坐在工位上"的画面，**不是什么黑科技，也不是 Hermes 的内置功能**，而是把 Hermes 电脑上本来就有的三份数据，做成了一层可视化界面：

| 你看到的画面 | 真实数据来源 | 说明 |
|---|---|---|
| 一个个工位 + 像素小人 | `~/.hermes/kanban.db` 的 `tasks.assignee` | 每个被派过活的 Agent 就是一个工位 |
| 小人敲键盘 / 趴桌上 | `tasks.status` | running=干活中，blocked=卡住了，done=收工 |
| 「正在执行 N 个项目」 | 该员工名下 `running` 任务数 | 一行 SQL 的事 |
| 右侧「Token 消耗 / 成本」 | **每个员工各自的 `state.db`** | 见下方「最容易踩的坑」第 2 条 |
| 「最近工作记录」列表 | `state.db` 的会话标题 | 每次干活都是一条会话记录 |
| 「正在干什么」那行小字 | `sessions.last_activity_description` | Hermes 现成字段，比如 `tool running: browser_exec` |

所以整套东西只有两个文件：

```
hermes-office/
├── office_server.py   # 只读读取上面那些数据 → 输出一个 JSON 接口
└── index.html         # 一个网页，每 3 秒拉一次 JSON，把工位画出来
```

---

## 二、准备工作（5 分钟）

### 1. 装 Hermes

**Windows**（PowerShell）：
```powershell
iex (irm https://hermes-agent.nousresearch.com/install.ps1)
```

**macOS / Linux / WSL2**：
```bash
curl -fsSL https://hermes-agent.nousresearch.com/install.sh | bash
```

也可以直接去 [hermes-agent.nousresearch.com](https://hermes-agent.nousresearch.com/) 下载桌面版安装包（推荐新手，一键装好命令行 + 桌面端）。

> 安装器会自动装好 Python 3.11、Node、ripgrep、ffmpeg 等依赖，**你只需要保证电脑上有 git**。

装完开一个**新终端**，敲：
```bash
hermes --version     # 能打印版本号就是装好了
```

### 2. 配上模型

```bash
hermes setup          # 交互式向导，第一次用建议跑这个
# 或只想改模型：
hermes model
```

> 想省事：`hermes setup --portal` 一条命令搞定登录 + 模型 + 工具网关。

---

## 三、第一步：招几个「AI 员工」

Hermes 里"多个员工"的单位叫 **profile（档案）**——每个 profile 是一个完全独立的 Agent：自己的配置、记忆、会话、技能。

```bash
# 给员工起名，并写明它擅长什么（派活路由会参考描述）
hermes profile create architect --description "设计架构方案、拆解任务"
hermes profile create coder     --description "写代码、修 bug"
hermes profile create tester    --description "写测试、跑回归"
hermes profile create reviewer  --description "代码评审、质量门禁"
```

创建完，**每个员工立刻拥有自己的命令**：
```bash
architect chat      # 直接跟架构师对话
coder chat          # 跟程序员对话
```

看花名册：
```bash
hermes profile list
```
> ⚠️ 重要：**一个 profile 只能有一个 Agent 在用**。不要开两个进程指向同一个 profile，记忆会互相污染 —— 想共享记忆请用外部记忆服务，而不是共用 profile。
>
> 💡 想少配几次密钥：`hermes profile create coder --clone` 会把当前配置和 API key 复制过去。

---

## 四、第二步：给员工派活（看板）

Hermes 的多 Agent 协作靠内置的**看板（Kanban）**——一个本地 SQLite 任务板，所有 profile 共用。

```bash
hermes kanban init                                      # 初始化看板

# 派活：写标题 + 派给谁 + 补充说明
hermes kanban create "给用户中心写登录接口" --assignee coder \
  --body "FastAPI + JWT，先看 docs/api.md 的约定"

hermes kanban create "给登录接口补单元测试" --assignee tester
```

查看：
```bash
hermes kanban list                  # 全部任务
hermes kanban list --status running # 只看正在跑的
hermes kanban stats                 # 按状态 + 按员工计数
hermes kanban show <task_id>        # 单个任务的评论与事件流（= 员工之间的"交流"）
```

### 🔑 关键一步：让调度器真正开工

很多人卡在这里：**派了活，员工却不动**。原因是——任务调度器（Dispatcher）跑在 **gateway** 里：

```bash
hermes gateway start     # 启动后台服务；调度器会拉起被指派的 profile 去干活
hermes gateway status    # 确认在跑（要看到 gateway 进程）
```

> **Windows 用户特别注意**（我实测踩过）：如果 `hermes gateway start` 是在**别的程序/脚本的 shell 里**执行的，进程可能随着那个 shell 一起被系统回收（Windows Job Object 机制），表现为"提示成功，但 `status` 说没有进程"：
> ```
> ⚠ reported success, but the process died without a clean shutdown record...
>   the shell that ran `hermes gateway start` was inside a Windows Job Object that killed the gateway on exit
> ✗ No gateway process detected
> ```
> **正确做法**：用 `hermes gateway install` 装成开机自启的后台服务（Windows 会装一个登录启动项），或者**在自己开的终端窗口里**手动 `hermes gateway start` 且别关那个窗口。装完用 `hermes gateway status` 确认。

> 调度器会自动认领 `ready` 的任务、拉起对应 profile 的进程、崩了重试、卡了回收。你不需要手工 `hermes chat`。
>
> 想让看板一直有活干，再挂个定时任务：`hermes cron create "every 2h"`（在交互式会话里用 `/cron` 更直观）。

---

## 五、第三步：搭办公室

### 1. 建目录，放两个文件

```bash
mkdir hermes-office && cd hermes-office
```

把这两个文件放进去（完整代码见文末「附录」或我的仓库链接）：

```
office_server.py    # 后端：只读读数据，出 JSON
index.html          # 前端：工位视图
```

### 2. 跑起来

```bash
python office_server.py
```

你会看到：

```
Hermes 数据目录 : C:\Users\你的用户名\AppData\Local\hermes
  看板 kanban.db : ✅
  员工 profiles  : 4 个 → architect, coder, reviewer, tester

🏢 办公室已开门 → http://127.0.0.1:8123
```

浏览器打开 **http://127.0.0.1:8123** —— 工位就出来了。

常用参数：
```bash
python office_server.py --port 9000        # 换端口（默认 8123）
python office_server.py --days 0           # 只看今天的消耗（默认是最近 8 天）
python office_server.py --hermes-home D:/我的/hermes   # 数据目录不在默认位置时
```

> 💡 为什么默认看 8 天而不是今天：新手第一天跑起来时，"今天"往往是 0（当天的会话可能还没落账），
> 满屏 0 会让人以为坏了。窗口放宽一点，数字立刻就是活的。

### 3. 想看到"有人在干活"的画面？

办公室的画面完全取决于**看板里有没有正在跑的任务**。想要一张好看的截图：

```bash
hermes kanban create "调研 3 个竞品的定价页并写成对比表" --assignee coder
```
然后盯着页面看——那位员工的工位会变绿、小人开始"敲键盘"，右侧活动栏出现 `tool running: ...`。

---

## 六、第四步：看懂这个办公室（含自定义）

### 6.1 角色设定：你是老板，经理是你的主 Agent

```
你（老板，人类 —— 不占 Hermes profile、不烧 Token）
   │  在聊天室打：@林诀 实现每日签到双倍积分
   ▼
经理（跑在 Hermes 主 profile 上的那个 Agent，默认叫「苏晚」）
   │  hermes kanban create ... --assignee coder
   ▼
员工（coder / tester / reviewer / designer / devops / doc ...）
```

- 👑 **老板办公室** = 你本人，鼠标点一下就能派活
- 📋 **经理办公室** = 你的主 Agent 的工位。它那份 Token 就是"你自己"烧掉的量（实测 354 万）
- **不写 @ → 默认派给经理**，由经理拆解后再分派给员工
- **写了 `@某人` → 直接派给那个人**（`@林诀`、`@coder` 都认；输入 `@` 会弹出员工下拉，带头像和岗位）

### 6.2 三种派活方式（效果完全一样）

| 方式 | 操作 |
|---|---|
| **聊天室 @** | 右下角输入框打 `@` → 选人 → 写要求 → 回车 |
| **点办公室** | 点老板/经理办公室 → 弹窗填标题 → 🚀 派活 |
| **点工位** | 点任意员工工位 → 看它名下任务/工作记录 → 🚀 派活给它 |

三种都走官方 CLI `hermes kanban create`（**绝不直接写数据库**），所以看板、日志、调度与手敲命令完全一致。
派完任务进入 `ready` 状态 —— **要真被干还需要调度器在跑**（见第七章第 5 条）。

### 6.3 右侧聊天室：员工之间在交流什么

- **员工发言**（评审结论、交接说明、完成汇报）来自 `kanban.db` 的 `task_comments` + `task_events` + `task_runs`
- **老板发言**来自办公室自己写的 `chat.json`
- 每条老板留言下面标着 `你 → 林诀 · t_ba3fea78`，任务号能在对应工位弹窗里查到

### 6.4 外观与自定义

- **工位颜色**：灰=空闲、绿=在岗（头像呼吸灯）、黄=排队、红=卡住（头像歪 6°）、灰虚线=空岗「招人中」
- **点任意工位**：弹窗显示「正在干」+ 任务记录 + 最近工作记录（来自各自的 `state.db` 与 `kanban.db`）
- **📊 统计排行 tab**：各员工 Token / 成本 / 完成数，按用量排序
- **✏️ 改标语**：顶部公司名和 slogan 可以在界面里直接改，存回 `agents.json` 的 `OFFICE` 段

想改成自己的样子：

| 想改什么 | 改哪里 |
|---|---|
| 员工名字 / 岗位 / 头像提示词 | `agents.json`（改完刷新即生效，不用动代码） |
| 顶部公司名 / slogan | 界面点「✏️ 改标语」，或直接改 `agents.json` 的 `OFFICE` |
| 配色 | `index.html` 的 `:root` CSS 变量（`--working / --blocked / --accent ...`） |
| 刷新频率 | `index.html` 结尾的 `setInterval(load, 5000)` |
| 工位大小 | `index.html` 里 `.floor-grid` 的 `minmax(...)` |
| 聊天室默认派给谁 | `agents.json` 里 `seat: "manager"` 那条的 `bind_profile` |

---

## 七、⚠️ 最容易踩的 11 个坑（我全踩过）

**1) Token 全是 0**
`sessions.started_at` 存的是 **Unix 时间戳**（如 `1789460816.71`），不是 `2026-09-16` 这种字符串。
拿日期字符串去比较会**一行都匹配不到**。必须转换成数值再比（`datetime(...).timestamp()`）。

**2) 只有一个员工的 Token，其他都是 0**
**每个 profile 是独立的 Hermes home**：
```
~/.hermes/state.db                    ← 只有 default 这个 Agent 的账
~/.hermes/profiles/coder/state.db     ← coder 自己的账（可能几十上百 MB）
```
想按工位分账，必须**逐个 profile 读各自的 state.db**。这也是"按员工统计"唯一正确的做法。

**3) Windows 找不到数据库**
Windows 上 Hermes 的数据目录是 `%LOCALAPPDATA%\hermes`，**不是** `~/.hermes`。
最稳的写法是直接问它自己：`hermes config path` 的上一级目录（教程里的 `office_server.py` 就是这么干的）。

**4) 数据库被锁 / 影响正常使用**
Hermes 进程随时在写数据库。**必须只读打开**：
```python
sqlite3.connect(f'file:{db}?mode=ro', uri=True)   # ✅ 只读，不写不锁
```

**5) 派了活没人干**
调度器在 gateway 里 → `hermes gateway start`。另外任务要处于 `ready` 状态才会被认领。

**6) 页面打开了，但工位是空的**
说明你还没有 profile（或者还没派过任何任务）。先建 profile + 建任务，画面自然就有了。

**7) Windows：`hermes gateway start` 说成功，但进程马上没了**
别在别的程序/脚本的 shell 里启它（Windows Job Object 会连带回收）。用 `hermes gateway install` 装成持久服务，或者在自己开的终端里启并保持窗口开着。用 `hermes gateway status` 复核。

**8) 页面里中文变问号/方块**
两个文件都要以 **UTF-8** 保存（尤其 Windows 记事本，另存时选 UTF-8）。

---

### 下面这 3 个是"做独立应用窗口"时才踩到的，特别阴

**9) `pythonw` 启动：进程活着、端口在听、就是没有窗口**
无控制台运行时 `sys.stdout` / `sys.stderr` 是 **`None`**，脚本里任何一个 `print()` 都会抛
`AttributeError`，把**后面创建窗口的代码整段打断** —— 但它是后台线程起服务在前，所以你只会看到
"服务正常、窗口没有"。解法：启动时先把输出重定向到日志文件：

```python
if sys.stdout is None or sys.stderr is None:
    sys.stdout = sys.stderr = open(HERE / 'office.log', 'a', encoding='utf-8', buffering=1)
```

**10) `.vbs` 双击没反应（什么都不发生）**
WSH 默认按 **ANSI** 读脚本 → **含中文的 UTF-8 vbs 会乱码且不报错**，只返回退出码 1。
解法：`.vbs` 用**纯 ASCII 文件名 + 纯 ASCII 内容**（中文名字留给桌面快捷方式 `.lnk`，它支持 Unicode）。

**11) `.vbs` 里 `Run(cmd, 0, False)` 会把 GUI 窗口一起藏起来**
那个 `0` 是"隐藏窗口"。而 `pythonw.exe` 本身就是创建 GUI 的进程，于是它创建的窗口也被标记为隐藏：
**进程在跑、端口在听、任务管理器能看到，就是屏幕上没有**。必须用 `1`：

```vbs
sh.Run cmd, 1, False   ' ⚠️ 用 0 会把 pythonw 创建的窗口一起隐藏
```

**附）150% 缩放下"右侧面板被挤出屏幕 / 什么都要滚动"**
窗口明明是 1721×1033，WebView 里却只拿到约 960 CSS 宽度再被放大 1.5 倍。两件事都要做：
① 进程**声明 DPI 感知**（`ctypes.windll.shcore.SetProcessDpiAwareness(2)`，必须在建窗口之前）；
② CSS 用 `@media (max-height: 820px / 700px)` 分档压缩工位尺寸。**别只做一半。**

**附）怎么"诚实地"验证自己的界面**
- pywebview 的窗口**不属于** pythonw 进程的 MainWindow → `Get-Process` 里 `MainWindowHandle` 是 **0**，
  拿它判断"窗口在不在"会得到假阴性。
- `CopyFromScreen` / `ImageGrab` 只录**屏幕上可见的像素** → 窗口被别的窗口压住时，你会截到**别的窗口**，
  然后开始怀疑自己的 CSS。用 `SetWindowPos(TOPMOST)` 先置顶，或者干脆在页面里读 DOM 尺寸：
  仓库 `dev/measure_layout.py` 就是干这个的（直接读 `getBoundingClientRect()` 和 `innerWidth`）。

---

## 八、进阶玩法

### 8.1 升级成「独立应用」（不在浏览器里）

不满足于浏览器标签页，可以让它变成一个**真正独立的应用窗口**：无地址栏、无标签页、无菜单，窗口标题就是「Hermes 办公室」，关窗即退出。

做法（Windows 实测）：用 `pywebview` 把同一个页面装进原生窗口，Windows 下它走系统自带的 Edge WebView2 内核。

```bash
cd hermes-office
uv venv .venv
uv pip install --python .venv\Scripts\python.exe pywebview pythonnet
```

再放一个启动脚本（`launch-office.vbs`，双击即可，无控制台窗口）：

```vbscript
' launch-office.vbs —— 双击启动独立窗口
Option Explicit
Dim fso, sh, here, pyw, script, cmd
Set fso = CreateObject("Scripting.FileSystemObject")
Set sh  = CreateObject("WScript.Shell")
here   = fso.GetParentFolderName(WScript.ScriptFullName)
pyw    = fso.BuildPath(here, ".venv\Scripts\pythonw.exe")
script = fso.BuildPath(here, "hermes_office_app.py")
sh.CurrentDirectory = here
cmd = """" & pyw & """ """ & script & """"
sh.Run cmd, 0, False
```

> ⚠️ **VBS 文件必须是纯 ASCII、文件名也用英文**。WSH 默认按系统 ANSI 码页读取 `.vbs`，
> 一个含中文的 UTF-8 `.vbs`（文件名或内容）会被读成乱码、脚本静默失败（返回码 1 但什么都不发生）。
> 想要中文名字，把**桌面快捷方式**命名为中文即可（`.lnk` 支持 Unicode，指向 ASCII 的 vbs）。

最后给桌面放一个快捷方式：

```powershell
$ws = New-Object -ComObject WScript.Shell
$lnk = $ws.CreateShortcut("$env:USERPROFILE\Desktop\Hermes办公室.lnk")
$lnk.TargetPath = 'C:\...\hermes-office\launch-office.vbs'
$lnk.WorkingDirectory = 'C:\...\hermes-office'
$lnk.IconLocation = 'C:\...\hermes-office\office.ico'
$lnk.Save()
```

### 8.2 给员工取名、换岗位、做头像（`agents.json`）

办公室里的名字不用和 profile 同名——编辑 `agents.json` 就行：

```json
{
  "STYLE": "beautiful cartoon illustration portrait, semi-realistic anime style, ...",
  "agents": [
    { "id": "manager",   "name": "苏晚",   "role": "经理",
      "prompt": "elegant young woman as an office manager, navy blazer ...",
      "bind_profile": "manager" },
    { "id": "coder",     "name": "林诀",   "role": "开发",
      "prompt": "cheerful young male programmer, gray hoodie ...",
      "bind_profile": "coder" }
  ]
}
```

- `id` 是内部标识，`bind_profile` 指定它对应哪个 Hermes profile（不填就同名匹配）
- `name` / `role` 就是工位上显示的名字和岗位 —— **随你改**
- `prompt` 是这张头像的画风提示词；`STYLE` 是所有头像**共用**的风格串（保证整体统一）
- 想加人就加一条；`bind_profile` 指向一个还不存在的 profile，工位会显示**「招人中」**

然后用图像模型批量出头像（本文用 Agnes 图像 API，任何 OpenAI 兼容的图像接口都能替换）：

```bash
python make_avatars.py               # 只补缺的
python make_avatars.py --only coder  # 先出一张看风格，满意再铺开
python make_avatars.py --force       # 全部重出
```

头像会落到 `avatars/<id>.png`。**建议再缩一份 256px 的**给页面用（原图 1MB×10 会让页面很重）：

```python
from PIL import Image
Image.open("avatars/coder.png").convert("RGB").resize((256,256), Image.LANCZOS)\
     .save("avatars_256/coder.jpg", quality=88, optimize=True)
```

实测：10 张原图 11.0MB → 缩后 **0.15MB**（页面秒开）。

### 8.3 其他

| 玩法 | 怎么做 |
|---|---|
| **实时**别 3 秒轮询，改事件流 | 用 `hermes kanban watch`（全板事件流）与 `hermes kanban tail <id>`，代理成 SSE |
| **夜班工位** | `hermes cron` 挂定时任务，办公室多一排"夜里值守"的员工 |
| **点工位看对话全文** | 读该 profile `state.db` 的 `messages` 表（终端里也可以 `hermes sessions browse`）|
| **多机协作** | 看板是**单机**的（`kanban.db` 本地文件、调度器同机拉进程）。多机请各自一块板 |
| **不写代码看数据** | `hermes insights --days 7`、`hermes kanban stats --json`（可直接喂给任何前端）|

---

## 九、写在最后

- 这套「办公室」是**一个展示层**：它读的都是 Hermes 已经在写的本地数据，**不改 Hermes、不写数据库**（全程只读），所以可以放心跑。
- 但它好看归好看，**数据本身 Hermes 早就有了**：`hermes kanban stats`、`hermes insights`、会话里的 `/agents` 都能看到。可视化解决的是"**一眼看懂我的 AI 员工在忙什么、烧了多少钱**"这个体感问题。
- 顺便提一句这套东西的"隐藏价值"：**它逼你把多 Agent 用对**——每个员工一个 profile、活走看板、调度器在后头跑。用对之后，你就不需要盯着终端看日志了。

> 两个文件我放在文末（或仓库链接）。跑起来有报错，把 `python office_server.py` 的输出贴到评论区，我看到了会回。

---

### 附录：两个文件的完整代码

**① `office_server.py`（后端，纯标准库，只读）**
见附件 `office_server.py`

**② `index.html`（前端，像素工位视图）**
见附件 `index.html`

> 本教程使用 Hermes Agent v0.21.x 实测；命令与数据表结构若版本升级后有变化，以 `hermes --help` 与官方文档为准：https://hermes-agent.nousresearch.com/docs
