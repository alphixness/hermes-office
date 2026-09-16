# 我给 Hermes 搭了一间「可视化办公室」：AI 员工坐在工位上，我 @ 一下它就派活

> 你有没有想过，你那一堆 AI Agent 到底在干嘛？
> 我把它们放进了一间看得见的办公室：有老板办公室、经理办公室、开放工位区，还有一间聊天室。
> 我在聊天框里打个 `@`，活就派到了对应员工的工位上。

**仓库（MIT 开源，零依赖可跑）**：https://github.com/alphixness/hermes-office

![Hermes 办公室总览](https://raw.githubusercontent.com/alphixness/hermes-office/main/screenshot.png)

---

## 一、先说清楚：这不是黑科技，是一层「展示层」

我用的是 [Hermes Agent](https://hermes-agent.nousresearch.com/docs)，它本身就带一套多 Agent 协作的能力：
每个 Agent 是一个独立 profile，任务走本地看板（kanban），调度器在 gateway 里认领任务并执行。

**这些数据本来就躺在你硬盘上**，只是没人把它画出来：

| 画面上的东西 | 真实数据来源 |
|---|---|
| 谁在工位上、在干什么 | `kanban.db` → `tasks(assignee, status)` |
| 工位气泡里那句「正在执行」 | `sessions.last_activity_description`（Hermes 现成字段） |
| 每个员工烧了多少 Token、多少钱 | **各 profile 自己的** `state.db` → `sessions(input_tokens, output_tokens, estimated_cost_usd)` |
| 聊天室里员工说的话 | `kanban.db` → `task_comments` + `task_events` + `task_runs` |
| 有哪些员工 | `~/.hermes/profiles/*` |

所以我做的事只有一件：**开一个只读进程读这些库，再渲染成一间办公室**。
全程 `sqlite3.connect('file:...?mode=ro', uri=True)`，**不写、不锁、不影响正在跑的 Hermes**。

---

## 二、角色设定：你是老板，AI 是经理

这是我做这个项目时最有意思的一个决定 —— 把组织结构画清楚：

```
你（老板，人类）—— 不占 profile、不烧 Token
   │  在聊天室打：@林诀 实现每日签到双倍积分
   ▼
经理（跑在 Hermes 主 profile 上的那个 Agent）
   │  它去调 hermes kanban create ... --assignee coder
   ▼
员工（coder / tester / reviewer / designer / devops / doc …）
```

- **不写 @** → 默认派给**经理**，由它拆解后再分派
- **写了 `@某人`** → 直接派给那个人（`@林诀`、`@coder` 都认，输入 `@` 会弹出带头像和岗位的下拉）

三种派活方式，效果完全一样（都走官方 CLI，**绝不直接写数据库**）：

| 方式 | 操作 |
|---|---|
| 聊天室 @ | 右下角输入框打 `@` → 选人 → 写要求 → 回车 |
| 点办公室 | 点老板/经理办公室 → 弹窗填标题 → 🚀 派活 |
| 点工位 | 点任意员工工位 → 看它名下任务与工作记录 → 🚀 派活给它 |

![聊天室：员工交流 + 老板的 @ 派活](https://raw.githubusercontent.com/alphixness/hermes-office/main/docs/chat-room.png)

聊天室里，**员工之间的真实交流**（评审结论、交接说明、完成汇报）就是这样一条条冒出来的；
每条老板留言下面会标 `你 → 林诀 · t_ba3fea78`，任务号点开工位就能查。

---

## 三、三步搭起来

### 1. 建几个「AI 员工」

```bash
hermes profile create architect
hermes profile create coder
hermes profile create tester
hermes profile create reviewer
hermes profile create devops
hermes profile create doc
```

### 2. 派个活，让工位动起来

```bash
hermes kanban create "设计 Todo API 架构方案（数据模型/接口/分层）" --assignee architect
```

### 3. 把办公室开起来

```bash
git clone https://github.com/alphixness/hermes-office.git
cd hermes-office
python office_server.py            # 零依赖，纯标准库 → http://127.0.0.1:8123
```

就这样，办公室开门了。**纯标准库，不装任何东西**。

---

## 四、把它变成「应用」，而不是一个浏览器标签

浏览器标签总差点意思。我想要的是一间**真正的窗口**：无地址栏、无标签页、关窗即退出，任务栏上就叫「Hermes 办公室」。

用 `pywebview`（Windows 下走系统自带的 Edge WebView2 内核）：

```bash
uv venv .venv
uv pip install --python .venv\Scripts\python.exe pywebview pythonnet
cscript launch-office.vbs          # 或双击
```

再给它做个桌面快捷方式 + 图标（四个员工头像拼合 + 圆角），双击就是一个"应用"了。

![办公室工位区（老板办公室 / 经理办公室 / 开放工位区）](https://raw.githubusercontent.com/alphixness/hermes-office/main/docs/office-floor.png)

---

## 五、我踩过的 5 个最阴的坑（建议你直接抄结论）

**1）Token 全是 0**
`sessions.started_at` 存的是 **Unix 时间戳**（`1789460816.71`），不是 `2026-09-16` 这种字符串。
拿日期字符串去比较，一行都匹配不到。

**2）只有一个员工的 Token，其他都是 0**
**每个 profile 是独立的 Hermes home**，账在各自的 `state.db` 里：

```
~/.hermes/state.db                    ← 只有默认 Agent 的账
~/.hermes/profiles/coder/state.db     ← coder 自己的账（可能几十上百 MB）
```

想"按工位分账"，必须逐个 profile 读。**这也是"按员工统计"唯一正确的做法。**

**3）`pythonw` 启动：进程活着、端口在听、就是没有窗口**
无控制台运行时 `sys.stdout` / `sys.stderr` 是 **`None`**，脚本里任何一个 `print()` 都会抛
`AttributeError`，把**后面创建窗口的代码整段打断** —— 而它是后台线程先起服务，所以你只会看到
"服务正常、窗口没有"。解法：启动时先把输出重定向到日志文件。

**4）`.vbs` 双击没反应**
WSH 默认按 **ANSI** 读脚本 → **含中文的 UTF-8 vbs 会乱码且不报错**，只返回退出码 1。
解法：`.vbs` 用纯 ASCII 文件名 + 纯 ASCII 内容，中文名字留给桌面快捷方式（`.lnk` 支持 Unicode）。

**5）`WScript.Shell.Run(cmd, 0, False)` 会把窗口一起藏起来**
那个 `0` 是「隐藏窗口」。而 `pythonw.exe` 本身就是创建 GUI 的进程，于是**它创建的窗口也被标记为隐藏**：
进程在跑、端口在听、任务管理器能看到，**就是屏幕上没有**。必须用 `1`。

> 附赠一条：**150% 缩放下"右侧面板被挤出屏幕"** —— 窗口明明 1721×1033，WebView 里却只有约
> 960 CSS 宽度再被放大 1.5 倍。要做两件事：进程**声明 DPI 感知** + CSS 用
> `@media (max-height: 820px)` 分档压缩。**只做一半没用。**

---

## 六、进阶：让它长得像"你的"公司

- **给员工改名换岗**：全在 `agents.json` 里，改完刷新即生效，不用动代码
- **顶部公司名 / slogan**：界面点「✏️ 改标语」直接改，存回同一个文件
- **头像**：`make_avatars.py` 走生图引擎批量出「唯美卡通」头像（我就是这么做的 5 女 5 男 10 张），
  提示词写在 `agents.json` 的 `prompt` 字段里
- **卡住了/在排队**：头像会变色（绿=在岗呼吸灯、黄=排队、红=卡住并歪 6°）、空岗显示「招人中」

---

## 七、最后

做好之后我发现，它最大的价值不是"好看"，而是**把黑盒打开了一条缝**：
以前我发一条指令就等着，现在我一眼能看到谁在干、卡在哪、烧了多少钱。

而且它证明了一件事 —— 你机器上那些"看不见的数据"，只要肯画出来，就是一整间办公室。

**仓库在这里，MIT 协议，随意改：**
👉 https://github.com/alphixness/hermes-office

如果它对你有用，给个 ⭐ 就好。
有想让它长成什么样（会议室？值班表？Token 日报？）欢迎在 Issue 里说。

---

*本文的完整教程（含 11 个实测坑与全部代码）在仓库里的 `教程-Hermes可视化办公室.md`。*
