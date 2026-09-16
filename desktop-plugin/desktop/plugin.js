// Hermes 办公室 · 桌面端原生面板（办公室场景版）
// 位置: $HERMES_HOME/plugins/hermes-office/desktop/plugin.js   （统一包：agent 侧 + 桌面侧同一文件夹）
//
// 与「数据卡片版」的区别：这一版把**办公室场景**搬进了原生面板 —— 墙面/地板、房间隔断、
// 木工位牌、工位气泡、状态灯 —— 全部用 jsx() 原生渲染，**不依赖任何本地端口、没有 iframe**。
// 数据仍走 ctx.rest → /api/plugins/hermes-office/*（gateway 自己的路由）。
//
// SDK 硬规则：只能 import '@hermes/plugin-sdk' / 'react' / 'react/jsx-runtime'；
//            不能写 JSX 语法（用 jsx()/jsxs()）；用 import * as SDK 抗导出改名。
// 配色：文字/边框走主题变量 var(--ui-*)，木色/状态色是设计常量。
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

// —— 设计常量（木色工位牌 + 状态色；文字与边框交给主题变量，切主题不会花）——
const WOOD = { top: '#c08a5e', mid: '#a3714a', deep: '#8c5f3d', ink: '#2b1c10', sub: '#4a3524' }
const STATE_CN = {
  working: '在岗干活', queued: '排队待命', blocked: '卡住了',
  idle: '空闲', done: '收工', vacant: '招人中', human: '本人',
}
const STATE_COLOR = {
  working: '#4fd18b', queued: '#e8b44a', blocked: '#e2645f',
  idle: '#8a819e', vacant: '#5b5470', human: '#ffd479',
}

let CTX = null

function nf(n) { return (n || 0).toLocaleString('en-US') }
function shortT(t) { return t ? String(t).replace('T', ' ').slice(5, 16) : '—' }
function shortTitle(s, n = 22) { return s && s.length > n ? s.slice(0, n) + '…' : (s || '') }

/* ------------------------------------------------------------------ 数据层 */

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
    if (CTX && CTX.rest) CTX.rest('/avatars').then(a => { if (alive.current) setAvatars(a || {}) }).catch(() => {})
    const t = setInterval(pull, POLL_MS)
    return () => { alive.current = false; clearInterval(t) }
  }, [pull])

  return { data, avatars, error, updatedAt, refresh: pull }
}

/* ------------------------------------------------------------------ 场景零件 */

/** 头像：状态环 + 卡住时歪 6°（和独立窗口版保持一致） */
function Face({ agent, avatars, size = 44 }) {
  const src = agent && avatars[agent.avatar || agent.name]
  const st = !agent ? 'vacant' : (agent.human ? 'human' : (agent.exists ? (agent.state || 'idle') : 'vacant'))
  const ring = STATE_COLOR[st] || '#8a819e'
  return jsx('div', {
    style: {
      width: size, height: size, borderRadius: '50%', flex: `0 0 ${size}px`,
      background: src ? `url(${src}) center/cover no-repeat` : 'var(--ui-bg-secondary, #2a2334)',
      border: `3px solid ${ring}`,
      boxShadow: st === 'working' ? `0 0 0 4px ${ring}22` : 'none',
      display: 'flex', alignItems: 'center', justifyContent: 'center',
      fontSize: Math.round(size * 0.4), color: 'var(--ui-text-tertiary, #9d93ad)',
      transform: st === 'blocked' ? 'rotate(-6deg)' : 'none',
      filter: st === 'vacant' ? 'grayscale(1) brightness(.7)' : 'none',
    },
    children: src ? null : ((agent && agent.display_name) ? agent.display_name.slice(0, 1) : '?'),
  })
}

/** 工位气泡：正在干活 / 最近活动 / 待命 */
function bubbleText(agent) {
  if (!agent) return ''
  if (agent.human) return '👑 点我派活给经理 →'
  if (!agent.exists) return '— 招人中 —'
  if (agent.current && agent.current.title) return '🔨 ' + agent.current.title
  if (agent.state === 'blocked') return '⚠️ 卡住了，需要处理'
  if (agent.last_activity) return '⚡ ' + agent.last_activity
  return '— 待命中 —'
}

/** 木工位牌：名字 + 岗位·状态 + 完成/Token */
function Nameplate({ agent }) {
  const st = !agent ? 'vacant' : (agent.human ? 'human' : (agent.exists ? (agent.state || 'idle') : 'vacant'))
  const done = (agent && agent.counts && agent.counts.done) || 0
  return jsxs('div', {
    style: {
      background: `linear-gradient(180deg, ${WOOD.top}, ${WOOD.mid})`,
      border: `1px solid ${WOOD.deep}`,
      borderRadius: 7, padding: '4px 8px',
      boxShadow: 'inset 0 1px 0 rgba(255,255,255,.22), 0 2px 5px rgba(0,0,0,.35)',
      color: WOOD.ink,
    },
    children: [
      jsxs('div', {
        style: { display: 'flex', alignItems: 'center', gap: 6 },
        children: [
          jsx('span', { style: { fontWeight: 700, fontSize: 13, color: '#fff6e8', textShadow: '0 1px 1px rgba(0,0,0,.35)' }, children: agent ? agent.display_name : '招人中' }),
          jsx('span', { style: { width: 6, height: 6, borderRadius: '50%', background: STATE_COLOR[st] || '#8a819e' } }),
          jsx('span', {
            style: { fontSize: 10.5, color: WOOD.sub, whiteSpace: 'nowrap', overflow: 'hidden', textOverflow: 'ellipsis' },
            children: agent ? `${agent.role} · ${STATE_CN[st] || st}` : '—— 空岗 ——',
          }),
        ],
      }),
      jsxs('div', {
        style: { display: 'flex', justifyContent: 'space-between', fontSize: 10, color: WOOD.sub, marginTop: 1 },
        children: [
          jsx('span', { children: agent && agent.exists ? `完成 ${done}` : '' }),
          jsx('span', { children: agent && agent.exists ? `${nf(agent.tokens && agent.tokens.total)} tok` : '' }),
        ],
      }),
    ],
  })
}

/** 一个工位：气泡 → 头像 → 木牌（可点，选中展开详情） */
function Desk({ agent, avatars, onClick, active }) {
  const st = !agent ? 'vacant' : (agent.human ? 'human' : (agent.exists ? (agent.state || 'idle') : 'vacant'))
  const bub = bubbleText(agent)
  const hot = st === 'working'
  return jsxs('button', {
    type: 'button',
    onClick,
    title: bub,
    style: {
      display: 'flex', flexDirection: 'column', gap: 5, alignItems: 'stretch',
      padding: '8px 8px 7px', borderRadius: 12,
      background: 'linear-gradient(180deg, rgba(255,255,255,.045), rgba(0,0,0,.16))',
      border: `1px solid ${active ? 'var(--ui-accent, #ffd479)' : (hot ? 'rgba(79,209,139,.5)' : 'var(--ui-border, #3a3147)')}`,
      boxShadow: hot ? '0 0 22px -10px rgba(79,209,139,.7)' : 'none',
      cursor: 'pointer', textAlign: 'left',
      opacity: st === 'vacant' ? 0.72 : 1,
    },
    children: [
      jsx('div', {
        style: {
          fontSize: 10.5, lineHeight: 1.35, minHeight: 26,
          color: hot ? '#cdf7e3' : 'var(--ui-text-secondary, #cbc2de)',
          background: 'var(--ui-bg, #1d1727)',
          border: `1px solid ${hot ? 'rgba(79,209,139,.35)' : 'var(--ui-border, #3a3147)'}`,
          borderRadius: 7, padding: '3px 6px',
          whiteSpace: 'nowrap', overflow: 'hidden', textOverflow: 'ellipsis',
        },
        children: bub,
      }),
      jsx('div', { style: { display: 'flex', justifyContent: 'center' }, children: jsx(Face, { agent, avatars }) }),
      jsx(Nameplate, { agent }),
    ],
  })
}

/** 一间房间：标题 + 隔断感的容器 */
function Room({ title, note, children, tall }) {
  return jsxs('div', {
    style: {
      border: '1px solid var(--ui-border, #3a3147)',
      borderRadius: 14,
      background: 'linear-gradient(180deg, rgba(255,255,255,.035), rgba(0,0,0,.14))',
      padding: 10,
      display: 'flex', flexDirection: 'column', gap: 8,
    },
    children: [
      jsxs('div', {
        style: { display: 'flex', alignItems: 'center', gap: 8, fontSize: 11, letterSpacing: 1.4, color: 'var(--ui-text-tertiary, #9d93ad)' },
        children: [
          jsx('span', {
            style: { background: 'rgba(255,212,121,.10)', border: '1px solid rgba(255,212,121,.32)', borderRadius: 6, padding: '2px 9px', color: 'var(--ui-accent, #ffd479)' },
            children: title,
          }),
          note ? jsx('span', { style: { letterSpacing: 0 }, children: note }) : null,
        ],
      }),
      jsx('div', {
        style: {
          display: 'grid', gap: 8,
          gridTemplateColumns: tall ? 'repeat(auto-fit, minmax(230px, 1fr))' : 'repeat(auto-fill, minmax(168px, 1fr))',
        },
        children,
      }),
    ],
  })
}

/* ------------------------------------------------------------------ 详情 / 聊天 */

function Detail({ agent, avatars, onClose }) {
  if (!agent) return null
  const tasks = agent.tasks || []
  const recs = agent.recent || []
  const row = (k, v) => jsxs('div', { style: { display: 'flex', gap: 8, alignItems: 'baseline' } , children: [
    jsx('span', { style: { color: 'var(--ui-text-tertiary, #9d93ad)', whiteSpace: 'nowrap' }, children: k }),
    jsx('span', { style: { flex: 1, minWidth: 0, overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }, children: v }),
  ] })
  return jsxs('div', {
    style: { border: '1px solid var(--ui-border, #3a3147)', borderRadius: 12, padding: 10, display: 'flex', flexDirection: 'column', gap: 6 },
    children: [
      jsxs('div', { style: { display: 'flex', alignItems: 'center', gap: 8 }, children: [
        jsx(Face, { agent, avatars, size: 30 }),
        jsx('b', { children: agent.display_name }),
        jsx('span', { style: { color: 'var(--ui-text-tertiary, #9d93ad)' }, children: agent.role }),
        jsx('span', { style: { flex: 1 } }),
        jsxs('span', { style: { color: 'var(--ui-text-tertiary, #9d93ad)' }, children: [
          'Token ', nf(agent.tokens && agent.tokens.total), ' · $', ((agent.tokens && agent.tokens.cost_usd) || 0).toFixed(4),
          ' · 会话 ', nf(agent.tokens && agent.tokens.sessions),
        ] }),
        jsx('button', {
          type: 'button', onClick: onClose,
          style: { border: '1px solid var(--ui-border, #3a3147)', borderRadius: 6, padding: '1px 7px', background: 'transparent', color: 'inherit', cursor: 'pointer' },
          children: '收起',
        }),
      ] }),
      agent.current ? row('正在干', agent.current.title) : null,
      ...tasks.slice(0, 6).map(t => row('[' + t.status + ']', t.title + (t.created_by ? '（由 ' + t.created_by + ' 派）' : ''))),
      ...recs.slice(0, 4).map(r => row(shortT(r.at), r.title)),
      jsx('div', { style: { fontSize: 10.5, color: 'var(--ui-text-tertiary, #9d93ad)' }, children: '任务来自 kanban.db；工作记录来自它自己的 state.db（只读）' }),
    ],
  })
}

function Feed({ feed, avatars, agents }) {
  if (!feed || !feed.length) {
    return jsx('div', { style: { padding: 12, color: 'var(--ui-text-tertiary, #9d93ad)' }, children: '还没有互动记录。派个任务给员工，这里就会出现他们之间的交流。' })
  }
  const byName = {}
  ;(agents || []).forEach(a => { byName[a.name] = a })
  return jsxs('div', { style: { display: 'flex', flexDirection: 'column', gap: 6 }, children:
    feed.slice().reverse().map((m, i) => {
      const a = m.author ? byName[m.author] : null
      return jsxs('div', {
        style: { display: 'flex', gap: 8, alignItems: 'flex-start', border: '1px solid var(--ui-border, #3a3147)', borderRadius: 10, padding: 8 },
        children: [
          jsx(Face, { agent: a || { name: m.author || '?', display_name: (m.author || '系').slice(0, 1), exists: false, state: 'idle' }, avatars, size: 26 }),
          jsxs('div', { style: { minWidth: 0, flex: 1 }, children: [
            jsxs('div', { style: { display: 'flex', gap: 8, fontSize: 11, color: 'var(--ui-text-tertiary, #9d93ad)' }, children: [
              jsx('b', { style: { color: 'var(--ui-text, inherit)' }, children: a ? a.display_name : (m.author || '系统') }),
              jsx('span', { children: m.kind || '' }),
              jsx('span', { style: { flex: 1 } }),
              jsx('span', { children: shortT(m.at) }),
            ] }),
            m.text ? jsx('div', { style: { whiteSpace: 'pre-wrap', wordBreak: 'break-word' }, children: m.text }) : null,
            m.task ? jsx('div', { style: { color: 'var(--ui-text-tertiary, #9d93ad)', fontSize: 11 }, children: '📋 ' + m.task }) : null,
          ] }),
        ],
      }, i)
    }) })
}

function Stat({ label, value, sub }) {
  return jsxs('div', {
    style: { border: '1px solid var(--ui-border, #3a3147)', borderRadius: 10, padding: '6px 10px', display: 'flex', flexDirection: 'column' },
    children: [
      jsx('div', { style: { fontSize: 10.5, color: 'var(--ui-text-tertiary, #9d93ad)' }, children: label }),
      jsx('div', { style: { fontSize: 17, fontWeight: 700 }, children: value }),
      sub ? jsx('div', { style: { fontSize: 10.5, color: 'var(--ui-text-tertiary, #9d93ad)' }, children: sub }) : null,
    ],
  })
}

/* ------------------------------------------------------------------ 主面板 */

function OfficePanel() {
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
      style: { display: 'flex', flexDirection: 'column', gap: 8, alignItems: 'center', justifyContent: 'center', height: '100%', padding: 24, textAlign: 'center' },
      children: [
        jsx('div', { style: { fontSize: 14, fontWeight: 600 }, children: '🏢 插件后端没挂上' }),
        jsx('div', { style: { color: 'var(--ui-text-tertiary, #9d93ad)' }, children: error }),
        jsx('div', { style: { color: 'var(--ui-text-tertiary, #9d93ad)', fontSize: 11.5 }, children: '检查：Settings → Plugins 里「Hermes 办公室」是否启用；用户插件要同时进 config.yaml 的 plugins.enabled。' }),
        jsx('button', {
          type: 'button', onClick: refresh,
          style: { border: '1px solid var(--ui-border, #3a3147)', borderRadius: 8, padding: '5px 12px', background: 'transparent', color: 'inherit', cursor: 'pointer' },
          children: '重试',
        }),
      ],
    })
  }

  const tabBtn = (id, label) => jsx('button', {
    type: 'button', onClick: () => setTab(id),
    style: {
      borderRadius: 8, padding: '3px 10px', cursor: 'pointer',
      border: '1px solid ' + (tab === id ? 'var(--ui-accent, #ffd479)' : 'var(--ui-border, #3a3147)'),
      background: tab === id ? 'rgba(255,212,121,.12)' : 'transparent',
      color: tab === id ? 'var(--ui-text, inherit)' : 'var(--ui-text-tertiary, #9d93ad)',
    },
    children: label,
  })

  return jsxs('div', {
    style: { display: 'flex', flexDirection: 'column', gap: 10, padding: 12, height: '100%', overflow: 'auto' },
    children: [
      // 顶部横幅（公司名 / slogan 可改，存在插件目录的 agents.json 里）
      jsxs('div', { style: { display: 'flex', alignItems: 'center', gap: 10, flexWrap: 'wrap' }, children: [
        jsx('div', { style: { fontSize: 15, fontWeight: 700 }, children: '🏢 ' + (office.title || 'Hermes 办公室') }),
        office.slogan ? jsx('div', { style: { color: 'var(--ui-text-tertiary, #9d93ad)', fontSize: 12 }, children: office.slogan }) : null,
        jsx('span', { style: { flex: 1 } }),
        jsx('button', {
          type: 'button', onClick: refresh,
          style: { border: '1px solid var(--ui-border, #3a3147)', borderRadius: 8, padding: '4px 12px', background: 'transparent', color: 'inherit', cursor: 'pointer' },
          children: '刷新',
        }),
      ] }),
      jsxs('div', { style: { display: 'grid', gap: 8, gridTemplateColumns: 'repeat(auto-fit, minmax(120px, 1fr))' }, children: [
        jsx(Stat, { label: 'Token 总量', value: nf(totals.tokens_total) }),
        jsx(Stat, { label: '成本', value: '$' + (totals.cost_usd || 0).toFixed(4) }),
        jsx(Stat, { label: '在岗 / 完成', value: (totals.working || 0) + ' / ' + (totals.done || 0) }),
        jsx(Stat, { label: '工位 / 在编', value: (totals.seats || 0) + ' / ' + (totals.agents || 0) }),
      ] }),
      jsxs('div', { style: { display: 'flex', alignItems: 'center', gap: 8 }, children: [
        tabBtn('desks', '🪑 工位'),
        tabBtn('chat', '💬 聊天室'),
        jsx('span', { style: { flex: 1 } }),
        jsx('span', { style: { fontSize: 10.5, color: 'var(--ui-text-tertiary, #9d93ad)' }, children: updatedAt ? '更新于 ' + updatedAt.toLocaleTimeString('zh-CN', { hour12: false }) : '加载中…' }),
      ] }),
      tab === 'desks'
        ? jsxs('div', { style: { display: 'flex', flexDirection: 'column', gap: 10 }, children: [
            jsx(Room, {
              title: '👑 老板 · 📋 经理办公室',
              note: '点办公室 = 派活',
              tall: true,
              children: [boss, mgr].filter(Boolean).map(a => jsx(Desk, {
                key: a.name, agent: a, avatars, active: selected === a.name, onClick: () => setSelected(selected === a.name ? null : a.name),
              })),
            }),
            jsx(Room, {
              title: '开放工位区',
              note: `${staff.filter(a => a.exists).length} 人在编 / ${staff.length} 个工位`,
              children: staff.map(a => jsx(Desk, {
                key: a.name, agent: a, avatars, active: selected === a.name, onClick: () => setSelected(selected === a.name ? null : a.name),
              })),
            }),
            sel ? jsx(Detail, { agent: sel, avatars, onClose: () => setSelected(null) }) : null,
          ] })
        : jsx(Feed, { feed: data ? data.feed : [], avatars, agents }),
      jsx('div', { style: { fontSize: 10.5, color: 'var(--ui-text-tertiary, #9d93ad)' }, children: '数据：' + ((data && data.hermes_home) || '?') + ' · 只读（kanban.db + 各 profile 的 state.db）' }),
    ],
  })
}

/* ------------------------------------------------------------------ 状态栏 */

function OfficeChip() {
  const { data } = useOfficeData()
  const working = data ? ((data.totals && data.totals.working) || 0) : 0
  const tokens = data ? ((data.totals && data.totals.tokens_total) || 0) : 0
  return jsxs('button', {
    type: 'button',
    title: 'Hermes 办公室：' + (data ? (working + ' 人在岗 · ' + nf(tokens) + ' tok') : '加载中'),
    onClick: () => { if (SDK.haptic) SDK.haptic('tap'); host.navigate(PAGE_PATH) },
    style: { display: 'flex', alignItems: 'center', gap: 4, padding: '0 6px', fontSize: 11, color: 'var(--ui-text-tertiary, #9d93ad)', background: 'transparent', border: 'none', cursor: 'pointer' },
    children: [
      jsx('span', { style: { width: 6, height: 6, borderRadius: '50%', background: working ? '#4fd18b' : '#8a819e' } }),
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
      { id: 'pane', area: AREA.panes, title: 'office', data: { placement: 'right', width: '480px' }, render: () => jsx(OfficePanel, {}) },
      { id: 'page', area: AREA.routes, data: { path: PAGE_PATH }, render: () => jsx(OfficePanel, {}) },
      { id: 'nav', area: AREA.nav, data: { path: PAGE_PATH, label: 'Hermes 办公室', codicon: 'organization' } },
      { id: 'chip', area: AREA.statusRight, order: 140, render: () => jsx(OfficeChip, {}) },
      { id: 'open', area: AREA.palette, data: { id: 'hermes-office.open', label: '打开 Hermes 办公室', keywords: ['office', 'bangongshi', 'kanban', 'agent', '工位'], run: () => host.navigate(PAGE_PATH) } },
      { id: 'key', area: AREA.keybinds, data: { id: 'hermes-office.open.key', label: '打开 Hermes 办公室', category: 'Hermes 办公室', defaults: ['mod+shift+o'], run: () => host.navigate(PAGE_PATH) } },
    ])
  },
}
