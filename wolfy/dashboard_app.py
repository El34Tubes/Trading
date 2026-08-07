#!/usr/bin/env python3
"""Wolfy mobile dashboard: summary APIs + landing page.

Public/VPS-ready, PIN-protected, read-mostly dashboard for Wolfy/Hermes status.
No secrets are embedded here; configure via environment variables.
"""
from __future__ import annotations

import json
import os
import secrets
import uuid
from collections import defaultdict
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Any, Callable, Mapping

import psycopg
from fastapi import Depends, FastAPI, Header, HTTPException, Request
from fastapi.responses import HTMLResponse, JSONResponse

DEFAULT_DSN = os.environ.get("WOLFY_POSTGRES_DSN", "dbname=wolfy user=root host=/var/run/postgresql")
DEFAULT_REFRESH_SECONDS = int(os.environ.get("WOLFY_DASHBOARD_REFRESH_SECONDS", "60"))
DEFAULT_NOTES_PATH = Path(os.environ.get("WOLFY_DASHBOARD_NOTES", "/data/dashboard_notes.json"))


def _iso(value: Any) -> str | None:
    if value is None:
        return None
    if isinstance(value, (datetime, date)):
        return value.isoformat()
    return str(value)


def _day(value: Any) -> str:
    if isinstance(value, datetime):
        return value.date().isoformat()
    if isinstance(value, date):
        return value.isoformat()
    if value:
        return str(value)[:10]
    return date.today().isoformat()


def _num(value: Any) -> float | int | None:
    if value is None:
        return None
    try:
        f = float(value)
    except Exception:
        return None
    return int(f) if f.is_integer() else f


class JsonNoteStore:
    """Tiny JSON store for phone-entered notes/status overrides."""

    def __init__(self, path: Path = DEFAULT_NOTES_PATH):
        self.path = Path(path)

    def _read(self) -> list[dict[str, Any]]:
        if not self.path.exists():
            return []
        try:
            data = json.loads(self.path.read_text())
        except Exception:
            return []
        return data if isinstance(data, list) else []

    def _write(self, notes: list[dict[str, Any]]) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.path.write_text(json.dumps(notes, indent=2, sort_keys=True, default=str))

    def list_notes(self) -> list[dict[str, Any]]:
        notes = [item for item in self._read() if item.get("type", "note") == "note"]
        return sorted(notes, key=lambda item: item.get("created_at", ""), reverse=True)[:50]

    def add_note(self, *, agent: str, note: str, status: str = "active") -> dict[str, Any]:
        item = {
            "id": uuid.uuid4().hex[:12],
            "type": "note",
            "agent": (agent or "general").lower(),
            "note": note.strip(),
            "status": status or "active",
            "created_at": datetime.now(timezone.utc).isoformat(),
        }
        if not item["note"]:
            raise ValueError("note is required")
        notes = self._read()
        notes.append(item)
        self._write(notes)
        return item

    def list_poll_answers(self) -> list[dict[str, Any]]:
        answers = [item for item in self._read() if item.get("type") == "poll_answer"]
        return sorted(answers, key=lambda item: item.get("created_at", ""), reverse=True)[:50]

    def add_poll_answer(self, *, poll_id: str, choice: str, note: str = "") -> dict[str, Any]:
        item = {
            "id": uuid.uuid4().hex[:12],
            "type": "poll_answer",
            "poll_id": poll_id.strip(),
            "choice": choice.strip(),
            "note": note.strip(),
            "created_at": datetime.now(timezone.utc).isoformat(),
        }
        if not item["poll_id"] or not item["choice"]:
            raise ValueError("poll_id and choice are required")
        rows = [row for row in self._read() if not (row.get("type") == "poll_answer" and row.get("poll_id") == item["poll_id"])]
        rows.append(item)
        self._write(rows)
        return item


def _normalize_task(row: Mapping[str, Any]) -> dict[str, Any]:
    return {
        "id": row.get("id"),
        "agent": (row.get("agent") or row.get("agent_name") or row.get("assigned_agent") or "unknown").lower(),
        "status": row.get("status") or "unknown",
        "title": row.get("title") or row.get("summary") or "Untitled task",
        "updated_at": _iso(row.get("updated_at") or row.get("completed_at") or row.get("created_at")),
    }


def _normalize_run(row: Mapping[str, Any]) -> dict[str, Any]:
    return {
        "id": row.get("id"),
        "agent": (row.get("agent") or row.get("agent_name") or "unknown").lower(),
        "status": row.get("status") or "unknown",
        "title": row.get("title") or row.get("summary") or row.get("result_summary") or row.get("role") or "Agent run",
        "started_at": _iso(row.get("started_at") or row.get("created_at")),
        "ended_at": _iso(row.get("ended_at") or row.get("completed_at") or row.get("finished_at")),
        "total_tokens": _num(row.get("total_tokens")),
        "estimated_cost": _num(row.get("estimated_cost")),
    }


def build_dashboard_snapshot(
    *,
    now: datetime | None = None,
    tasks: list[Mapping[str, Any]],
    runs: list[Mapping[str, Any]],
    recommendations: list[Mapping[str, Any]],
    paper_trades: list[Mapping[str, Any]],
    system_metrics: list[Mapping[str, Any]],
    polls: list[Mapping[str, Any]],
    poll_answers: list[Mapping[str, Any]] | None = None,
    manual_notes: list[Mapping[str, Any]] | None = None,
    refresh_seconds: int = DEFAULT_REFRESH_SECONDS,
) -> dict[str, Any]:
    now = now or datetime.now(timezone.utc)
    agents: dict[str, dict[str, Any]] = defaultdict(lambda: {"queued_tasks": 0, "in_progress_tasks": 0, "completed_tasks": 0, "failed_tasks": 0, "completed_runs": 0, "active_runs": 0, "latest": None})
    current = {
        "as_of_date": now.date().isoformat(),
        "tasks": {"queued": 0, "in_progress": 0, "completed": 0, "failed": 0},
        "runs": {"active": 0, "completed": 0, "failed": 0},
        "recommendations": {"pending_attention": 0, "total_current": 0},
        "paper_trades": {"open": 0, "total_current": 0},
    }

    normalized_tasks = [_normalize_task(dict(task)) for task in tasks]
    normalized_runs = [_normalize_run(dict(run)) for run in runs]
    for task in normalized_tasks:
        agent = task["agent"]
        status = task["status"]
        bucket = agents[agent]
        if status == "queued":
            bucket["queued_tasks"] += 1
            current["tasks"]["queued"] += 1
        elif status in {"in_progress", "claimed", "started"}:
            bucket["in_progress_tasks"] += 1
            current["tasks"]["in_progress"] += 1
        elif status == "completed":
            bucket["completed_tasks"] += 1
            current["tasks"]["completed"] += 1
        elif status in {"failed", "error", "blocked"}:
            bucket["failed_tasks"] += 1
            current["tasks"]["failed"] += 1
        bucket["latest"] = bucket["latest"] or task["title"]

    for run in normalized_runs:
        agent = run["agent"]
        status = run["status"]
        if status in {"completed", "success", "succeeded"}:
            agents[agent]["completed_runs"] += 1
            current["runs"]["completed"] += 1
        elif status in {"failed", "error"}:
            current["runs"]["failed"] += 1
        if status in {"started", "running", "in_progress"}:
            agents[agent]["active_runs"] += 1
            current["runs"]["active"] += 1

    rec_rows = []
    pending_user_attention = 0
    for rec in recommendations:
        status = rec.get("status") or "unknown"
        if status in {"paper_candidate", "pending", "pending_review", "needs_user_approval", "approved"}:
            pending_user_attention += 1
            current["recommendations"]["pending_attention"] += 1
        current["recommendations"]["total_current"] += 1
        rec_rows.append({
            "id": rec.get("id"),
            "ticker": rec.get("ticker"),
            "status": status,
            "created_at": _iso(rec.get("created_at")),
            "thesis": rec.get("thesis"),
            "entry_trigger": rec.get("entry_trigger"),
            "stop": rec.get("stop"),
            "target": rec.get("target"),
        })

    paper_rows = []
    for trade in paper_trades:
        trade_status = str(trade.get("status") or "unknown")
        paper_rows.append({k: _iso(v) if isinstance(v, (datetime, date)) else v for k, v in dict(trade).items()})
        current["paper_trades"]["total_current"] += 1
        if trade_status in {"open", "active", "entered"}:
            current["paper_trades"]["open"] += 1

    health: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for metric in system_metrics:
        category = metric.get("category") or metric.get("metric_name") or "system"
        health[str(category)].append({
            "metric_name": metric.get("metric_name") or metric.get("notes") or "metric",
            "metric_value": _num(metric.get("metric_value")) if metric.get("metric_value") is not None else _num(metric.get("root_used_pct")),
            "captured_at": _iso(metric.get("captured_at") or metric.get("created_at")),
        })

    return {
        "generated_at": now.isoformat(),
        "refresh_seconds": refresh_seconds,
        "current": current,
        "agents": dict(sorted(agents.items())),
        "recommendations": {"pending_user_attention": pending_user_attention, "items": rec_rows[:25]},
        "paper_trades": paper_rows[:25],
        "health": dict(health),
        "polls": list(polls)[:20],
        "poll_answers": list(poll_answers or [])[:50],
        "manual_notes": list(manual_notes or [])[:50],
    }


class PostgresDashboardRepository:
    def __init__(self, dsn: str = DEFAULT_DSN, note_store: JsonNoteStore | None = None):
        self.dsn = dsn
        self.note_store = note_store or JsonNoteStore()

    def __call__(self) -> dict[str, Any]:
        with psycopg.connect(self.dsn, row_factory=psycopg.rows.dict_row) as conn:
            tasks = conn.execute("SELECT id, coalesce(agent, agent_name, assigned_agent) AS agent, status, title, updated_at, completed_at, created_at FROM agent_tasks ORDER BY updated_at DESC NULLS LAST, id DESC LIMIT 200").fetchall()
            runs = conn.execute("SELECT id, agent_name AS agent, status, title, role, summary, result_summary, started_at, ended_at, completed_at, finished_at, total_tokens, estimated_cost FROM agent_runs ORDER BY started_at DESC LIMIT 100").fetchall()
            recommendations = conn.execute("SELECT id, ticker, status, created_at, thesis, entry_trigger, stop, target FROM recommendations ORDER BY created_at DESC LIMIT 100").fetchall()
            paper_trades = conn.execute("SELECT id, ticker, status, entry_date, entry_price, stop_price, target_price, r_multiple, created_at FROM paper_trades ORDER BY created_at DESC LIMIT 100").fetchall()
            system_metrics = conn.execute("SELECT category, metric_name, metric_value, root_used_pct, captured_at, created_at, notes FROM system_metrics ORDER BY captured_at DESC NULLS LAST, created_at DESC NULLS LAST LIMIT 100").fetchall()
        return {
            "tasks": tasks,
            "runs": runs,
            "recommendations": recommendations,
            "paper_trades": paper_trades,
            "system_metrics": system_metrics,
            "polls": suggested_polls(tasks=tasks, recommendations=recommendations, paper_trades=paper_trades),
            "poll_answers": self.note_store.list_poll_answers(),
            "manual_notes": self.note_store.list_notes(),
        }


def suggested_polls(*, tasks: list[Mapping[str, Any]], recommendations: list[Mapping[str, Any]], paper_trades: list[Mapping[str, Any]]) -> list[dict[str, Any]]:
    polls: list[dict[str, Any]] = []
    pending_recs = [rec for rec in recommendations if rec.get("status") in {"paper_candidate", "pending_review", "needs_user_approval"}]
    queued_tasks = [task for task in tasks if task.get("status") == "queued"]
    if pending_recs:
        polls.append({"id": "rec-review", "status": "open", "question": "How should Wolfy handle current paper candidates?", "choices": ["keep logging", "tighten filters", "pause recommendations", "summarize first"]})
    if queued_tasks:
        polls.append({"id": "next-build", "status": "open", "question": "Which agent workstream should move next?", "choices": ["recommendations", "paper logging", "dashboard", "system health"]})
    if not polls:
        polls.append({"id": "optimize-next", "status": "open", "question": "What should the agent optimize next?", "choices": ["new strategy", "better reports", "lower token cost", "infra health"]})
    return polls


def _repository_payload(repository: Callable[[], Mapping[str, Any]]) -> Mapping[str, Any]:
    payload = repository()
    return payload if isinstance(payload, Mapping) else {}


def create_app(*, repository: Callable[[], Mapping[str, Any]] | None = None, dashboard_pin: str | None = None, note_store: JsonNoteStore | None = None) -> FastAPI:
    app = FastAPI(title="Wolfy Command Dashboard", version="0.1.0")
    note_store = note_store or JsonNoteStore()
    repository = repository or PostgresDashboardRepository(note_store=note_store)
    pin = dashboard_pin if dashboard_pin is not None else os.environ.get("WOLFY_DASHBOARD_PIN", "")

    def require_pin(x_dashboard_pin: str | None = Header(default=None)) -> None:
        if not pin:
            raise HTTPException(status_code=503, detail="WOLFY_DASHBOARD_PIN is required")
        if not x_dashboard_pin or not secrets.compare_digest(x_dashboard_pin, pin):
            raise HTTPException(status_code=401, detail="dashboard PIN required")

    def snapshot() -> dict[str, Any]:
        payload = _repository_payload(repository)
        return build_dashboard_snapshot(
            tasks=list(payload.get("tasks", [])),
            runs=list(payload.get("runs", [])),
            recommendations=list(payload.get("recommendations", [])),
            paper_trades=list(payload.get("paper_trades", [])),
            system_metrics=list(payload.get("system_metrics", [])),
            polls=list(payload.get("polls", [])),
            poll_answers=list(payload.get("poll_answers", [])),
            manual_notes=list(payload.get("manual_notes", [])),
        )

    @app.get("/healthz")
    def healthz() -> dict[str, str]:
        return {"status": "ok"}

    @app.get("/api/summary")
    def api_summary(_: None = Depends(require_pin)) -> JSONResponse:
        return JSONResponse(snapshot())

    @app.post("/api/notes")
    async def api_notes(request: Request, _: None = Depends(require_pin)) -> dict[str, Any]:
        body = await request.json()
        return note_store.add_note(agent=str(body.get("agent", "general")), note=str(body.get("note", "")), status=str(body.get("status", "active")))

    @app.post("/api/polls/{poll_id}/answer")
    async def api_poll_answer(poll_id: str, request: Request, _: None = Depends(require_pin)) -> dict[str, Any]:
        body = await request.json()
        return note_store.add_poll_answer(poll_id=poll_id, choice=str(body.get("choice", "")), note=str(body.get("note", "")))

    @app.get("/", response_class=HTMLResponse)
    def index() -> str:
        return DASHBOARD_HTML

    return app


DASHBOARD_HTML = """<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8" />
  <meta name="viewport" content="width=device-width, initial-scale=1" />
  <title>Wolfy Command Dashboard</title>
  <style>
    :root { color-scheme: dark; --bg:#080b11; --panel:#111827; --muted:#94a3b8; --text:#e5e7eb; --accent:#38bdf8; --good:#22c55e; --warn:#f59e0b; --bad:#ef4444; }
    body { margin:0; font-family: Inter, ui-sans-serif, system-ui, -apple-system, Segoe UI, sans-serif; background:linear-gradient(180deg,#07111f,#080b11 30%); color:var(--text); }
    header { position:sticky; top:0; z-index:5; padding:16px; backdrop-filter: blur(14px); background:rgba(8,11,17,.82); border-bottom:1px solid rgba(148,163,184,.18); }
    h1 { margin:0; font-size:22px; } .sub { color:var(--muted); font-size:13px; margin-top:4px; }
    main { padding:14px; display:grid; gap:14px; max-width:1180px; margin:auto; }
    .grid { display:grid; grid-template-columns:repeat(auto-fit,minmax(260px,1fr)); gap:14px; }
    .card { background:rgba(17,24,39,.86); border:1px solid rgba(148,163,184,.16); border-radius:18px; padding:14px; box-shadow:0 14px 40px rgba(0,0,0,.22); }
    .card h2 { font-size:16px; margin:0 0 10px; } .metric { display:flex; justify-content:space-between; gap:10px; padding:8px 0; border-top:1px solid rgba(148,163,184,.10); }
    .pill { border-radius:999px; padding:4px 9px; background:rgba(56,189,248,.13); color:#bae6fd; font-size:12px; }
    .good{color:var(--good)} .warn{color:var(--warn)} .bad{color:var(--bad)} .muted{color:var(--muted)}
    input, textarea, button { width:100%; box-sizing:border-box; border-radius:12px; border:1px solid rgba(148,163,184,.25); background:#0b1220; color:var(--text); padding:10px; margin-top:8px; }
    button { background:linear-gradient(135deg,#0284c7,#0f766e); border:0; font-weight:700; }
    .timeline-row { display:grid; grid-template-columns: 1fr repeat(4, auto); gap:8px; align-items:center; font-size:13px; padding:8px 0; border-top:1px solid rgba(148,163,184,.10); }
    .rec { border-left:3px solid var(--accent); padding:8px 10px; margin:8px 0; background:rgba(8,47,73,.26); border-radius:10px; }
  </style>
</head>
<body>
<header><h1>Wolfy Command Dashboard</h1><div class="sub">Current point-in-time status, agents, health, recommendations, approvals, and interview polls. Updates every 60 seconds.</div></header>
<main>
  <section class="card"><h2>Unlock</h2><input id="pin" type="password" placeholder="Dashboard PIN" autocomplete="current-password"/><button onclick="load()">Load Dashboard</button><div id="status" class="sub"></div></section>
  <section class="card"><h2>Current Snapshot</h2><div id="current"></div></section>
  <section class="grid"><div class="card"><h2>Recommendations / Approval Attention</h2><div id="recs"></div></div><div class="card"><h2>Agents</h2><div id="agents"></div></div></section>
  <section class="grid"><div class="card"><h2>Environment Health</h2><div id="health"></div></div><div class="card"><h2>Interview Polls</h2><div id="polls"></div></div></section>
  <section class="card"><h2>Manual Notes / Status Overrides</h2><input id="agent" placeholder="agent e.g. wolfy"/><textarea id="note" placeholder="Add note or override"></textarea><button onclick="addNote()">Save Note</button><div id="notes"></div></section>
</main>
<script>
let refreshTimer=null;
function pin(){ return document.getElementById('pin').value; }
async function load(){
  const r=await fetch('/api/summary',{headers:{'x-dashboard-pin':pin()}});
  if(!r.ok){document.getElementById('status').textContent='Auth failed or server unavailable'; return;}
  const d=await r.json(); render(d); document.getElementById('status').textContent='Updated '+new Date(d.generated_at).toLocaleString();
  clearTimeout(refreshTimer); refreshTimer=setTimeout(load,(d.refresh_seconds||60)*1000);
}
function metric(k,v){ return `<div class="metric"><span>${k}</span><b>${v}</b></div>`; }
function render(d){
  const c=d.current||{tasks:{},runs:{},recommendations:{},paper_trades:{}};
  current.innerHTML=`<div class="grid"><div>${metric('As of', c.as_of_date||'now')}${metric('Queued tasks', c.tasks.queued||0)}${metric('In progress tasks', c.tasks.in_progress||0)}${metric('Failed/blocked tasks', c.tasks.failed||0)}</div><div>${metric('Active runs', c.runs.active||0)}${metric('Recommendations needing attention', c.recommendations.pending_attention||0)}${metric('Open paper trades', c.paper_trades.open||0)}${metric('Current paper trades tracked', c.paper_trades.total_current||0)}</div></div>`;
  recs.innerHTML=metric('Pending attention', d.recommendations.pending_user_attention)+(d.recommendations.items||[]).slice(0,8).map(r=>`<div class="rec"><b>${r.ticker}</b> <span class="pill">${r.status}</span><div class="muted">${r.thesis||''}</div></div>`).join('');
  agents.innerHTML=Object.entries(d.agents||{}).map(([a,x])=>`<div class="metric"><span><b>${a}</b><br><span class="muted">${x.latest||''}</span></span><span>Q${x.queued_tasks} / Run${x.active_runs} / Done${x.completed_tasks}</span></div>`).join('')||'<div class="muted">No agents</div>';
  health.innerHTML=Object.entries(d.health||{}).map(([cat,items])=>`<h3>${cat}</h3>`+items.slice(0,5).map(i=>metric(i.metric_name,i.metric_value??'n/a')).join('')).join('')||'<div class="muted">No health metrics</div>';
  polls.innerHTML=(d.polls||[]).map(p=>`<div class="rec"><b>${p.question}</b><div>${(p.choices||[]).map(c=>`<button onclick="answerPoll('${p.id}','${String(c).replaceAll("'","&#39;")}')">${c}</button>`).join('')}</div></div>`).join('')+((d.poll_answers||[]).length?`<h3>Recent answers</h3>${(d.poll_answers||[]).slice(0,5).map(a=>metric(a.poll_id,a.choice)).join('')}`:'')||'<div class="muted">No polls</div>';
  notes.innerHTML=(d.manual_notes||[]).map(n=>`<div class="metric"><span><b>${n.agent}</b><br>${n.note}</span><span class="muted">${(n.created_at||'').slice(0,16)}</span></div>`).join('');
}
async function addNote(){
  const r=await fetch('/api/notes',{method:'POST',headers:{'content-type':'application/json','x-dashboard-pin':pin()},body:JSON.stringify({agent:agent.value,note:note.value})});
  if(r.ok){ note.value=''; load(); } else alert('save failed');
}
async function answerPoll(pollId, choice){
  const r=await fetch(`/api/polls/${pollId}/answer`,{method:'POST',headers:{'content-type':'application/json','x-dashboard-pin':pin()},body:JSON.stringify({choice})});
  if(r.ok){ load(); } else alert('poll answer failed');
}
</script>
</body></html>"""

app = create_app()

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=int(os.environ.get("PORT", "8080")))
