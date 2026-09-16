// Hermes 办公室 · 桌面端面板 v4（原页面直出 = 与独立窗口版 100% 一致）
//
// 为什么这么做：v1~v3 都是"我照着独立窗口版重新实现一遍" → 只能近似，用户一眼就看出不一样。
// v4 换了思路：插件后端把独立窗口版那一页**原样**交给面板（/ui），面板用 iframe srcDoc 承载，
// 页面里的 fetch 由后端注入的 shim 改写路径 + 带上会话 token。于是：
//   · 视觉 == 独立窗口版（HTML/CSS/JS 一字未改）   · 不依赖 8123（数据来自插件自己的路由）
// 原生 React 场景（Face/Nameplate/Desk/Room…）保留为**兜底**：取不到页面时自动降级。
//
// SDK 硬规则：只能 import '@hermes/plugin-sdk' / 'react' / 'react/jsx-runtime'；
//            不能写 JSX 语法（用 jsx()/jsxs()）；用 import * as SDK 抗导出改名。
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

const ART = {
  wall: '#241d2f', wallLine: '#3a3048', wallLine2: '#1d1826',
  floorA: '#3a2f46', floorB: '#332a3e', room: '#2b2436', panel: '#251f30',
  card: 'linear-gradient(180deg,#2c2537,#251f30)', cardLine: '#3a3147',
  bubble: '#1d1727', line: '#3a3147',
  fg: '#efe9f5', muted: '#9d93ad', accent: '#ffd479',
}
const WOOD = { top: '#c08a5e', mid: '#a3714a', deep: '#8c5f3d', sub: '#4a3524' }
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

/* ------------------------------------------------------- 原页面（首选渲染路径） */

// 固定端口候选 —— 面板直接探这些端口，完全不依赖 ctx.rest
// （桌面端的 ctx.rest 打到 headless `hermes serve`，它按设计拒绝所有 web UI/插件 API 路径 → 404）
const PORT_CANDIDATES = [8142, 8143, 8144, 8150]

async function probeUiUrl() {
  // 1) 先问后端：某些配置下 ctx.rest 是通的（比如插件 API 挂在 dashboard 后端上时）
  try {
    if (CTX && CTX.rest) {
      const r = await CTX.rest('/ui-url')
      if (r && r.ok && r.url) return r.url
    }
  } catch (e) { /* headless 后端必然 404，属正常 */ }
  // 2) 固定端口自探：no-cors fetch 只关心"有没有 HTTP 响应"，不关心内容/CORS
  for (let i = 0; i < PORT_CANDIDATES.length; i++) {
    const base = 'http://127.0.0.1:' + PORT_CANDIDATES[i] + '/'
    try {
      await fetch(base + 'health', { mode: 'no-cors', cache: 'no-store' })
      return base
    } catch (e) { /* 换下一个端口 */ }
  }
  return ''
}

function useUiUrl() {
  const [url, setUrl] = useState('')
  const [err, setErr] = useState(null)
  const [busy, setBusy] = useState(true)
  const alive = useRef(true)

  const load = useCallback(async () => {
    setBusy(true)
    const u = await probeUiUrl()
    if (!alive.current) return
    setBusy(false)
    if (u) { setUrl(u); setErr(null) }
    else { setUrl(''); setErr('本地办公室服务没在监听（端口 ' + PORT_CANDIDATES.join('/') + ' 都没响应）') }
  }, [])

  useEffect(() => {
    alive.current = true
    load()
    return () => { alive.current = false }
  }, [load])

  return { url, err, busy, reload: load }
}

/* ------------------------------------------------- 兜底：原生场景（后端不可用时） */

function useOfficeData() {
  const [data, setData] = useState(null)
  const [avatars, setAvatars] = useState({})
  const [error, setError] = useState(null)
  const alive = useRef(true)

  const pull = useCallback(async () => {
    if (!CTX || !CTX.rest) { setError('ctx.rest 不可用（插件后端没挂载）'); return }
    try {
      const d = await CTX.rest('/office')
      if (alive.current) { setData(d); setError(null) }
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

  return { data, avatars, error, refresh: pull }
}

function Face({ agent, avatars, size = 46 }) {
  const src = agent && avatars[agent.avatar || agent.name]
  const st = !agent ? 'vacant' : (agent.human ? 'human' : (agent.exists ? (agent.state || 'idle') : 'vacant'))
  const ring = STATE_COLOR[st] || '#8a819e'
  return jsx('div', {
    style: {
      width: size, height: size, borderRadius: '50%', flex: `0 0 ${size}px`,
      background: src ? `url(${src}) center/cover no-repeat` : '#1b1622',
      border: `3px solid ${ring}`,
      boxShadow: st === 'working' ? `0 0 0 5px ${ring}22` : '0 4px 10px rgba(0,0,0,.45)',
      display: 'flex', alignItems: 'center', justifyContent: 'center',
      fontSize: Math.round(size * 0.4), color: ART.muted, fontWeight: 600,
      transform: st === 'blocked' ? 'rotate(-6deg)' : 'none',
      filter: st === 'vacant' ? 'grayscale(1) brightness(.7)' : 'none',
    },
    children: src ? null : ((agent && agent.display_name) ? agent.display_name.slice(0, 1) : '?'),
  })
}

function bubbleText(agent) {
  if (!agent) return ''
  if (agent.human) return '👑 点我派活给经理 →'
  if (!agent.exists) return '— 招人中 —'
  if (agent.current && agent.current.title) return '🔨 ' + agent.current.title
  if (agent.state === 'blocked') return '⚠️ 卡住了，需要处理'
  if (agent.last_activity) return '⚡ ' + agent.last_activity
  return '— 待命中 —'
}

function Nameplate({ agent }) {
  const st = !agent ? 'vacant' : (agent.human ? 'human' : (agent.exists ? (agent.state || 'idle') : 'vacant'))
  const done = (agent && agent.counts && agent.counts.done) || 0
  const tok = agent && agent.tokens ? agent.tokens.total : 0
  return jsxs('div', {
    style: {
      background: `linear-gradient(180deg, ${WOOD.top}, ${WOOD.mid} 45%, ${WOOD.deep})`,
      border: `1px solid ${WOOD.deep}`, borderRadius: 8, padding: '5px 9px',
      boxShadow: 'inset 0 1px 0 rgba(255,255,255,.22), 0 6px 12px -6px #000',
    },
    children: [
      jsxs('div', {
        style: { display: 'flex', alignItems: 'center', gap: 6, minWidth: 0 },
        children: [
          jsx('span', { style: { fontWeight: 700, fontSize: 13, color: '#fff6e8', whiteSpace: 'nowrap' }, children: agent ? agent.display_name : '招人中' }),
          jsx('span', { style: { width: 6, height: 6, borderRadius: '50%', background: STATE_COLOR[st] || '#8a819e', flex: '0 0 6px' } }),
          jsx('span', { style: { fontSize: 10.5, color: WOOD.sub, overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }, children: agent ? `${agent.role} · ${STATE_CN[st] || st}` : '—— 空岗 ——' }),
        ],
      }),
      jsxs('div', {
        style: { display: 'flex', justifyContent: 'space-between', fontSize: 10, color: WOOD.sub, marginTop: 2 },
        children: [
          jsx('span', { children: agent && agent.exists ? `完成 ${done}` : '' }),
          jsx('span', { children: agent && agent.exists ? `${nf(tok)} tok` : '' }),
        ],
      }),
    ],
  })
}

function Desk({ agent, avatars, onClick, active }) {
  const st = !agent ? 'vacant' : (agent.human ? 'human' : (agent.exists ? (agent.state || 'idle') : 'vacant'))
  const bub = bubbleText(agent)
  const hot = st === 'working'
  return jsxs('button', {
    type: 'button', onClick, title: bub,
    style: {
      display: 'flex', flexDirection: 'column', gap: 6, padding: '8px 9px', borderRadius: 12,
      background: ART.card,
      border: `1px solid ${active ? ART.accent : (hot ? 'rgba(79,209,139,.5)' : ART.cardLine)}`,
      cursor: 'pointer', textAlign: 'left', opacity: st === 'vacant' ? 0.78 : 1,
    },
    children: [
      jsx('div', {
        style: {
          fontSize: 10.5, lineHeight: 1.4, minHeight: 27, color: hot ? '#cdf7e3' : '#d9d2e6',
          background: ART.bubble, border: `1px solid ${hot ? 'rgba(79,209,139,.35)' : ART.line}`,
          borderRadius: 8, padding: '4px 7px', whiteSpace: 'nowrap', overflow: 'hidden', textOverflow: 'ellipsis',
        },
        children: bub,
      }),
      jsx('div', { style: { display: 'flex', justifyContent: 'center' }, children: jsx(Face, { agent, avatars }) }),
      jsx(Nameplate, { agent }),
    ],
  })
}

function Room({ title, note, children, tall }) {
  return jsxs('div', {
    style: {
      border: '1px solid rgba(255,255,255,.10)', borderRadius: 14,
      background: 'linear-gradient(180deg, rgba(255,255,255,.03), rgba(0,0,0,.22)), ' + ART.room,
      padding: 11, display: 'flex', flexDirection: 'column', gap: 9,
    },
    children: [
      jsxs('div', {
        style: { display: 'flex', alignItems: 'center', gap: 9, fontSize: 11, letterSpacing: 1.6, color: ART.muted },
        children: [
          jsx('span', { style: { background: 'rgba(255,212,121,.12)', border: '1px solid rgba(255,212,121,.34)', borderRadius: 6, padding: '3px 10px', color: ART.accent }, children: title }),
          note ? jsx('span', { style: { letterSpacing: 0, opacity: .85 }, children: note }) : null,
        ],
      }),
      jsx('div', {
        style: { display: 'grid', gap: 9, gridTemplateColumns: tall ? 'repeat(auto-fit, minmax(240px, 1fr))' : 'repeat(auto-fill, minmax(172px, 1fr))' },
        children,
      }),
    ],
  })
}

function Stat({ label, value }) {
  return jsxs('div', {
    style: { border: `1px solid ${ART.line}`, borderRadius: 10, padding: '7px 11px', background: ART.panel, color: ART.fg },
    children: [
      jsx('div', { style: { fontSize: 10.5, color: ART.muted }, children: label }),
      jsx('div', { style: { fontSize: 17, fontWeight: 700 }, children: value }),
    ],
  })
}

function NativeFallback({ message, onRetry }) {
  const { data, avatars } = useOfficeData()
  const agents = (data && data.agents) || []
  const totals = (data && data.totals) || {}
  const boss = agents.find(a => a.seat === 'boss')
  const mgr = agents.find(a => a.seat === 'manager')
  const staff = agents.filter(a => a.seat === 'staff')
  const scene = {
    minHeight: '100%', padding: '12px 14px 16px', color: ART.fg,
    backgroundImage: [
      `linear-gradient(180deg, ${ART.wall} 0 62px, ${ART.wallLine} 62px 74px, ${ART.wallLine2} 74px 76px, transparent 76px)`,
      `repeating-linear-gradient(90deg, ${ART.floorA} 0 46px, ${ART.floorB} 46px 92px)`,
    ].join(', '),
    backgroundColor: '#1a1622', display: 'flex', flexDirection: 'column', gap: 11,
  }
  return jsxs('div', {
    style: scene,
    children: [
      jsxs('div', { style: { display: 'flex', alignItems: 'center', gap: 10 }, children: [
        jsx('div', { style: { fontSize: 15, fontWeight: 700 }, children: '🏢 Hermes 办公室（原生兜底视图）' }),
        jsx('span', { style: { flex: 1 } }),
        jsx('button', {
          type: 'button', onClick: onRetry,
          style: { border: '1px solid rgba(255,255,255,.16)', borderRadius: 8, padding: '4px 12px', background: 'rgba(255,255,255,.06)', color: ART.fg, cursor: 'pointer' },
          children: '重试原页面',
        }),
      ] }),
      message ? jsx('div', { style: { color: '#ffb3b0', fontSize: 11.5 }, children: '原页面没取到：' + message + '（先用兜底视图；后端路由要重启一次桌面端才会挂载）' }) : null,
      jsxs('div', { style: { display: 'grid', gap: 9, gridTemplateColumns: 'repeat(auto-fit, minmax(126px, 1fr))' }, children: [
        jsx(Stat, { label: 'Token 总量', value: nf(totals.tokens_total) }),
        jsx(Stat, { label: '成本', value: '$' + (totals.cost_usd || 0).toFixed(4) }),
        jsx(Stat, { label: '在岗 / 完成', value: (totals.working || 0) + ' / ' + (totals.done || 0) }),
        jsx(Stat, { label: '工位 / 在编', value: (totals.seats || 0) + ' / ' + (totals.agents || 0) }),
      ] }),
      jsx(Room, {
        title: '👑 老板 · 📋 经理办公室', tall: true,
        children: [boss, mgr].filter(Boolean).map(a => jsx(Desk, { key: a.name, agent: a, avatars })),
      }),
      jsx(Room, {
        title: '开放工位区',
        note: `${staff.filter(a => a.exists).length} 人在编 / ${staff.length} 个工位`,
        children: staff.map(a => jsx(Desk, { key: a.name, agent: a, avatars })),
      }),
    ],
  })
}

/* ------------------------------------------------------------------ 主面板 */

function OfficePanel() {
  const { url, err, busy, reload } = useUiUrl()

  // 首选：插件自带的 UI 服务（就是独立窗口那一页本身，视觉 100% 一致）
  if (url) {
    return jsx('div', {
      style: { display: 'flex', flexDirection: 'column', height: '100%', minHeight: 0 },
      children: jsx('iframe', {
        title: 'Hermes 办公室',
        src: url,
        style: { flex: 1, minHeight: 0, width: '100%', border: 'none', background: 'transparent', display: 'block' },
      }),
    })
  }

  if (busy || !err) {
    return jsx('div', {
      style: { display: 'flex', alignItems: 'center', justifyContent: 'center', height: '100%', color: ART.muted, background: '#1a1622' },
      children: '正在启动办公室…',
    })
  }

  // 兜底：原生场景
  return jsx(NativeFallback, { message: err, onRetry: reload })
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
      { id: 'pane', area: AREA.panes, title: 'office', data: { placement: 'right', width: '560px' }, render: () => jsx(OfficePanel, {}) },
      { id: 'page', area: AREA.routes, data: { path: PAGE_PATH }, render: () => jsx(OfficePanel, {}) },
      { id: 'nav', area: AREA.nav, data: { path: PAGE_PATH, label: 'Hermes 办公室', codicon: 'organization' } },
      { id: 'chip', area: AREA.statusRight, order: 140, render: () => jsx(OfficeChip, {}) },
      { id: 'open', area: AREA.palette, data: { id: 'hermes-office.open', label: '打开 Hermes 办公室', keywords: ['office', 'bangongshi', 'kanban', 'agent', '工位'], run: () => host.navigate(PAGE_PATH) } },
      { id: 'key', area: AREA.keybinds, data: { id: 'hermes-office.open.key', label: '打开 Hermes 办公室', category: 'Hermes 办公室', defaults: ['mod+shift+o'], run: () => host.navigate(PAGE_PATH) } },
    ])
  },
}
