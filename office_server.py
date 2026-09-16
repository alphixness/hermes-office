#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Hermes 可视化办公室 · 后端（纯标准库，零依赖）

把 Hermes 本地数据汇总成一份 JSON，给工位视图页面轮询。三份原料：
  1) ~/.hermes/kanban.db                → 任务、状态、分派给谁（谁在干活）
  2) ~/.hermes/state.db                 → default 那个"你"的 token/成本/活动
  3) ~/.hermes/profiles/<name>/state.db → **每个 bot 自己的账本**（按工位分账的关键）
  4) ~/.hermes/profiles/*               → 有哪些"员工"

⚠️ 两个实测踩过的坑（教程重点，别踩）：
  - sessions.started_at / last_activity_at 是 **Unix 时间戳（REAL）**，不是日期字符串；
    拿 '2026-09-16' 去比会一行都匹配不到 → token 全 0。
  - 每个 profile 是**独立 Hermes home**，token 记在各自的 state.db 里，根 state.db 里
    只有 default 那个 agent 的账。想按工位分账必须逐个 profile 读。

设计：**全程只读**打开 SQLite（mode=ro），不写不锁，不影响正在跑的 Hermes。
用法：
    python office_server.py                 # http://127.0.0.1:8123
    python office_server.py --port 9000
    python office_server.py --days 7        # 统计窗口（默认今天）
"""
from __future__ import annotations

import argparse
import json
import os
import sqlite3
import sys
from datetime import datetime
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

# ----------------------------------------------------------------------------
# 路径与通用工具
# ----------------------------------------------------------------------------

def default_hermes_home() -> Path:
    """跨平台定位 Hermes 数据目录：HERMES_HOME → 问 hermes 自己 → 平台默认"""
    env = os.environ.get('HERMES_HOME')
    if env and Path(env).exists():
        return Path(env)
    try:
        import subprocess
        out = subprocess.run(['hermes', 'config', 'path'], capture_output=True,
                             text=True, timeout=10)
        if out.returncode == 0 and out.stdout.strip():
            cand = Path(out.stdout.strip()).parent
            if cand.exists():
                return cand
    except Exception:
        pass
    cands = [Path.home() / '.hermes']
    for var in ('LOCALAPPDATA', 'APPDATA'):
        if os.environ.get(var):
            cands.append(Path(os.environ[var]) / 'hermes')
    for c in cands:
        if c.exists():
            return c
    return cands[0]


HERMES_HOME = default_hermes_home()


def ro_connect(db_path: Path) -> sqlite3.Connection | None:
    if not db_path.exists():
        return None
    try:
        con = sqlite3.connect(f'file:{db_path.as_posix()}?mode=ro', uri=True, timeout=2.0)
        con.row_factory = sqlite3.Row
        return con
    except Exception:
        return None


def q(con, sql: str, args: tuple = ()) -> list:
    if con is None:
        return []
    try:
        return list(con.execute(sql, args))
    except Exception:
        return []


def cols_of(con, table: str) -> set[str]:
    return {r['name'] for r in q(con, f'PRAGMA table_info({table})')}


def has(columns: set[str], *names: str) -> str | None:
    for n in names:
        if n in columns:
            return n
    return None


def ts_to_iso(ts) -> str | None:
    """Unix 时间戳（REAL/INT，也可能是字符串）→ ISO 字符串"""
    if ts in (None, ''):
        return None
    try:
        return datetime.fromtimestamp(float(ts)).isoformat(timespec='seconds')
    except Exception:
        return str(ts)


def day_start_ts(days_back: int = 0) -> float:
    dt = datetime.now().replace(hour=0, minute=0, second=0, microsecond=0)
    return dt.timestamp() - days_back * 86400


# ----------------------------------------------------------------------------
# 员工（profiles）+ 看板
# ----------------------------------------------------------------------------

def profile_homes() -> dict[str, Path]:
    """agent 名 → 它的 Hermes home（根目录 = default）"""
    homes: dict[str, Path] = {'default': HERMES_HOME}
    pdir = HERMES_HOME / 'profiles'
    if pdir.is_dir():
        for p in sorted(pdir.iterdir()):
            if p.is_dir() and not p.name.startswith('.') and (p / 'state.db').exists():
                homes[p.name] = p
    return homes


STATUS_BUCKET = {
    'running': 'working', 'review': 'working',
    'ready': 'queued', 'todo': 'queued', 'triage': 'queued', 'scheduled': 'queued',
    'blocked': 'blocked',
    'done': 'done', 'archived': 'done',
}


def collect_kanban() -> dict:
    con = ro_connect(HERMES_HOME / 'kanban.db')
    tc = cols_of(con, 'tasks')
    empty = {'agents': {}, 'totals': {'running': 0, 'done': 0, 'blocked': 0,
                                      'queued': 0, 'other': 0, 'total': 0}}
    if not tc:
        return empty
    idc, titlec = has(tc, 'id') or 'id', has(tc, 'title') or 'title'
    asg, stc = has(tc, 'assignee'), has(tc, 'status') or 'status'
    started, done_at = has(tc, 'started_at'), has(tc, 'completed_at')
    upd = has(tc, 'updated_at', 'created_at')

    rows = q(con, f'SELECT {idc} id, {titlec} title, '
                  f'{asg or "NULL"} assignee, {stc} status, '
                  f'{started or "NULL"} started_at, {done_at or "NULL"} completed_at, '
                  f'{upd or "NULL"} updated_at FROM tasks')

    # 交流密度：每个任务的评论数 / 事件数 / 运行次数
    def count_by(table: str) -> dict[str, int]:
        c = cols_of(con, table)
        t = has(c, 'task_id')
        if not t:
            return {}
        return {str(r[0]): r[1] for r in q(con, f'SELECT {t}, COUNT(*) FROM {table} GROUP BY {t}')}

    cmt, evt, run = count_by('task_comments'), count_by('task_events'), count_by('task_runs')
    if con:
        con.close()

    agents: dict[str, dict] = {}
    totals = dict(empty['totals'])
    for r in rows:
        name = str(r['assignee'] or '(未指派)')
        st = (r['status'] or '').lower()
        bucket = STATUS_BUCKET.get(st, 'other')
        totals[bucket] = totals.get(bucket, 0) + 1
        totals['total'] += 1

        a = agents.setdefault(name, {
            'name': name, 'state': 'idle', 'current': None,
            'counts': {'running': 0, 'done': 0, 'blocked': 0, 'queued': 0, 'other': 0},
            'comments': 0, 'events': 0, 'runs': 0, 'tasks': [],
        })
        a['counts'][bucket] += 1
        a['comments'] += cmt.get(str(r['id']), 0)
        a['events'] += evt.get(str(r['id']), 0)
        a['runs'] += run.get(str(r['id']), 0)
        if bucket == 'working':
            a['state'] = 'working'
            a['current'] = {'id': str(r['id']), 'title': r['title'],
                            'started_at': ts_to_iso(r['started_at'])}
        elif bucket == 'queued' and a['state'] == 'idle':
            a['state'] = 'queued'
        elif bucket == 'blocked' and a['state'] in ('idle', 'queued'):
            a['state'] = 'blocked'
        a['tasks'].append({'id': str(r['id']), 'title': r['title'], 'status': st,
                           'bucket': bucket, 'updated_at': ts_to_iso(r['updated_at']),
                           'created_by': (r['created_by'] if 'created_by' in r.keys() else None)})
    for a in agents.values():
        a['tasks'] = sorted(a['tasks'], key=lambda t: t.get('updated_at') or '', reverse=True)[:8]
    return {'agents': agents, 'totals': totals}


# ----------------------------------------------------------------------------
# 会话账本（按 profile 读各自的 state.db）
# ----------------------------------------------------------------------------

def session_stats(home: Path, since_ts: float) -> dict | None:
    con = ro_connect(home / 'state.db')
    sc = cols_of(con, 'sessions')
    if not sc:
        if con:
            con.close()
        return None

    started = has(sc, 'started_at')
    tok_cols = [c for c in ('input_tokens', 'output_tokens', 'cache_read_tokens',
                            'cache_write_tokens', 'reasoning_tokens') if c in sc]
    cost_c = has(sc, 'estimated_cost_usd', 'actual_cost_usd')
    act_c = has(sc, 'last_activity_description')
    act_at = has(sc, 'last_activity_at', 'ended_at')

    where, args = ('', ())
    if started:                      # ⚠️ started_at 是 Unix 时间戳，必须用数值比较
        where, args = f'WHERE {started} >= ?', (since_ts,)

    sel = [f'sum(coalesce({c},0)) AS {c}' for c in tok_cols]
    sel.append(f'sum(coalesce({cost_c},0)) AS cost' if cost_c else '0 AS cost')
    sel.append('count(*) AS sessions')
    row = q(con, f'SELECT {", ".join(sel)} FROM sessions {where}', args)
    out = dict(row[0]) if row else {'sessions': 0, 'cost': 0}
    out['tokens_total'] = sum(int(out.get(c, 0) or 0) for c in tok_cols)

    # 最近在干什么（Hermes 现成字段）
    if act_c:
        r = q(con, f'SELECT {act_c} a, {act_at or "rowid"} t FROM sessions '
                   f'WHERE {act_c} IS NOT NULL AND {act_c} != "" '
                   f'ORDER BY {act_at or "rowid"} DESC LIMIT 1')
        out['last_activity'] = r[0]['a'] if r else None
        out['last_activity_at'] = ts_to_iso(r[0]['t']) if r else None

    # 该工位最近的工作记录（会话标题）
    title_c = has(sc, 'title')
    if title_c:
        order = act_at or started or 'rowid'
        recs = q(con, f'SELECT {title_c} title, {order} at, '
                      f'{has(sc, "message_count") or "0"} msgs, '
                      f'{cost_c or "0"} cost FROM sessions '
                      f'WHERE {title_c} IS NOT NULL AND {title_c} != "" '
                      f'ORDER BY {order} DESC LIMIT 6')
        out['recent'] = [{'title': r['title'], 'at': ts_to_iso(r['at']),
                          'messages': r['msgs'], 'cost_usd': round(float(r['cost'] or 0), 4)}
                         for r in recs]
    if con:
        con.close()
    return out


# ----------------------------------------------------------------------------
# 花名册（agents.json：用户可以在这里给员工改名/换岗/换头像提示词）
# ----------------------------------------------------------------------------

ROSTER_FILE = 'agents.json'


def load_roster() -> tuple[dict, str]:
    """读取花名册；返回 (按 id 索引的表, 共用风格)。读不到就返回空表，不影响主流程。"""
    f = HERE / ROSTER_FILE
    if not f.exists():
        return {}, ''
    try:
        cfg = json.loads(f.read_text(encoding='utf-8'))
        return {a['id']: a for a in cfg.get('agents', []) if a.get('id')}, cfg.get('STYLE', '')
    except Exception:
        return {}, ''


def avatar_url(agent_id: str) -> str | None:
    """优先用缩过的 256 图，其次原图；都没有返回 None"""
    for name in (f'avatars_256/{agent_id}.jpg', f'avatars/{agent_id}.png'):
        if (HERE / name).exists():
            return '/' + name
    return None


def collect_feed(limit: int = 60) -> list[dict]:
    """互动动态：kanban 评论 + 有意义的任务事件 + 任务运行（= 谁在跟谁说什么）"""
    con = ro_connect(HERMES_HOME / 'kanban.db')
    if not con:
        return []
    titles = {str(r['id']): r['title'] for r in q(con, 'SELECT id, title FROM tasks')}
    feeds: list[dict] = []

    if cols_of(con, 'task_comments'):
        for r in q(con, 'SELECT task_id, author, body, created_at FROM task_comments '
                        'ORDER BY rowid DESC LIMIT ?', (limit,)):
            feeds.append({'kind': 'comment', 'task_id': str(r['task_id']),
                          'task': titles.get(str(r['task_id']), ''),
                          'author': r['author'] or '?', 'role': 'comment',
                          'text': (r['body'] or '').strip(),
                          'at': ts_to_iso(r['created_at']), 'ts': float(r['created_at'] or 0)})

    if cols_of(con, 'task_events'):
        keep = {'completed', 'blocked', 'unblocked', 'gave_up',
                'review_requested', 'changes_requested'}   # 去掉 commented/created/claimed/spawned：
                                                           # 评论正文本身已单独成条，这几个只是重复噪音
        for r in q(con, 'SELECT task_id, kind, payload, created_at FROM task_events '
                        'ORDER BY rowid DESC LIMIT ?', (limit * 4,)):
            kind = str(r['kind'] or '')
            if kind not in keep:
                continue
            detail = ''
            if r['payload']:
                try:
                    p = json.loads(r['payload'])
                    detail = str(p.get('summary') or p.get('reason') or p.get('author') or '')
                except Exception:
                    detail = str(r['payload'])
            feeds.append({'kind': kind, 'task_id': str(r['task_id']),
                          'task': titles.get(str(r['task_id']), ''),
                          'author': None, 'role': kind, 'text': detail[:240],
                          'at': ts_to_iso(r['created_at']), 'ts': float(r['created_at'] or 0)})

    if cols_of(con, 'task_runs'):
        for r in q(con, 'SELECT task_id, profile, status, outcome, summary, started_at '
                        'FROM task_runs ORDER BY rowid DESC LIMIT ?', (limit,)):
            feeds.append({'kind': 'run', 'task_id': str(r['task_id']),
                          'task': titles.get(str(r['task_id']), ''),
                          'author': r['profile'], 'role': r['status'] or r['outcome'] or 'run',
                          'text': (r['summary'] or '')[:240],
                          'at': ts_to_iso(r['started_at']), 'ts': float(r['started_at'] or 0)})

    con.close()
    feeds.sort(key=lambda x: x.get('ts') or 0, reverse=True)
    for f in feeds:
        f.pop('ts', None)
    return feeds[:limit]


def assign_task(title: str, assignee: str, body: str = '') -> tuple[bool, str]:
    """派活：调用官方 CLI `hermes kanban create`（不直接写数据库，最安全）"""
    import shutil
    import subprocess
    title, assignee, body = (title or '').strip(), (assignee or '').strip(), (body or '').strip()
    if not title or not assignee:
        return False, '标题和负责人不能为空'
    if len(title) > 200 or len(body) > 2000:
        return False, '内容过长（标题 ≤200 字，说明 ≤2000 字）'
    exe = shutil.which('hermes') or 'hermes'
    cmd = [exe, 'kanban', 'create', title, '--assignee', assignee] + (['--body', body] if body else [])
    try:
        r = subprocess.run(cmd, capture_output=True, text=True, timeout=90,
                           encoding='utf-8', errors='replace')
    except Exception as e:
        return False, f'{type(e).__name__}: {e}'
    out = ((r.stdout or '') + (r.stderr or '')).strip()
    if r.returncode != 0:
        return False, out[:400] or f'退出码 {r.returncode}'
    return True, out[:400] or '已派活'


def load_office_cfg() -> dict:
    """顶部横幅配置（公司名 / slogan）：存在 agents.json 的 OFFICE 段里，用户可在界面里改"""
    f = HERE / ROSTER_FILE
    default = {'title': 'Hermes 办公室', 'slogan': '我派活 · 经理分派 · 员工执行'}
    if not f.exists():
        return default
    try:
        cfg = json.loads(f.read_text(encoding='utf-8')).get('OFFICE') or {}
        return {**default, **cfg}
    except Exception:
        return default


def save_office_cfg(title: str, slogan: str) -> tuple[bool, str]:
    f = HERE / ROSTER_FILE
    try:
        cfg = json.loads(f.read_text(encoding='utf-8')) if f.exists() else {'agents': []}
        cfg['OFFICE'] = {'title': (title or '').strip()[:60] or 'Hermes 办公室',
                         'slogan': (slogan or '').strip()[:120]}
        f.write_text(json.dumps(cfg, ensure_ascii=False, indent=2), encoding='utf-8')
        return True, '已保存'
    except Exception as e:
        return False, f'{type(e).__name__}: {e}'


CHAT_FILE = 'chat.json'


def chat_targets() -> list[tuple[str, str]]:
    """@ 可选对象：[(显示名, profile 名)]，包含花名册名字、id 和所有真实 profile"""
    roster, _ = load_roster()
    pairs: list[tuple[str, str]] = []
    for rid, r in roster.items():
        if r.get('human'):
            continue
        prof = r.get('bind_profile') or rid
        pairs.append((r.get('name') or rid, prof))
        pairs.append((rid, prof))
    for name in profile_homes():
        pairs.append((name, name))
    seen, out = set(), []
    for disp, prof in pairs:
        if disp and disp not in seen:
            seen.add(disp)
            out.append((disp, prof))
    return out


def manager_profile() -> str:
    """没写 @ 时默认派给谁：花名册里 seat=manager 绑的那个 profile（默认 profile，也就是主 Agent）"""
    roster, _ = load_roster()
    for rid, r in roster.items():
        if r.get('seat') == 'manager':
            return r.get('bind_profile') or rid
    return 'default'


def resolve_mention(text: str) -> tuple[str | None, str | None]:
    """从文本里解析 @某人 → (profile, 显示名)。取最长的匹配，避免 @林 命中 @林诀。"""
    best: tuple[str, str] | None = None
    for disp, prof in chat_targets():
        if f'@{disp}' in text and (best is None or len(disp) > len(best[1])):
            best = (prof, disp)
    return best if best else (None, None)


def strip_mention(text: str, disp: str | None) -> str:
    if not disp:
        return text
    out = text.replace(f'@{disp}', ' ')
    for ch in ('，', '。', ',', '.', '：', ':', '、', '!', '！'):
        out = out.replace(f'@ {ch}', ch)
    return ' '.join(out.split()).strip(' -—·:：,，')


def load_chat() -> list[dict]:
    f = HERE / CHAT_FILE
    if not f.exists():
        return []
    try:
        data = json.loads(f.read_text(encoding='utf-8'))
        return data if isinstance(data, list) else []
    except Exception:
        return []


def append_chat(text: str, assignee: str, assignee_name: str,
                task_id: str | None = None, ok: bool = True) -> dict:
    f = HERE / CHAT_FILE
    log = load_chat()
    rec = {'at': datetime.now().isoformat(timespec='seconds'),
           'author': 'boss', 'text': text, 'assignee': assignee,
           'assignee_name': assignee_name, 'task_id': task_id, 'ok': ok}
    log.append(rec)
    try:
        f.write_text(json.dumps(log[-500:], ensure_ascii=False, indent=2), encoding='utf-8')
    except Exception:
        pass
    return rec


def chat_stream(limit: int = 80) -> list[dict]:
    """聊天室时间线 = 老板的留言（本地 chat.json）+ 员工之间的动态（kanban）"""
    roster, _ = load_roster()
    boss_name = next((r.get('name') for r in roster.values() if r.get('human')), '老板')
    by_prof = {prof: disp for disp, prof in chat_targets()}
    msgs: list[dict] = []

    for m in load_chat():
        m = dict(m)
        m['who'] = 'boss'
        m['name'] = boss_name
        msgs.append(m)

    for f in collect_feed(limit):
        author = f.get('author')
        msgs.append({'at': f.get('at'), 'who': 'bot', 'author': author,
                     'name': by_prof.get(author, author) or '系统',
                     'kind': f.get('kind'), 'role': f.get('role'),
                     'text': f.get('text') or '', 'task': f.get('task') or '',
                     'task_id': f.get('task_id')})
    msgs.sort(key=lambda x: (x.get('at') or ''))
    return msgs[-limit:]


# ----------------------------------------------------------------------------
# 汇总
# ----------------------------------------------------------------------------

def build_office(days_back: int = 0) -> dict:
    since = day_start_ts(days_back)
    kb = collect_kanban()
    homes = profile_homes()
    roster, _style = load_roster()

    # 工位集合 = 花名册里绑定的 profile ∪ 实际存在的 profile ∪ 看板里出现过的名字
    bound: dict[str, dict] = {}          # profile 名 → 花名册条目
    for rid, r in roster.items():
        p = r.get('bind_profile') or rid
        bound[p] = r

    names = sorted(set(bound) | set(homes) | set(kb['agents']))
    agents = []
    for name in names:
        home = homes.get(name)                      # 没有对应 profile 的空岗：不读账本（否则会误读 root 的账，导致重复计数）
        kb_a = kb['agents'].get(name, {})
        st = session_stats(home, since) if home else {}
        r = bound.get(name, {})
        human = bool(r.get('human'))          # 老板（用户本人）不是 Hermes profile，不读账本
        exists = human or name in homes or name in kb['agents']
        seat = r.get('seat') or ('manager' if name == 'manager' else
                                 'boss' if name in ('default', 'boss') else 'staff')
        agents.append({
            'name': name,
            'seat': seat,                               # boss / manager / staff → 前端决定放哪个房间
            'human': human,
            'display_name': r.get('name') or name,      # ← 用户取的名字
            'role': r.get('role') or ('在编' if exists else '空岗'),
            'gender': r.get('gender'),
            'avatar': avatar_url(r.get('avatar') or name),
            'exists': exists,
            'state': 'human' if human else kb_a.get('state', 'idle'),
            'current': kb_a.get('current'),
            'counts': kb_a.get('counts', {'running': 0, 'done': 0, 'blocked': 0,
                                          'queued': 0, 'other': 0}),
            'comments': kb_a.get('comments', 0),
            'events': kb_a.get('events', 0),
            'runs': kb_a.get('runs', 0),
            'tasks': kb_a.get('tasks', []),
            'tokens': {
                'total': int(st.get('tokens_total', 0) or 0),
                'input': int(st.get('input_tokens', 0) or 0),
                'output': int(st.get('output_tokens', 0) or 0),
                'cache_read': int(st.get('cache_read_tokens', 0) or 0),
                'cost_usd': round(float(st.get('cost', 0) or 0), 4),
                'sessions': int(st.get('sessions', 0) or 0),
            },
            'last_activity': st.get('last_activity'),
            'last_activity_at': st.get('last_activity_at'),
            'recent': st.get('recent', []),
        })

    # 排序：经理单独一个工位，其余按"在干活 > 卡住 > 排队 > 空闲 > 空岗"
    order = {'working': 0, 'blocked': 1, 'queued': 2, 'idle': 3, 'done': 4}
    agents.sort(key=lambda x: (x['role'] != '经理', order.get(x['state'], 9), x['display_name']))

    totals = dict(kb['totals'])
    totals.update({
        'agents': sum(1 for a in agents if a['exists']),
        'seats': len(agents),
        'tokens_total': sum(a['tokens']['total'] for a in agents),
        'cost_usd': round(sum(a['tokens']['cost_usd'] for a in agents), 4),
        'working': sum(1 for a in agents if a['state'] == 'working'),
    })
    return {'generated_at': datetime.now().isoformat(timespec='seconds'),
            'hermes_home': str(HERMES_HOME),
            'window': '今天' if days_back == 0 else f'最近 {days_back + 1} 天',
            'totals': totals, 'agents': agents, 'feed': collect_feed(60),
            'chat': chat_stream(80), 'office': load_office_cfg()}


# ----------------------------------------------------------------------------
# HTTP
# ----------------------------------------------------------------------------

HERE = Path(__file__).resolve().parent
WINDOW_DAYS = 0


class Handler(BaseHTTPRequestHandler):
    server_version = 'HermesOffice/1.0'

    def log_message(self, *a):
        pass

    def _send(self, code, body: bytes, ctype: str):
        self.send_response(code)
        self.send_header('Content-Type', ctype)
        self.send_header('Content-Length', str(len(body)))
        self.send_header('Cache-Control', 'no-store')
        self.end_headers()
        try:
            self.wfile.write(body)
        except Exception:
            pass

    def do_GET(self):
        path = self.path.split('?')[0]
        try:
            if path in ('/', '/index.html'):
                self._send(200, (HERE / 'index.html').read_bytes(), 'text/html; charset=utf-8')
            elif path == '/api/office':
                self._send(200, json.dumps(build_office(WINDOW_DAYS), ensure_ascii=False)
                           .encode('utf-8'), 'application/json; charset=utf-8')
            elif path == '/health':
                self._send(200, b'ok', 'text/plain; charset=utf-8')
            elif path.startswith('/avatars') or path in ('/agents.json', '/avatar_sheet.jpg'):
                self._send_static(path)
            else:
                self._send(404, b'not found', 'text/plain; charset=utf-8')
        except Exception as e:
            self._send(500, json.dumps({'error': f'{type(e).__name__}: {e}'}).encode(),
                       'application/json; charset=utf-8')

    def do_POST(self):
        """写操作：派活 / 保存顶部横幅（都走受控路径）"""
        path = self.path.split('?')[0]
        try:
            n = int(self.headers.get('Content-Length') or 0)
            raw = self.rfile.read(n).decode('utf-8')
            data = json.loads(raw) if raw.strip() else {}
            if not isinstance(data, dict):
                raise ValueError('body 必须是 JSON 对象')
        except Exception as e:
            self._send(400, json.dumps({'ok': False, 'message': f'请求体解析失败（需要 UTF-8 JSON）：{e}'},
                                       ensure_ascii=False).encode('utf-8'),
                       'application/json; charset=utf-8')
            return
        if path == '/api/banner':
            ok, msg = save_office_cfg(data.get('title', ''), data.get('slogan', ''))
            self._send(200 if ok else 400,
                       json.dumps({'ok': ok, 'message': msg}, ensure_ascii=False).encode('utf-8'),
                       'application/json; charset=utf-8')
            return
        if path == '/api/chat':
            text = (data.get('text') or '').strip()
            if not text:
                self._send(400, json.dumps({'ok': False, 'message': '内容不能为空'},
                                           ensure_ascii=False).encode('utf-8'),
                           'application/json; charset=utf-8')
                return
            text = text[:600]
            prof, disp = resolve_mention(text)                 # @某人 → 派给他
            if not prof:
                prof = manager_profile()                       # 没 @ → 派给经理（主 Agent）
                disp = next((d for d, p in chat_targets() if p == prof), prof)
            title = strip_mention(text, disp)[:200] or text[:200]
            ok, out = assign_task(title, prof, body=f'来自办公室聊天窗口（老板留言：{text}）')
            task_id = None
            m = out or ''
            for tok in m.replace('\n', ' ').split():
                if tok.startswith('t_'):
                    task_id = tok.strip('.,;)')
                    break
            append_chat(text, prof, disp, task_id, ok)
            self._send(200 if ok else 400,
                       json.dumps({'ok': ok, 'message': out, 'assignee': prof,
                                   'assignee_name': disp, 'task_id': task_id},
                                  ensure_ascii=False).encode('utf-8'),
                       'application/json; charset=utf-8')
            return
        if path != '/api/assign':
            self._send(404, b'not found', 'text/plain; charset=utf-8')
            return
        try:
            ok, msg = assign_task(data.get('title', ''), data.get('assignee', ''),
                                  data.get('body', ''))
            body = json.dumps({'ok': ok, 'message': msg}, ensure_ascii=False).encode('utf-8')
            self._send(200 if ok else 400, body, 'application/json; charset=utf-8')
        except Exception as e:
            self._send(500, json.dumps({'ok': False, 'message': f'{type(e).__name__}: {e}'},
                                       ensure_ascii=False).encode('utf-8'),
                       'application/json; charset=utf-8')

    def _send_static(self, path: str):
        """只允许读办公室目录下、白名单后缀的文件（防目录穿越）"""
        rel = path.lstrip('/')
        target = (HERE / rel).resolve()
        if not str(target).startswith(str(HERE.resolve())) or not target.is_file():
            self._send(404, b'not found', 'text/plain; charset=utf-8')
            return
        ext = target.suffix.lower()
        ctype = {'.png': 'image/png', '.jpg': 'image/jpeg', '.jpeg': 'image/jpeg',
                 '.json': 'application/json; charset=utf-8',
                 '.html': 'text/html; charset=utf-8'}.get(ext)
        if not ctype:
            self._send(403, b'forbidden', 'text/plain; charset=utf-8')
            return
        self._send(200, target.read_bytes(), ctype)


def main() -> int:
    global HERMES_HOME, WINDOW_DAYS
    ap = argparse.ArgumentParser(description='Hermes 可视化办公室（只读）')
    ap.add_argument('--port', type=int, default=8123)
    ap.add_argument('--host', default='127.0.0.1')
    ap.add_argument('--hermes-home', default=None)
    ap.add_argument('--days', type=int, default=7,
                    help='统计窗口：7=最近 8 天（默认），0=只看今天')
    args = ap.parse_args()
    if args.hermes_home:
        HERMES_HOME = Path(args.hermes_home)
    WINDOW_DAYS = args.days

    homes = profile_homes()
    print(f'Hermes 数据目录 : {HERMES_HOME}')
    print(f'  看板 kanban.db : {"✅" if (HERMES_HOME / "kanban.db").exists() else "❌ 未找到 → 先跑 hermes kanban init"}')
    print(f'  员工 profiles  : {len(homes) - 1} 个 → {", ".join(n for n in homes if n != "default") or "（还没有，先 hermes profile create <名字>）"}')
    srv = ThreadingHTTPServer((args.host, args.port), Handler)
    print(f'\n🏢 办公室已开门 → http://{args.host}:{args.port}\n   按 Ctrl+C 关闭\n')
    try:
        srv.serve_forever()
    except KeyboardInterrupt:
        print('\n已关闭。')
    return 0


if __name__ == '__main__':
    sys.exit(main())
