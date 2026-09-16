"""Hermes 办公室 · 插件后端

挂在 /api/plugins/hermes-office/ 下，由 gateway 提供（**不需要另外跑任何服务**）。
全部只读：kanban.db 与各 profile 的 state.db 都用 `mode=ro` 打开。

数据来源
  · 工位/任务   ← <HERMES_HOME>/kanban.db   (tasks / task_comments / task_events / task_runs)
  · Token/成本  ← <HERMES_HOME>/profiles/<名>/state.db  (sessions，逐 profile 分账)
  · 花名册      ← 本插件目录下的 agents.json（用户可改名/岗位/头像）

路径解析优先问 `hermes_cli.kanban_db.kanban_db_path()`（跟着 HERMES_HOME/多板走），
失败再退回环境变量与平台默认目录。
"""
from __future__ import annotations

import base64
import json
import os
import sqlite3
from datetime import datetime, timedelta
from pathlib import Path

from fastapi import APIRouter, Depends, Response

try:
    from hermes_cli import kanban_db  # gateway 自带；拿它定位数据目录最稳
except Exception:  # pragma: no cover - 极端情况下退回环境变量
    kanban_db = None

CORS_HEADERS = {
    "Access-Control-Allow-Origin": "*",
    "Access-Control-Allow-Headers": "*, X-Hermes-Session-Token, Authorization, Content-Type",
    "Access-Control-Allow-Methods": "GET, POST, OPTIONS",
    "Access-Control-Max-Age": "600",
}


def _cors(response: Response) -> None:
    """面板用 srcDoc 渲染原页面 → 那是个不透明源，所有请求都算跨源，必须放行。

    放行不等于放宽鉴权：这些路由仍然要求会话 token（ctx.rest 和注入的 shim 都会带上）。
    """
    for k, v in CORS_HEADERS.items():
        response.headers[k] = v


router = APIRouter(dependencies=[Depends(_cors)])
HERE = Path(__file__).resolve().parent          # <plugin>/dashboard
PLUGIN_DIR = HERE.parent                        # <plugin>
ROSTER_FILE = PLUGIN_DIR / "agents.json"
CHAT_FILE = PLUGIN_DIR / "chat.json"            # 老板的留言（插件自己记，和 kanban 的 feed 合并展示）
AVATAR_DIR = PLUGIN_DIR / "avatars_256"

FEED_LIMIT = 60


# --------------------------------------------------------------------- 基础工具

def hermes_home() -> Path:
    if kanban_db is not None:
        try:
            return Path(kanban_db.kanban_db_path()).parent
        except Exception:
            pass
    env = os.environ.get("HERMES_HOME")
    if env:
        return Path(env)
    if os.name == "nt":
        base = os.environ.get("LOCALAPPDATA") or (Path.home() / "AppData" / "Local")
        return Path(base) / "hermes"
    return Path.home() / ".hermes"


def ro(path: Path) -> sqlite3.Connection | None:
    if not path.exists():
        return None
    try:
        con = sqlite3.connect(f"file:{path}?mode=ro", uri=True, timeout=5)
        con.row_factory = sqlite3.Row
        return con
    except Exception:
        return None


def q(con: sqlite3.Connection | None, sql: str, args: tuple = ()) -> list:
    if con is None:
        return []
    try:
        return list(con.execute(sql, args))
    except Exception:
        return []


def cols(con: sqlite3.Connection | None, table: str) -> set[str]:
    return {r["name"] for r in q(con, f"PRAGMA table_info({table})")}


def iso(ts) -> str | None:
    """kanban 的时间戳是 Unix 秒；sessions.started_at 也是。统一转 ISO。"""
    if ts in (None, "", 0):
        return None
    try:
        return datetime.fromtimestamp(float(ts)).isoformat(timespec="seconds")
    except Exception:
        return str(ts)


def num(v, default=0):
    try:
        return int(float(v))
    except Exception:
        return default


# --------------------------------------------------------------------- 花名册

def load_roster() -> tuple[dict, dict]:
    default_office = {"title": "Hermes 办公室", "slogan": "我派活 → 经理分派 → 员工执行"}
    if not ROSTER_FILE.exists():
        return {}, default_office
    try:
        cfg = json.loads(ROSTER_FILE.read_text(encoding="utf-8"))
        agents = {a["id"]: a for a in cfg.get("agents", []) if a.get("id")}
        return agents, {**default_office, **(cfg.get("OFFICE") or {})}
    except Exception:
        return {}, default_office


def profile_homes() -> dict[str, Path]:
    """{'default': <home>, 'coder': <home>/profiles/coder, ...}"""
    home = hermes_home()
    out = {"default": home}
    pdir = home / "profiles"
    if pdir.is_dir():
        for d in sorted(pdir.iterdir()):
            if d.is_dir() and (d / "state.db").exists():
                out[d.name] = d
    return out


# ------------------------------------------------------- 老板留言（chat.json）

def load_chat() -> list[dict]:
    if not CHAT_FILE.exists():
        return []
    try:
        data = json.loads(CHAT_FILE.read_text(encoding="utf-8"))
        return data if isinstance(data, list) else []
    except Exception:
        return []


def append_chat(text: str, assignee: str, assignee_name: str,
                task_id: str | None = None, ok: bool = True) -> dict:
    rec = {"at": datetime.now().isoformat(timespec="seconds"), "author": "boss",
           "text": text, "assignee": assignee, "assignee_name": assignee_name,
           "task_id": task_id, "ok": ok}
    log = load_chat()
    log.append(rec)
    try:
        CHAT_FILE.write_text(json.dumps(log[-500:], ensure_ascii=False, indent=2), encoding="utf-8")
    except Exception:
        pass
    return rec


def chat_targets() -> list[tuple[str, str]]:
    """@ 可选对象：[(显示名, profile)]，含花名册名字、id 与真实 profile"""
    roster, _ = load_roster()
    pairs: list[tuple[str, str]] = []
    for rid, r in roster.items():
        if r.get("human"):
            continue
        prof = r.get("bind_profile") or rid
        pairs.append((r.get("name") or rid, prof))
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
    roster, _ = load_roster()
    for rid, r in roster.items():
        if r.get("seat") == "manager":
            return r.get("bind_profile") or rid
    return "default"


def resolve_mention(text: str) -> tuple[str | None, str | None]:
    """@某人 → (profile, 显示名)；取最长匹配，避免 @林 命中 @林诀"""
    best = None
    for disp, prof in chat_targets():
        if f"@{disp}" in text and (best is None or len(disp) > len(best[1])):
            best = (prof, disp)
    return best if best else (None, None)


def strip_mention(text: str, disp: str | None) -> str:
    if not disp:
        return text
    out = text.replace(f"@{disp}", " ")
    for ch in ("，", "。", ",", ".", "：", ":", "、", "!", "！"):
        out = out.replace(f"@ {ch}", ch)
    return " ".join(out.split()).strip(" -—·:：,，")


def assign_task(title: str, assignee: str, body: str = "") -> tuple[bool, str]:
    """派活：调官方 CLI（不直接写库），和独立窗口版同一路径"""
    import shutil
    import subprocess
    title, assignee, body = (title or "").strip(), (assignee or "").strip(), (body or "").strip()
    if not title or not assignee:
        return False, "标题和负责人不能为空"
    if len(title) > 200 or len(body) > 2000:
        return False, "内容过长（标题 ≤200 字，说明 ≤2000 字）"
    exe = shutil.which("hermes") or "hermes"
    cmd = [exe, "kanban", "create", title, "--assignee", assignee] + (["--body", body] if body else [])
    try:
        r = subprocess.run(cmd, capture_output=True, text=True, timeout=90,
                           encoding="utf-8", errors="replace")
    except Exception as e:
        return False, f"{type(e).__name__}: {e}"
    out = ((r.stdout or "") + (r.stderr or "")).strip()
    if r.returncode != 0:
        return False, out[:400] or f"退出码 {r.returncode}"
    return True, out[:400] or "已派活"


# --------------------------------------------------------------------- 看板

def collect_kanban() -> tuple[dict, dict]:
    home = hermes_home()
    con = ro(home / "kanban.db")
    if con is None:
        return {"agents": {}, "totals": {}}, {}
    tc = cols(con, "tasks")
    if not tc:
        con.close()
        return {"agents": {}, "totals": {}}, {}

    ts_col = "updated_at" if "updated_at" in tc else ("created_at" if "created_at" in tc else "rowid")
    rows = q(con, f"SELECT * FROM tasks ORDER BY {ts_col} DESC")
    titles = {str(r["id"]): r["title"] for r in rows}

    agents: dict[str, dict] = {}
    totals = {"seats": 0, "done": 0, "running": 0, "blocked": 0, "queued": 0, "todo": 0, "tasks": 0}
    for r in rows:
        who = r["assignee"] or "未指派"
        st = str(r["status"] or "todo")
        bucket = ("working" if st in ("running", "in_progress", "executing")
                  else "done" if st in ("done", "completed", "archived")
                  else "blocked" if st in ("blocked", "failed", "error")
                  else "queued" if st in ("ready", "queued", "assigned", "claimed")
                  else "todo")
        a = agents.setdefault(who, {"state": "idle", "current": None, "counts": {}, "tasks": []})
        a["counts"][bucket] = a["counts"].get(bucket, 0) + 1
        if bucket == "working":
            a["state"] = "working"
            a["current"] = {"id": str(r["id"]), "title": r["title"], "started_at": iso(r["started_at"] if "started_at" in tc else None)}
        elif bucket == "blocked" and a["state"] == "idle":
            a["state"] = "blocked"
        elif bucket == "queued" and a["state"] == "idle":
            a["state"] = "queued"
        a["tasks"].append({"id": str(r["id"]), "title": r["title"], "status": st, "bucket": bucket,
                           "created_by": (r["created_by"] if "created_by" in tc else None),
                           "updated_at": iso(r[ts_col] if ts_col != "rowid" else None)})
        totals["tasks"] += 1
        totals[bucket if bucket in ("done", "blocked") else "running" if bucket == "working" else "queued"] += 1

    # 评论 / 事件 / 运行：聊天室的数据源
    feed: list[dict] = []
    if cols(con, "task_comments"):
        for r in q(con, "SELECT task_id, author, body, created_at FROM task_comments ORDER BY rowid DESC LIMIT ?", (FEED_LIMIT,)):
            feed.append({"kind": "comment", "task_id": str(r["task_id"]), "task": titles.get(str(r["task_id"]), ""),
                         "author": r["author"] or "?", "text": (r["body"] or "").strip(), "at": iso(r["created_at"])})
    if cols(con, "task_events"):
        keep = {"completed", "blocked", "unblocked", "gave_up", "review_requested", "changes_requested"}
        for r in q(con, "SELECT task_id, kind, payload, created_at FROM task_events ORDER BY rowid DESC LIMIT ?", (FEED_LIMIT * 4,)):
            kind = str(r["kind"] or "")
            if kind not in keep:
                continue
            detail = ""
            if r["payload"]:
                try:
                    p = json.loads(r["payload"])
                    detail = str(p.get("summary") or p.get("reason") or "")
                except Exception:
                    detail = str(r["payload"])
            feed.append({"kind": kind, "task_id": str(r["task_id"]), "task": titles.get(str(r["task_id"]), ""),
                         "author": None, "text": detail[:240], "at": iso(r["created_at"])})
    if cols(con, "task_runs"):
        for r in q(con, "SELECT task_id, profile, status, outcome, summary, started_at FROM task_runs ORDER BY rowid DESC LIMIT ?", (FEED_LIMIT,)):
            feed.append({"kind": "run", "task_id": str(r["task_id"]), "task": titles.get(str(r["task_id"]), ""),
                         "author": r["profile"], "role": r["status"] or r["outcome"] or "run",
                         "text": (r["summary"] or "")[:240], "at": iso(r["started_at"])})

    con.close()
    feed.sort(key=lambda x: x.get("at") or "")
    return {"agents": agents, "totals": totals}, {"feed": feed[-FEED_LIMIT:]}


# --------------------------------------------------------------------- Token 分账

def session_stats(home: Path, since_ts: float) -> dict:
    con = ro(home / "state.db")
    sc = cols(con, "sessions")
    if not sc:
        if con:
            con.close()
        return {}
    started = "started_at" if "started_at" in sc else None
    tok_cols = [c for c in ("input_tokens", "output_tokens", "cache_read_tokens",
                            "cache_write_tokens", "reasoning_tokens") if c in sc]
    cost_c = "estimated_cost_usd" if "estimated_cost_usd" in sc else ("actual_cost_usd" if "actual_cost_usd" in sc else None)
    act_c = "last_activity_description" if "last_activity_description" in sc else None
    act_at = "last_activity_at" if "last_activity_at" in sc else ("ended_at" if "ended_at" in sc else None)

    where, args = ("", ())
    if started:                       # ⚠️ 是 Unix 时间戳，不能拿日期串比
        where, args = f"WHERE {started} >= ?", (since_ts,)

    sel = [f"sum(coalesce({c},0)) AS {c}" for c in tok_cols]
    sel.append(f"sum(coalesce({cost_c},0)) AS cost" if cost_c else "0 AS cost")
    sel.append("count(*) AS sessions")
    row = q(con, f"SELECT {', '.join(sel)} FROM sessions {where}", args)
    out = dict(row[0]) if row else {}
    out["tokens_total"] = sum(num(out.get(c)) for c in tok_cols)
    out["cost"] = float(out.get("cost") or 0)
    out["sessions"] = num(out.get("sessions"))

    if act_c:
        r = q(con, f"SELECT {act_c} a, {act_at or 'rowid'} t FROM sessions "
                   f"WHERE {act_c} IS NOT NULL AND {act_c} != '' ORDER BY {act_at or 'rowid'} DESC LIMIT 1")
        if r:
            out["last_activity"] = r[0]["a"]
            out["last_activity_at"] = iso(r[0]["t"])
    if "title" in sc:
        order = act_at or started or "rowid"
        recs = q(con, f"SELECT title, {order} at FROM sessions WHERE title IS NOT NULL AND title != '' "
                      f"ORDER BY {order} DESC LIMIT 5")
        out["recent"] = [{"title": r["title"], "at": iso(r["at"])} for r in recs]
    con.close()
    return out


def build(days: int = 8) -> dict:
    since = (datetime.now() - timedelta(days=max(0, days - 1))).replace(hour=0, minute=0, second=0, microsecond=0).timestamp()
    kb, extra = collect_kanban()
    homes = profile_homes()
    roster, office_cfg = load_roster()

    bound: dict[str, dict] = {}
    for rid, r in roster.items():
        bound[r.get("bind_profile") or rid] = r

    names = sorted(set(bound) | set(homes) | set(kb["agents"]))
    agents: list[dict] = []
    for name in names:
        r = bound.get(name, {})
        human = bool(r.get("human"))
        home = None if human else homes.get(name)
        st = session_stats(home, since) if home else {}
        ka = kb["agents"].get(name, {})
        exists = human or name in homes or name in kb["agents"]
        agents.append({
            "name": name,
            "seat": r.get("seat") or ("manager" if name == "manager" else "boss" if name in ("default", "boss") else "staff"),
            "human": human,
            "display_name": r.get("name") or name,
            "role": r.get("role") or ("在编" if exists else "空岗"),
            "avatar": r.get("avatar") or name,
            "exists": exists,
            "state": "human" if human else ka.get("state", "idle"),
            "current": ka.get("current"),
            "counts": ka.get("counts", {}),
            "tasks": ka.get("tasks", [])[:8],
            "tokens": {
                "total": num(st.get("tokens_total")),
                "input": num(st.get("input_tokens")),
                "output": num(st.get("output_tokens")),
                "cache_read": num(st.get("cache_read_tokens")),
                "cost_usd": round(float(st.get("cost") or 0), 4),
                "sessions": num(st.get("sessions")),
            },
            "last_activity": st.get("last_activity"),
            "recent": st.get("recent", []),
        })

    totals = dict(kb["totals"])
    totals.update({
        "seats": len(agents),
        "agents": sum(1 for a in agents if a["exists"]),
        "tokens_total": sum(a["tokens"]["total"] for a in agents),
        "cost_usd": round(sum(a["tokens"]["cost_usd"] for a in agents), 4),
        "working": sum(1 for a in agents if a["state"] == "working"),
    })

    # 聊天室时间线 = 老板留言（chat.json）+ 员工动态（kanban），按时间合并
    boss_name = next((r.get("name") for r in roster.values() if r.get("human")), "老板")
    feed = list(extra.get("feed", []))
    for m in load_chat():
        feed.append({"kind": "", "who": "boss", "author": "boss", "name": boss_name,
                     "text": m.get("text") or "", "at": m.get("at"),
                     "assignee": m.get("assignee"), "assignee_name": m.get("assignee_name"),
                     "task_id": m.get("task_id"), "ok": m.get("ok", True)})
    feed.sort(key=lambda x: x.get("at") or "")
    feed = feed[-FEED_LIMIT:]

    return {
        "generated_at": datetime.now().isoformat(timespec="seconds"),
        "hermes_home": str(hermes_home()),
        "window": f"最近 {days} 天",
        "office": office_cfg,
        "totals": totals,
        "agents": agents,
        "feed": feed,
        "targets": [{"name": d, "profile": p} for d, p in chat_targets()],
        "default_assignee": manager_profile(),
    }


# ------------------------------------------------------------------------- 路由

@router.options("/{rest:path}")
def preflight(rest: str) -> Response:
    """srcdoc 里的预检（自定义 header 触发）。"""
    return Response(status_code=204, headers=CORS_HEADERS)


@router.get("/office")
def get_office(days: int = 8) -> dict:
    """办公室快照（只读）。桌面端面板 5 秒轮询这个。"""
    return build(days)


@router.get("/health")
def health() -> dict:
    home = hermes_home()
    return {"ok": True, "hermes_home": str(home), "kanban": (home / "kanban.db").exists()}


@router.get("/avatars")
def avatars() -> dict:
    """头像只在加载时取一次（base64 内嵌，免得再多开静态路由/权限口子）。"""
    out: dict[str, str] = {}
    if AVATAR_DIR.is_dir():
        for f in sorted(AVATAR_DIR.glob("*.jpg")):
            try:
                out[f.stem] = "data:image/jpeg;base64," + base64.b64encode(f.read_bytes()).decode()
            except Exception:
                continue
    return out


def save_office_cfg(title: str, slogan: str) -> tuple[bool, str]:
    """改顶部横幅：写回插件目录的 agents.json（和独立窗口版同一个字段）"""
    try:
        cfg = json.loads(ROSTER_FILE.read_text(encoding="utf-8")) if ROSTER_FILE.exists() else {"agents": []}
        cfg["OFFICE"] = {"title": (title or "").strip()[:60] or "Hermes 办公室",
                         "slogan": (slogan or "").strip()[:120]}
        ROSTER_FILE.write_text(json.dumps(cfg, ensure_ascii=False, indent=2), encoding="utf-8")
        return True, "已保存"
    except Exception as e:
        return False, f"{type(e).__name__}: {e}"


@router.post("/chat")
def post_chat(payload: dict) -> dict:
    """老板在面板里留言/派活：@某人 → 派给他；不 @ → 派给经理。走官方 CLI，不直接写库。"""
    text = str((payload or {}).get("text") or "").strip()
    if not text:
        return {"ok": False, "message": "内容不能为空"}
    text = text[:600]
    prof, disp = resolve_mention(text)
    if not prof:
        prof = manager_profile()
        disp = next((d for d, p in chat_targets() if p == prof), prof)
    title = strip_mention(text, disp)[:200] or text[:200]
    ok, out = assign_task(title, prof, body=f"来自桌面端办公室面板（老板留言：{text}）")
    task_id = None
    for tok in (out or "").replace("\n", " ").split():
        if tok.startswith("t_"):
            task_id = tok.strip(".,;)")
            break
    append_chat(text, prof, disp, task_id, ok)
    return {"ok": ok, "message": out, "assignee": prof, "assignee_name": disp, "task_id": task_id}


@router.post("/banner")
def post_banner(payload: dict) -> dict:
    ok, msg = save_office_cfg(str((payload or {}).get("title") or ""),
                              str((payload or {}).get("slogan") or ""))
    return {"ok": ok, "message": msg}


@router.post("/assign")
def post_assign(payload: dict) -> dict:
    """独立窗口版页面的派活契约（title/body/assignee），让原页面一字不改也能用。"""
    p = payload or {}
    ok, out = assign_task(str(p.get("title") or ""), str(p.get("assignee") or manager_profile()),
                          str(p.get("body") or ""))
    return {"ok": ok, "message": out}


# --------------------------------------------------------------- UI（原页面直出）

UI_FILE = PLUGIN_DIR / "ui" / "index.html"
_UI_URL: str | None = None


def start_ui_server() -> str | None:
    """在插件自己的 ui/ 目录里起一个只监听 127.0.0.1 的极小服务。

    这套 server.py 就是独立窗口版用的那份（同一份页面 + 同一份数据契约），
    面板用 iframe 直连它：同源、无鉴权/CORS 烦恼、视觉与独立窗口 100% 一致，
    而且**不需要用户另外跑任何东西**（插件后端起它，进程随 gateway 一起活）。
    端口随机：每次后端重启都换一个，/ui-url 会返回当前的。
    """
    global _UI_URL
    if _UI_URL:
        return _UI_URL
    try:
        import importlib.util
        import socket
        import threading
        from http.server import ThreadingHTTPServer

        srv_py = PLUGIN_DIR / "ui" / "server.py"
        if not srv_py.exists():
            return None
        spec = importlib.util.spec_from_file_location("hermes_office_ui_server", str(srv_py))
        mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mod)          # type: ignore[union-attr]
        mod.HERMES_HOME = mod.default_hermes_home()
        mod.WINDOW_DAYS = 7

        s = socket.socket()
        s.bind(("127.0.0.1", 0))
        port = s.getsockname()[1]
        s.close()

        httpd = ThreadingHTTPServer(("127.0.0.1", port), mod.Handler)
        threading.Thread(target=httpd.serve_forever, daemon=True,
                         name="hermes-office-ui").start()
        _UI_URL = f"http://127.0.0.1:{port}/"
    except Exception:
        _UI_URL = None
    return _UI_URL


def session_token() -> str:
    """桌面端会话 token（后端进程自己就能拿到），注入给 srcdoc 里的页面用。"""
    t = os.environ.get("HERMES_DASHBOARD_SESSION_TOKEN")
    if t:
        return t
    try:
        from hermes_cli import web_server as ws
        return getattr(ws, "_SESSION_TOKEN", "") or ""
    except Exception:
        return ""


def _ui_shim() -> str:
    """注入到原页面最前面的一小段 shim：
      1) 把 /api/xxx 改写到本插件命名空间，并带上会话 token（srcdoc 是不透明源，带不了 header 就 401）
      2) 把 agent.avatar（/avatars_256/x.jpg）换成内嵌 data URI —— srcdoc 里的 <img> 同样带不了 token
    """
    tok = json.dumps(session_token())
    return (
        "<script>(function(){"
        "var TOKEN=" + tok + ";"
        "var BASE='/api/plugins/hermes-office';"
        "var of=window.fetch.bind(window);"
        "var AV=of(BASE+'/avatars',{headers:{'X-Hermes-Session-Token':TOKEN}})"
        ".then(function(r){return r.json()}).catch(function(){return {}});"
        "window.fetch=function(u,o){"
        "  var url=u;"
        "  if(typeof u==='string'&&u.indexOf('/api/')===0){url=BASE+u.slice(4);}"
        "  var opt=Object.assign({},o||{});"
        "  var h=Object.assign({},(o&&o.headers)||{});"
        "  h['X-Hermes-Session-Token']=TOKEN;"
        "  opt.headers=h;"
        "  return of(url,opt).then(function(r){"
        "    if(String(url).indexOf('/office')<0){return r;}"
        "    return r.clone().json().then(function(d){"
        "      return AV.then(function(av){"
        "        (d.agents||[]).forEach(function(a){"
        "          if(a&&a.avatar){var k=String(a.avatar).split('/').pop().replace(/\\.[a-z]+$/i,'');"
        "            if(av[k]){a.avatar=av[k];}}"
        "        });"
        "        return new Response(JSON.stringify(d),{status:r.status,headers:{'Content-Type':'application/json'}});"
        "      });"
        "    });"
        "  });"
        "};"
        "})();</script>"
    )


@router.get("/ui-url")
def ui_url() -> dict:
    """面板首选的渲染路径：返回插件自带 UI 服务的地址，面板 iframe 直连。"""
    url = start_ui_server()
    if url:
        return {"ok": True, "url": url}
    return {"ok": False, "url": "", "message": "ui/server.py 没起来（看 gateway 日志）"}


@router.get("/ui")
def ui() -> dict:
    """把独立窗口版那一页原样交给桌面端面板（面板用 srcDoc 渲染，视觉 100% 一致）。"""
    try:
        html = UI_FILE.read_text(encoding="utf-8")
    except Exception as e:
        return {"ok": False, "html": "", "message": f"读不到 ui/index.html：{type(e).__name__}: {e}"}
    # 插到 <head> 之后、页面脚本之前
    marker = "<head>"
    idx = html.lower().find(marker)
    shim = _ui_shim()
    html = (html[:idx + len(marker)] + shim + html[idx + len(marker):]) if idx >= 0 else (shim + html)
    return {"ok": True, "html": html}
