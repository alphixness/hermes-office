// Hermes 办公室 · 桌面端原生面板
// 位置: $HERMES_HOME/plugins/hermes-office/desktop/plugin.js   （统一包：agent 侧 + 桌面侧同一个文件夹）
//
// 与原「独立窗口版」的区别：**不依赖任何本地端口**。
// 数据走 ctx.rest → gateway 自己的路由 /api/plugins/hermes-office/*（由本插件 dashboard/plugin_api.py 提供），
// 所以在桌面端里打开就是原生面板，不需要先把 8123 跑起来。
//
// SDK 硬规则（disk/统一包都不编译）：
//   · 只能 import '@hermes/plugin-sdk' / 'react' / 'react/jsx-runtime'
//   · 不能写 JSX 语法，用 jsx() / jsxs()
//   · 用 import * as SDK，避免某个导出改名导致整个模块链接失败
import * as SDK from '@hermes/plugin-sdk'
import { useCallback, useEffect, useRef, useState } from 'react'
import { jsx, jsxs } from 'react/jsx-runtime'

const host = SDK.host

const AREA = {
  panes: SDK.PANES_AREA || 'panes',
  routes: SDK.ROUTES_AREA || 'routes',
  nav: SDK.SIDEBAR_NAV_AREA || 'sidebarNav',
  statusRight: (SDK.STATUSBAR_AREAS && SDK.STATUSBAR_AREAS.right) || 'statusBar.right',
  palette: SDK.PALETTE_AREA || 'palette',
  keybinds: SDK.KEYBINDS_AREA || 'keybinds',
}

const PAGE_PATH = '/office'
const POLL_MS = 5000

let CTX = null

/* ------------------------------------------------------------------ 数据层 */

const STATE_CN = {
  working: '在岗干活', queued: '排队待命', blocked: '卡住了',
  idle: '空闲', done: '收工', vacant: '招人中', human: '本人',
}
const STATE_COLOR = {
  working: '#4fd18b', queued: '#e8b44a', blocked: '#e2645f',
  idle: '#8a819e', vacant: '#5b5470', human: '#ffd479',
}

function nf(n) { return (n || 0).toLocaleString('en-US') }
function shortT(t) { return t ? String(t).replace('T', ' ').slice(5, 16) : '—' }

function useOfficeData() {
  const [data, setData] = useState(null)
  const [avatars, setAvatars] = useState({})
  const [error, setError] = useState(null)
  const [updatedAt, setUpdatedAt] = useState(null)
  const alive = useRef(true)

  const pull = useCallback(async () => {
    if (!CTX || !CTX.rest) { setError('ctx.rest 不可用（插件后端没挂载）'); return }
    try {
      const d = await CTX.rest('/office')
      if (!alive.current) return
      setData(d); setError(null); setUpdatedAt(new Date())
    } catch (e) {
      if (alive.current) setError(String((e && e.message) || e))
    }
  }, [])

  useEffect(() => {
    alive.current = true
    pull()
    // 头像只取一次（base64 内嵌），别塞进轮询
    if (CTX && CTX.rest) CTX.rest('/avatars').then(a => { if (alive.current) setAvatars(a || {}) }).catch(() => {})
    const t = setInterval(pull, POLL_MS)
    return () => { alive.current = false; clearInterval(t) }
  }, [pull])

  return { data, avatars, error, updatedAt, refresh: pull }
}

/* ------------------------------------------------------------------ 小组件 */

function Avatar({ agent, avatars, size = 34 }) {
  const src = agent && avatars[agent.avatar || agent.name]
  const st = agent ? (agent.exists ? agent.state : 'vacant') : 'vacant'
  const ring = STATE_COLOR[st] || '#8a819e'
  const common = {
    width: size, height: size, borderRadius: '50%', flex: `0 0 ${size}px`,
    background: src ? `url(${src}) center/cover no-repeat` : 'var(--ui-bg-secondary, #2a2334)',
    border: `2px solid ${ring}`,
    display: 'flex', alignItems: 'center', justifyContent: 'center',
    fontSize: size * 0.42, color: 'var(--ui-text-tertiary, #9d93ad)',
    transform: st === 'blocked' ? 'rotate(-6deg)' : 'none',
  }
  return jsx('div', { style: common, children: src ? null : (agent && agent.display_name ? agent.display_name.slice(0, 1) : '?') })
}

function StateDot({ state }) {
  return jsx('span', {
    style: { display: 'inline-block', width: 6, height: 6, borderRadius: '50%', background: STATE_COLOR[state] || '#8a819e', marginRight: 4, verticalAlign: 1 },
  })
}

function Desk({ agent, avatars, onClick, active }) {
  const st = agent.exists ? (agent.state || 'idle') : 'vacant'
  const cur = agent.current && agent.current.title
  const line = agent.human ? '👑 点我派活给经理 →'
    : cur ? '🔨 ' + cur
      : agent.last_activity ? '⚡ ' + agent.last_activity
        : '— 待命中 —'
  return jsxs('button', {
    type: 'button',
    onClick,
    className: 'flex flex-col gap-1.5 rounded-lg border p-2 text-left',
    style: {
      borderColor: active ? 'var(--ui-accent, #ffd479)' : 'var(--ui-border, #3a3147)',
      background: 'var(--ui-bg-secondary, #251f30)',
      cursor: 'pointer',
    },
    children: [
      jsxs('div', {
        className: 'flex items-center gap-2',
        children: [
          jsx(Avatar, { agent, avatars }),
          jsxs('div', {
            className: 'flex min-w-0 flex-col',
            children: [
              jsx('div', { className: 'truncate text-xs font-medium', children: agent.display_name }),
              jsxs('div', {
                className: 'flex items-center text-[0.6875rem] text-(--ui-text-tertiary)',
                children: [jsx(StateDot, { state: st }), jsx('span', { className: 'truncate', children: agent.role + ' · ' + (STATE_CN[st] || st) })],
              }),
            ],
          }),
        ],
      }),
      jsx('div', {
        className: 'truncate text-[0.6875rem] text-(--ui-text-tertiary)',
        title: line,
        children: line,
      }),
      jsxs('div', {
        className: 'flex items-center justify-between text-[0.625rem] text-(--ui-text-tertiary)',
        children: [
          jsx('span', { children: '完成 ' + ((agent.counts && agent.counts.done) || 0) }),
          jsx('span', { children: nf(agent.tokens && agent.tokens.total) + ' tok' }),
        ],
      }),
    ],
  })
}

function Detail({ agent, avatars }) {
  if (!agent) return null
  const tasks = agent.tasks || []
  const recs = agent.recent || []
  return jsxs('div', {
    className: 'flex flex-col gap-2 rounded-lg border p-2 text-xs',
    style: { borderColor: 'var(--ui-border, #3a3147)', background: 'var(--ui-bg-secondary, #251f30)' },
    children: [
      jsxs('div', {
        className: 'flex items-center gap-2',
        children: [
          jsx(Avatar, { agent, avatars, size: 28 }),
          jsx('span', { className: 'font-medium', children: agent.display_name }),
          jsx('span', { className: 'text-(--ui-text-tertiary)', children: agent.role }),
          jsx('span', { className: 'grow' }),
          jsx('span', {
            className: 'text-(--ui-text-tertiary)',
            children: 'Token ' + nf(agent.tokens.total) + ' · $' + (agent.tokens.cost_usd || 0).toFixed(4),
          }),
        ],
      }),
      tasks.length
        ? jsxs('div', { className: 'flex flex-col gap-1', children: [
            jsx('div', { className: 'text-(--ui-text-tertiary)', children: '任务' }),
            ...tasks.slice(0, 6).map(t => jsxs('div', {
              key: t.id,
              className: 'flex items-center gap-2',
              children: [
                jsx('span', { className: 'text-(--ui-text-tertiary)', children: '[' + t.status + ']' }),
                jsx('span', { className: 'truncate', children: t.title }),
                jsx('span', { className: 'grow' }),
                jsx('span', { className: 'text-(--ui-text-tertiary)', children: shortT(t.updated_at) }),
              ],
            })),
          ] })
        : null,
      recs.length
        ? jsxs('div', { className: 'flex flex-col gap-1', children: [
            jsx('div', { className: 'text-(--ui-text-tertiary)', children: '最近工作记录（来自它自己的 state.db）' }),
            ...recs.slice(0, 4).map((r, i) => jsxs('div', {
              key: i,
              className: 'flex items-center gap-2',
              children: [
                jsx('span', { className: 'text-(--ui-text-tertiary)', children: shortT(r.at) }),
                jsx('span', { className: 'truncate', children: r.title }),
              ],
            })),
          ] })
        : null,
    ],
  })
}

function Feed({ feed, avatars, agents }) {
  if (!feed || !feed.length) {
    return jsx('div', { className: 'p-3 text-xs text-(--ui-text-tertiary)', children: '还没有互动记录。派个任务给员工，这里就会出现他们之间的交流。' })
  }
  const byName = {}
  ;(agents || []).forEach(a => { byName[a.name] = a })
  return jsxs('div', {
    className: 'flex flex-col gap-1.5 p-2 text-xs',
    children: feed.slice().reverse().map((m, i) => {
      const a = m.author ? byName[m.author] : null
      return jsxs('div', {
        className: 'flex items-start gap-2 rounded border p-1.5',
        style: { borderColor: 'var(--ui-border, #3a3147)' },
        children: [
          jsx(Avatar, { agent: a || { name: m.author || '?', display_name: m.author || '系统', exists: false, state: 'idle' }, avatars, size: 22 }),
          jsxs('div', {
            className: 'min-w-0 flex-1',
            children: [
              jsxs('div', {
                className: 'flex items-center gap-2 text-[0.6875rem] text-(--ui-text-tertiary)',
                children: [
                  jsx('span', { className: 'font-medium', children: a ? a.display_name : (m.author || '系统') }),
                  jsx('span', { children: m.kind || '' }),
                  jsx('span', { className: 'grow' }),
                  jsx('span', { children: shortT(m.at) }),
                ],
              }),
              m.text ? jsx('div', { style: { whiteSpace: 'pre-wrap', wordBreak: 'break-word' }, children: m.text }) : null,
              m.task ? jsx('div', { className: 'text-(--ui-text-tertiary)', children: '📋 ' + m.task }) : null,
            ],
          }),
        ],
      }, i)
    }),
  })
}

function Stat({ label, value, sub }) {
  return jsxs('div', {
    className: 'flex flex-col rounded border px-2 py-1',
    style: { borderColor: 'var(--ui-border, #3a3147)' },
    children: [
      jsx('div', { className: 'text-[0.625rem] text-(--ui-text-tertiary)', children: label }),
      jsx('div', { className: 'text-sm font-semibold', children: value }),
      sub ? jsx('div', { className: 'text-[0.625rem] text-(--ui-text-tertiary)', children: sub }) : null,
    ],
  })
}

/* ------------------------------------------------------------------ 主面板 */

function OfficePanel({ full }) {
  const { data, avatars, error, updatedAt, refresh } = useOfficeData()
  const [tab, setTab] = useState('desks')
  const [selected, setSelected] = useState(null)

  const agents = (data && data.agents) || []
  const totals = (data && data.totals) || {}
  const office = (data && data.office) || {}

  const boss = agents.find(a => a.seat === 'boss')
  const mgr = agents.find(a => a.seat === 'manager')
  const staff = agents.filter(a => a.seat === 'staff')
  const sel = selected ? agents.find(a => a.name === selected) : null

  if (error && !data) {
    return jsxs('div', {
      className: 'flex h-full flex-col items-center justify-center gap-2 p-6 text-center text-xs',
      children: [
        jsx('div', { className: 'text-sm font-medium', children: '🏢 插件后端没挂上' }),
        jsx('div', { className: 'text-(--ui-text-tertiary)', children: error }),
        jsxs('div', {
          className: 'text-(--ui-text-tertiary)',
          children: [
            jsx('div', { children: '检查：Settings → Plugins 里「Hermes 办公室」是否启用；' }),
            jsx('div', { children: '用户插件要在 config.yaml 的 plugins.enabled 列表里，改动后需要重启 gateway。' }),
          ],
        }),
        jsx('button', {
          type: 'button',
          className: 'rounded border px-2 py-1',
          style: { borderColor: 'var(--ui-border, #3a3147)' },
          onClick: refresh,
          children: '重试',
        }),
      ],
    })
  }

  const tabBtn = (id, label) => jsx('button', {
    type: 'button',
    onClick: () => setTab(id),
    className: 'rounded px-2 py-0.5 text-xs',
    style: {
      background: tab === id ? 'var(--ui-bg-secondary, #251f30)' : 'transparent',
      color: tab === id ? 'var(--ui-text, #efe9f5)' : 'var(--ui-text-tertiary, #9d93ad)',
      cursor: 'pointer',
    },
    children: label,
  })

  return jsxs('div', {
    className: 'flex h-full w-full flex-col gap-2 overflow-auto p-2 text-xs',
    children: [
      // 顶部横幅 + 统计
      jsxs('div', {
        className: 'flex flex-wrap items-center gap-2',
        children: [
          jsx('div', { className: 'text-sm font-semibold', children: '🏢 ' + (office.title || 'Hermes 办公室') }),
          office.slogan ? jsx('div', { className: 'text-(--ui-text-tertiary)', children: office.slogan }) : null,
          jsx('div', { className: 'grow' }),
          jsx('button', {
            type: 'button', onClick: refresh,
            className: 'rounded border px-2 py-0.5',
            style: { borderColor: 'var(--ui-border, #3a3147)' },
            children: '刷新',
          }),
        ],
      }),
      jsxs('div', {
        className: 'grid gap-1.5',
        style: { gridTemplateColumns: 'repeat(auto-fit, minmax(84px, 1fr))' },
        children: [
          jsx(Stat, { label: 'Token 总量', value: nf(totals.tokens_total) }),
          jsx(Stat, { label: '成本', value: '$' + (totals.cost_usd || 0).toFixed(4) }),
          jsx(Stat, { label: '在岗 / 完成', value: (totals.working || 0) + ' / ' + (totals.done || 0) }),
          jsx(Stat, { label: '工位 / 在编', value: (totals.seats || 0) + ' / ' + (totals.agents || 0) }),
        ],
      }),
      // tab
      jsxs('div', {
        className: 'flex items-center gap-1',
        children: [
          tabBtn('desks', '🪑 工位'),
          tabBtn('chat', '💬 聊天室'),
          jsx('span', { className: 'grow' }),
          jsx('span', {
            className: 'text-[0.625rem] text-(--ui-text-tertiary)',
            children: updatedAt ? '更新于 ' + updatedAt.toLocaleTimeString('zh-CN', { hour12: false }) : '加载中…',
          }),
        ],
      }),
      tab === 'desks'
        ? jsxs('div', {
            className: 'flex flex-col gap-2',
            children: [
              // 老板 / 经理
              jsxs('div', {
                className: 'grid gap-1.5',
                style: { gridTemplateColumns: 'repeat(auto-fit, minmax(180px, 1fr))' },
                children: [
                  boss ? jsx(Desk, { key: 'boss', agent: boss, avatars, active: selected === boss.name, onClick: () => setSelected(boss.name) }) : null,
                  mgr ? jsx(Desk, { key: 'mgr', agent: mgr, avatars, active: selected === mgr.name, onClick: () => setSelected(mgr.name) }) : null,
                ],
              }),
              jsx('div', { className: 'text-(--ui-text-tertiary)', children: '开放工位区 · ' + staff.filter(a => a.exists).length + ' 人在编 / ' + staff.length + ' 个工位' }),
              jsxs('div', {
                className: 'grid gap-1.5',
                style: { gridTemplateColumns: 'repeat(auto-fill, minmax(150px, 1fr))' },
                children: staff.map(a => jsx(Desk, {
                  key: a.name, agent: a, avatars, active: selected === a.name, onClick: () => setSelected(a.name),
                })),
              }),
              sel ? jsx(Detail, { agent: sel, avatars }) : null,
            ],
          })
        : jsx(Feed, { feed: data ? data.feed : [], avatars, agents }),
      jsx('div', {
        className: 'text-[0.625rem] text-(--ui-text-tertiary)',
        children: '数据：' + ((data && data.hermes_home) || '?') + ' · 只读（kanban.db + 各 profile 的 state.db）',
      }),
    ],
  })
}

/* ------------------------------------------------------------------ 状态栏 */

function OfficeChip() {
  const { data } = useOfficeData()
  const working = data ? ((data.totals && data.totals.working) || 0) : 0
  const tokens = data ? ((data.totals && data.totals.tokens_total) || 0) : 0
  const color = working > 0 ? '#4fd18b' : '#8a819e'
  return jsxs('button', {
    type: 'button',
    title: 'Hermes 办公室：' + (data ? (working + ' 人在岗 · ' + nf(tokens) + ' tok') : '加载中'),
    className: 'flex items-center gap-1 px-1.5 text-[0.6875rem] text-(--ui-text-tertiary)',
    style: { cursor: 'pointer' },
    onClick: () => { if (SDK.haptic) SDK.haptic('tap'); host.navigate(PAGE_PATH) },
    children: [
      jsx('span', { style: { display: 'inline-block', width: 6, height: 6, borderRadius: '50%', background: color } }),
      jsx('span', { children: '办公室' + (working ? ' ' + working : '') }),
    ],
  })
}

/* ------------------------------------------------------------------ 注册 */

export default {
  id: 'hermes-office',
  name: 'Hermes 办公室',
  defaultEnabled: true,

  register(ctx) {
    CTX = ctx

    ctx.registerMany([
      { id: 'pane', area: AREA.panes, title: 'office', data: { placement: 'right', width: '480px' }, render: () => jsx(OfficePanel, { full: false }) },
      { id: 'page', area: AREA.routes, data: { path: PAGE_PATH }, render: () => jsx(OfficePanel, { full: true }) },
      { id: 'nav', area: AREA.nav, data: { path: PAGE_PATH, label: 'Hermes 办公室', codicon: 'organization' } },
      { id: 'chip', area: AREA.statusRight, order: 140, render: () => jsx(OfficeChip, {}) },
      { id: 'open', area: AREA.palette, data: { id: 'hermes-office.open', label: '打开 Hermes 办公室', keywords: ['office', 'bangongshi', 'kanban', 'agent', '工位'], run: () => host.navigate(PAGE_PATH) } },
      { id: 'key', area: AREA.keybinds, data: { id: 'hermes-office.open.key', label: '打开 Hermes 办公室', category: 'Hermes 办公室', defaults: ['mod+shift+o'], run: () => host.navigate(PAGE_PATH) } },
    ])
  },
}
