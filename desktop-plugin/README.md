# 桌面插件版 · Hermes Desktop Plugin

把办公室直接搬进 **Hermes 桌面端**：右侧分栏、整页路由、侧边栏入口、状态栏小灯、命令面板、快捷键。

**原生 React 面板，不依赖任何额外端口** —— 数据走 `ctx.rest` → gateway 自己的路由
`/api/plugins/hermes-office/*`（由本插件后端提供），不需要先把 8123 跑起来。

> 用的是官方 **Desktop Plugin SDK**（`$HERMES_HOME/desktop-plugins/` 与统一包
> `$HERMES_HOME/plugins/<id>/desktop/plugin.js`）。插件是普通 ESM，**保存即热重载**，
> 不需要 npm build、不需要改 app 源码。

## 安装（一次）

```bash
# 1) 把整个插件包放进 plugins 目录（文件夹名必须 = id = hermes-office）
#    Windows
xcopy /E /I desktop-plugin "%LOCALAPPDATA%\hermes\plugins\hermes-office"
#    macOS / Linux
cp -r desktop-plugin ~/.hermes/plugins/hermes-office

# 2) 启用（用户插件默认 opt-in，必须在 plugins.enabled 里）
hermes plugins enable hermes-office

# 3) 自检
hermes plugins doctor hermes-office      # 期望：OK: runtime discovery, manifest parsing, import, and registration passed
```

桌面端面板几秒内自动加载（保存 `desktop/plugin.js` 即热重载）。
没出现就跑 **⌘K / Ctrl+K → Reload desktop plugins**，或到 **Settings → Plugins** 看一眼。

> 💡 `ctx.rest` 需要插件后端已挂载。已挂载的标志：直接请求会返回 **401（要 app 鉴权）而不是 404**：
> `curl -s -o /dev/null -w '%{http_code}' http://127.0.0.1:<后端端口>/api/plugins/hermes-office/health`
> 如果拿到 404，重启一次桌面端让后端重新挂载。

## 你会得到 4 个入口

| 入口 | 位置 |
|---|---|
| **分栏 pane** | 右侧，和终端/文件面板并列；可拖动停靠到任意边 |
| **整页** | 侧边栏「Hermes 办公室」，或 ⌘K → 「打开 Hermes 办公室」 |
| **状态栏小灯** | 底部状态栏右侧 `● 办公室 N`（N = 在岗人数，悬停看 Token） |
| **快捷键** | `⌘/Ctrl + Shift + O` |

面板里有两个 tab：**🪑 工位**（老板/经理办公室 + 开放工位区，点开看任务与工作记录）和
**💬 聊天室**（员工评论/完成/运行的实时流）。

## 包结构

```
hermes-office/
├── plugin.yaml              # 插件元数据
├── __init__.py              # agent 侧入口（纯 UI 插件，register 是空的）
├── agents.json             # 花名册 + 顶部横幅（可改名字/岗位/头像/banner）
├── avatars_256/            # 头像缩略图（base64 由后端一次下发）
├── dashboard/
│   ├── manifest.json       # {"name":"hermes-office","api":"plugin_api.py"}
│   └── plugin_api.py       # FastAPI 路由 → /api/plugins/hermes-office/*
└── desktop/
    └── plugin.js           # 桌面端原生面板（panes / routes / nav / statusbar / palette / keybinds）
```

## 数据从哪来（全部只读，`mode=ro`）

| 画面 | 来源 |
|---|---|
| 工位 / 任务 / 聊天室 | `<HERMES_HOME>/kanban.db` → `tasks` / `task_comments` / `task_events` / `task_runs` |
| Token / 成本 / 工作记录 | `<HERMES_HOME>/profiles/<名>/state.db` → `sessions`（**逐 profile 分账**） |
| 老板 / 经理 / 员工席位 | 花名册 `agents.json`（`seat` / `bind_profile` / `human`） |

`plugin_api.py` 用 `hermes_cli.kanban_db.kanban_db_path()` 定位数据目录（跟着 `HERMES_HOME`
和多看板走），失败才退回环境变量与平台默认目录。

## 它做了什么 / 没做什么

- ✅ 只读展示：工位、聊天室、Token 排行
- ✅ 后台 5 秒轮询；头像只在加载时取一次（base64 内嵌，避免静态路由与鉴权口子）
- ❌ **不写任何数据**：不派活、不改看板、不占工具权限（`plugins.enable` 时 `allow_tool_override=False`）

## 写桌面插件要记住的 SDK 硬规则

1. disk/统一包都**不编译**，只能 import 这三个：`@hermes/plugin-sdk`、`react`、`react/jsx-runtime`
2. **不能写 JSX 语法**，要用 `jsx()` / `jsxs()`（从 `react/jsx-runtime`）
3. `id` 必须等于文件夹名，且**全局唯一**（和旧的磁盘插件同 id 会冲突 —— 本项目就把旧版挪到了 `variant-iframe/`）
4. 用 `import * as SDK from '@hermes/plugin-sdk'`，比具名导入抗改名
5. 颜色用 `var(--ui-*)` 主题变量，别写死色值
6. `ctx.rest` 的路径是**相对插件命名空间**的（`/office` → `/api/plugins/hermes-office/office`）
7. 加载失败会弹 toast：`hermes logs gui -f`

## 另一种形态：`variant-iframe/plugin.js`

早期版本：单文件、把现有 `office_server.py` 的页面 iframe 进来。优点是**零改动复用**，
缺点是**必须先跑 8123 服务**、并且是网页嵌网页。除非你就想那样，否则推荐用上面的原生版。

官方参考：<https://hermes-agent.nousresearch.com/docs/developer-guide/desktop-plugin-sdk>
