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

from fastapi import APIRouter

try:
    from hermes_cli import kanban_db  # gateway 自带；拿它定位数据目录最稳
except Exception:  # pragma: no cover - 极端情况下退回环境变量
    kanban_db = None

router = APIRouter()
HERE = Path(__file__).resolve().parent          # <plugin>/dashboard
PLUGIN_DIR = HERE.parent                        # <plugin>
ROSTER_FILE = PLUGIN_DIR / "agents.json"
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
    return {
        "generated_at": datetime.now().isoformat(timespec="seconds"),
        "hermes_home": str(hermes_home()),
        "window": f"最近 {days} 天",
        "office": office_cfg,
        "totals": totals,
        "agents": agents,
        "feed": extra.get("feed", []),
    }


# ------------------------------------------------------------------------- 路由

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
