# 桌面插件版 · Hermes Desktop Plugin

把办公室直接搬进 **Hermes 桌面端**：右侧分栏、整页路由、侧边栏入口、状态栏小灯、
命令面板、快捷键 —— 不用再另开一个窗口。

> 这是官方 **Desktop Plugin SDK** 的用法（`$HERMES_HOME/desktop-plugins/<id>/plugin.js`）。
> 插件是**一个 ESM 文件**，丢进去几秒内加载，**保存即热重载**，不需要 npm build、不需要改 app 源码。

## 安装（10 秒）

```bash
# Windows
mkdir "%LOCALAPPDATA%\hermes\desktop-plugins\hermes-office"
copy desktop-plugin\plugin.js "%LOCALAPPDATA%\hermes\desktop-plugins\hermes-office\plugin.js"

# macOS / Linux
mkdir -p ~/.hermes/desktop-plugins/hermes-office
cp desktop-plugin/plugin.js ~/.hermes/desktop-plugins/hermes-office/plugin.js
```

> 命名 profile 要放 `~/.hermes/profiles/<name>/desktop-plugins/hermes-office/plugin.js`
> **文件夹名必须等于 `id`**（这里是 `hermes-office`），否则不加载。

保存后应用会在几秒内自动加载。没出现就跑 **⌘K / Ctrl+K → Reload desktop plugins**；
也可以到 **Settings → Plugins** 看「Hermes 办公室」是否在列表里，随时开关。

## 你会得到 4 个入口

| 入口 | 位置 |
|---|---|
| **分栏 pane** | 右侧，和终端/文件面板并列；拖动能停靠到任意边 |
| **整页** | 侧边栏「Hermes 办公室」，或 ⌘K → 「打开 Hermes 办公室」 |
| **状态栏小灯** | 底部状态栏右侧 `● 办公室`：绿=数据服务在线，红=没起（点一下有启动指引） |
| **快捷键** | `⌘/Ctrl + Shift + O` |

## 前提：数据服务要在跑

插件只负责**显示**，数据来自本地那个只读服务：

```bash
cd hermes-office
python office_server.py          # 零依赖，默认 127.0.0.1:8123
```

双击桌面「Hermes办公室」快捷方式也会顺带把它起起来。
服务没跑时，面板会直接告诉你怎么启动，并给一个「复制命令」按钮。

## 它做了什么 / 没做什么

- ✅ 显示办公室（工位、聊天室、统计），可刷新、可用浏览器打开
- ✅ 状态栏实时反映数据服务是否在线
- ❌ **不写任何数据**：派活仍然走主界面聊天室或独立窗口（POST 接口没有开 CORS，防止随便一个网页就能往你
  看板派任务；GET 才允许跨域读取）

## 写插件时要记住的 SDK 硬规则

1. disk 插件**不编译**，只能 import 这三个：`@hermes/plugin-sdk`、`react`、`react/jsx-runtime`
2. **不能写 JSX 语法**，要用 `jsx()` / `jsxs()` 调用（从 `react/jsx-runtime` 取）
3. `id` 必须等于文件夹名
4. 用 `import * as SDK from '@hermes/plugin-sdk'` 比具名导入更抗改名（某个导出没了不会整个模块链接失败）
5. 颜色用主题变量 `var(--ui-*)`，别写死色值，否则切主题会花
6. 加载失败会弹 toast 并写日志：`hermes logs gui -f`

官方参考：<https://hermes-agent.nousresearch.com/docs/developer-guide/desktop-plugin-sdk>
