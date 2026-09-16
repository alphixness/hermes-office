// Hermes 办公室 · 桌面插件版
// 位置: $HERMES_HOME/desktop-plugins/hermes-office/plugin.js   (文件夹名必须 = id)
// 作用: 把 https://github.com/alphixness/hermes-office 的办公室，搬进桌面端
//       右侧分栏 + 整页路由 + 侧边栏入口 + 状态栏小灯 + 命令面板 + 快捷键
//
// 注意（SDK 硬规则）:
//   · disk 插件不编译，只能 import '@hermes/plugin-sdk' / 'react' / 'react/jsx-runtime'
//   · 不能写 JSX 语法，要用 jsx() / jsxs() 调用
//   · 用 import * as SDK 而不是具名导入，避免某个导出改名时整个模块链接失败
import * as SDK from '@hermes/plugin-sdk'
import { useEffect, useRef, useState, useCallback } from 'react'
import { jsx, jsxs } from 'react/jsx-runtime'

const host = SDK.host

// 区域常量：优先用 SDK 导出的，取不到就退回文档里的字面量
const AREA = {
  panes: SDK.PANES_AREA || 'panes',
  routes: SDK.ROUTES_AREA || 'routes',
  nav: SDK.SIDEBAR_NAV_AREA || 'sidebarNav',
  statusRight: (SDK.STATUSBAR_AREAS && SDK.STATUSBAR_AREAS.right) || 'statusBar.right',
  palette: SDK.PALETTE_AREA || 'palette',
  keybinds: SDK.KEYBINDS_AREA || 'keybinds',
}

const OFFICE_URL = 'http://127.0.0.1:8123'
const PAGE_PATH = '/office'

// ctx 在 register() 里拿到，组件里要用（复制命令、提示 toast）
let CTX = null

/* ------------------------------------------------------------------ 小工具 */

function useOfficeHealth() {
  const [state, setState] = useState('unknown')   // unknown | up | down
  const check = useCallback(async () => {
    try {
      const r = await fetch(OFFICE_URL + '/health', { cache: 'no-store' })
      setState(r.ok ? 'up' : 'down')
    } catch (e) {
      setState('down')
    }
  }, [])
  useEffect(() => {
    let alive = true
    const run = () => { if (alive) check() }
    run()
    const t = setInterval(run, 8000)
    return () => { alive = false; clearInterval(t) }
  }, [check])
  return [state, check]
}

async function copyText(text, label) {
  try {
    if (CTX && CTX.os && CTX.os.writeClipboard) await CTX.os.writeClipboard(text)
    else await navigator.clipboard.writeText(text)
    host.notify({ kind: 'info', message: (label || '已复制') + '：' + text })
  } catch (e) {
    host.notify({ kind: 'error', message: '复制失败，请手动复制：' + text })
  }
}

/* --------------------------------------------------------------- 数据服务没跑 */

function SetupHint({ onRetry }) {
  const cmd = 'cd %USERPROFILE%\\Desktop\\hermes-office && python office_server.py'
  return jsx('div', {
    className: 'flex h-full w-full flex-col items-center justify-center gap-3 p-6 text-center text-sm',
    children: jsxs('div', {
      className: 'flex max-w-[26rem] flex-col gap-2',
      children: [
        jsx('div', { className: 'text-base font-medium', children: '🏢 办公室数据服务没在跑' }),
        jsx('div', {
          className: 'text-(--ui-text-tertiary)',
          children: '这个插件负责显示，数据由本地那个只读服务提供（默认 8123）。启动方式二选一：',
        }),
        jsxs('div', {
          className: 'mt-1 flex flex-col gap-1 text-left text-(--ui-text-secondary)',
          children: [
            jsx('div', { children: '① 双击桌面「Hermes办公室」快捷方式（独立窗口也会顺带把服务起起来）' }),
            jsx('div', { children: '② 或手动跑下面这条命令：' }),
          ],
        }),
        jsx('code', {
          className: 'select-all rounded bg-(--ui-bg-secondary) px-2 py-1.5 text-left text-xs',
          children: cmd,
        }),
        jsxs('div', {
          className: 'mt-1 flex items-center justify-center gap-2',
          children: [
            jsx('button', {
              type: 'button',
              className: 'rounded border border-(--ui-border) px-2 py-1 text-xs hover:bg-(--ui-bg-secondary)',
              onClick: () => copyText(cmd, '已复制启动命令'),
              children: '复制命令',
            }),
            jsx('button', {
              type: 'button',
              className: 'rounded border border-(--ui-border) px-2 py-1 text-xs hover:bg-(--ui-bg-secondary)',
              onClick: onRetry,
              children: '重新检测',
            }),
          ],
        }),
      ],
    }),
  })
}

/* ------------------------------------------------------------------ 办公室本体 */

function OfficeView({ full }) {
  const [health, recheck] = useOfficeHealth()
  const [nonce, setNonce] = useState(0)
  const [loaded, setLoaded] = useState(false)

  const reload = useCallback(() => { setLoaded(false); setNonce(n => n + 1) }, [])

  if (health === 'down') {
    return jsx(SetupHint, { onRetry: () => { recheck(); reload() } })
  }

  return jsxs('div', {
    className: 'flex h-full w-full flex-col',
    children: [
      jsxs('div', {
        className: 'flex shrink-0 items-center gap-2 border-b border-(--ui-border) px-2 py-1 text-xs',
        children: [
          jsx('span', { className: 'font-medium', children: '🏢 Hermes 办公室' }),
          jsx('span', {
            className: 'text-(--ui-text-tertiary)',
            children: health === 'up' ? '已连接 8123' : '连接中…',
          }),
          jsx('span', { className: 'grow' }),
          jsx('button', {
            type: 'button',
            className: 'rounded border border-(--ui-border) px-1.5 py-0.5 hover:bg-(--ui-bg-secondary)',
            onClick: reload,
            children: '刷新',
          }),
          jsx('button', {
            type: 'button',
            className: 'rounded border border-(--ui-border) px-1.5 py-0.5 hover:bg-(--ui-bg-secondary)',
            onClick: () => CTX && CTX.os && CTX.os.openExternal(OFFICE_URL),
            children: '浏览器打开',
          }),
        ],
      }),
      jsx('iframe', {
        key: nonce,
        title: 'Hermes 办公室',
        src: OFFICE_URL + '/?v=' + nonce,
        onLoad: () => setLoaded(true),
        className: 'w-full grow border-0 bg-transparent',
        style: { minHeight: full ? '60vh' : '420px' },
      }),
    ],
  })
}

/* ----------------------------------------------------------------- 状态栏小灯 */

function OfficeChip() {
  const [health] = useOfficeHealth()
  const color = health === 'up' ? '#4fd18b' : health === 'down' ? '#e2645f' : '#8a819e'
  return jsxs('button', {
    type: 'button',
    className: 'flex items-center gap-1 px-1.5 text-[0.6875rem] text-(--ui-text-tertiary)',
    title: health === 'up' ? 'Hermes 办公室：数据服务在线' : 'Hermes 办公室：数据服务未运行（点一下看怎么启动）',
    onClick: () => { if (SDK.haptic) SDK.haptic('tap'); host.navigate(PAGE_PATH) },
    children: [
      jsx('span', { style: { display: 'inline-block', width: '6px', height: '6px', borderRadius: '50%', background: color } }),
      jsx('span', { children: '办公室' }),
    ],
  })
}

/* ---------------------------------------------------------------------- 注册 */

export default {
  id: 'hermes-office',
  name: 'Hermes 办公室',
  defaultEnabled: true,

  register(ctx) {
    CTX = ctx

    ctx.registerMany([
      // 右侧分栏：和终端/文件面板并列，可以拖到任意位置
      {
        id: 'pane',
        area: AREA.panes,
        title: 'office',
        data: { placement: 'right', width: '460px' },
        render: () => jsx(OfficeView, { full: false }),
      },
      // 整页路由 + 侧边栏入口
      {
        id: 'page',
        area: AREA.routes,
        data: { path: PAGE_PATH },
        render: () => jsx(OfficeView, { full: true }),
      },
      {
        id: 'nav',
        area: AREA.nav,
        data: { path: PAGE_PATH, label: 'Hermes 办公室', codicon: 'organization' },
      },
      // 状态栏小灯
      {
        id: 'chip',
        area: AREA.statusRight,
        order: 140,
        render: () => jsx(OfficeChip, {}),
      },
      // 命令面板
      {
        id: 'open',
        area: AREA.palette,
        data: {
          id: 'hermes-office.open',
          label: '打开 Hermes 办公室',
          keywords: ['office', 'bangongshi', 'kanban', 'agent', '工位'],
          run: () => host.navigate(PAGE_PATH),
        },
      },
      // 快捷键 ⌘/Ctrl+Shift+O
      {
        id: 'key',
        area: AREA.keybinds,
        data: {
          id: 'hermes-office.open.key',
          label: '打开 Hermes 办公室',
          category: 'Hermes 办公室',
          defaults: ['mod+shift+o'],
          run: () => host.navigate(PAGE_PATH),
        },
      },
    ])

    host.logs && host.logs('plugin', '[hermes-office] 已加载：分栏 / 整页 / 侧边栏 / 状态栏 / 命令面板 / 快捷键')
  },
}
