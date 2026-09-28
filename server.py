"""Chat ↔ Cowork ↔ CC loop MCP server (v1).

Symmetric N-way Collaborator protocol. Any participant declares its identity
as "Chat", "Cowork", or "CC" via the `me` parameter on every call. Anyone can
dispatch tasks to anyone; routing is explicit per-call.

State lives in SQLite. A single asyncio.Condition wakes long-polls when
state changes. Long-polls return `{still_waiting: true}` on timeout (not
errors) — callers loop. v0 single-user assumption preserved: at most one
session active per role.
"""

from __future__ import annotations

import asyncio
import os
import re
import sqlite3
import sys
import time
import uuid
from contextlib import contextmanager
from typing import Optional

from mcp.server.fastmcp import FastMCP


DB_PATH = os.environ.get("LOOP_DB", os.path.expanduser("~/collab-loop/loop.db"))
RETENTION_DAYS = int(os.environ.get("LOOP_RETENTION_DAYS", "7"))

BASE_ROLES = ("Chat", "Cowork", "CC", "CCD", "Human", "Codex")
# A role is a base name optionally followed by digits (Chat2, CC3, ...) so
# multiple instances of the same surface can co-exist in one loop.
# "Human" is the user herself, participating directly via the dashboard.
# "Codex" is the OpenAI Codex CLI peer — joins via the aleph MCP like CC/CCD.
ROLE_PATTERN = re.compile(r"^(Chat|Cowork|CC|CCD|Human|Codex)(\d*)$")
VALID_OUTCOMES = ("completed", "failed", "blocked", "rejected")

# Lower number = higher priority for becoming the loop's "closer".
# When multiple collaborators idle out at the same time, the highest-priority
# one online becomes responsible for posting the summary; others defer.
ROLE_PRIORITY = {"Human": 0, "Chat": 1, "Cowork": 2, "CCD": 3, "CC": 4, "Codex": 5}


def _base_role(role: str) -> str:
    m = ROLE_PATTERN.match(role)
    return m.group(1) if m else role


def _close_priority(role: str) -> tuple:
    """Sort key for closer election: base-priority, then role string for
    deterministic tie-break between same-base instances (Chat < Chat2)."""
    return (ROLE_PRIORITY.get(_base_role(role), 99), role)

# How recently a role must have called any tool to count as "online" for
# closer-eligibility purposes.
PRESENCE_WINDOW_SEC = 90

# How long a loop_closed summary remains deliverable. Belt-and-suspenders
# against ghost-summary delivery — even if other safeguards fail, anything
# older than this TTL is dead.
LOOP_CLOSE_TTL_SEC = int(os.environ.get("LOOP_CLOSE_TTL_SEC", "3600"))


_cond: Optional[asyncio.Condition] = None


def cond() -> asyncio.Condition:
    global _cond
    if _cond is None:
        _cond = asyncio.Condition()
    return _cond


async def notify():
    c = cond()
    async with c:
        c.notify_all()


@contextmanager
def db():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    try:
        yield conn
        conn.commit()
    finally:
        conn.close()


def init_db():
    # detect legacy v0 schema (direction column on messages) and reset —
    # the old data is testing crumbs, not worth migrating.
    if os.path.exists(DB_PATH):
        try:
            with db() as conn:
                cols = {row["name"] for row in conn.execute("PRAGMA table_info(messages)")}
                if cols and "direction" in cols and "from_role" not in cols:
                    backup = DB_PATH + ".v0bak"
                    print(f"[init] legacy v0 schema detected — moving {DB_PATH} → {backup}",
                          file=sys.stderr, flush=True)
                    os.rename(DB_PATH, backup)
        except sqlite3.OperationalError:
            pass

        # presence.segment_started_at migration — add column if missing and
        # clear stale rows so legacy roles get a fresh segment on next touch
        # (otherwise old summaries with created_at > legacy default of 0
        # would still be deliverable).
        try:
            with db() as conn:
                pcols = {row["name"] for row in conn.execute("PRAGMA table_info(presence)")}
                if pcols and "segment_started_at" not in pcols:
                    conn.execute(
                        "ALTER TABLE presence ADD COLUMN "
                        "segment_started_at REAL NOT NULL DEFAULT 0"
                    )
                    conn.execute("DELETE FROM presence")
                    print("[init] presence schema migrated; cleared stale rows",
                          file=sys.stderr, flush=True)
        except sqlite3.OperationalError:
            pass

    with db() as conn:
        conn.executescript(
            """
            CREATE TABLE IF NOT EXISTS tasks (
                id                   TEXT PRIMARY KEY,
                status               TEXT NOT NULL,
                outcome              TEXT,
                context              TEXT NOT NULL,
                summary              TEXT,
                dispatched_by        TEXT NOT NULL,
                assigned_to          TEXT NOT NULL,
                last_seen_dispatcher INTEGER NOT NULL DEFAULT 0,
                created_at           REAL NOT NULL,
                updated_at           REAL NOT NULL
            );
            CREATE TABLE IF NOT EXISTS messages (
                id        INTEGER PRIMARY KEY AUTOINCREMENT,
                task_id   TEXT NOT NULL,
                from_role TEXT NOT NULL,
                to_role   TEXT NOT NULL,
                type      TEXT NOT NULL,
                content   TEXT NOT NULL,
                ts        REAL NOT NULL
            );
            CREATE TABLE IF NOT EXISTS cursors (
                role             TEXT PRIMARY KEY,
                last_seen_msg_id INTEGER NOT NULL DEFAULT 0
            );
            CREATE TABLE IF NOT EXISTS presence (
                role               TEXT PRIMARY KEY,
                last_seen_at       REAL NOT NULL,
                -- start of this role's current continuous online segment.
                -- A gap > PRESENCE_WINDOW_SEC since last touch resets it.
                -- Used to scope loop_closed delivery to the instance that
                -- was actually alive when the close happened.
                segment_started_at REAL NOT NULL DEFAULT 0
            );
            CREATE TABLE IF NOT EXISTS room (
                id         INTEGER PRIMARY KEY AUTOINCREMENT,
                sender     TEXT NOT NULL,
                content    TEXT NOT NULL,
                created_at REAL NOT NULL
            );
            CREATE TABLE IF NOT EXISTS room_cursors (
                role             TEXT PRIMARY KEY,
                last_seen_msg_id INTEGER NOT NULL DEFAULT 0
            );
            CREATE TABLE IF NOT EXISTS loop_summaries (
                id             INTEGER PRIMARY KEY AUTOINCREMENT,
                closer         TEXT NOT NULL,
                summary        TEXT NOT NULL,
                created_at     REAL NOT NULL,
                last_seen_by   TEXT NOT NULL DEFAULT ''  -- comma-sep roles that have ack'd
            );
            CREATE INDEX IF NOT EXISTS idx_loop_recent ON loop_summaries(created_at DESC);
            CREATE INDEX IF NOT EXISTS idx_msg_task ON messages(task_id, id);
            CREATE INDEX IF NOT EXISTS idx_msg_to ON messages(to_role, id);
            CREATE INDEX IF NOT EXISTS idx_task_assigned ON tasks(assigned_to, status, created_at);
            """
        )


def prune_old_tasks(retention_days: int = RETENTION_DAYS) -> int:
    """Delete done tasks (and their messages) older than retention_days. Returns count."""
    if retention_days <= 0:
        return 0
    cutoff = time.time() - retention_days * 86400
    with db() as conn:
        conn.execute(
            "DELETE FROM messages WHERE task_id IN ("
            "  SELECT id FROM tasks WHERE status='done' AND updated_at < ?"
            ")",
            (cutoff,),
        )
        cur = conn.execute(
            "DELETE FROM tasks WHERE status='done' AND updated_at < ?", (cutoff,)
        )
        deleted = cur.rowcount
    if deleted:
        # VACUUM cannot run inside a transaction
        conn = sqlite3.connect(DB_PATH)
        try:
            conn.execute("VACUUM")
        finally:
            conn.close()
        print(f"[prune] dropped {deleted} task(s) older than {retention_days}d",
              file=sys.stderr, flush=True)
    return deleted


def _check_role(me: str) -> Optional[dict]:
    if not ROLE_PATTERN.match(me):
        return {
            "ok": False,
            "error": (
                f"`me` must match <base><digits?> where base is one of "
                f"{BASE_ROLES} (e.g. Chat, Chat2, CC3); got {me!r}"
            ),
        }
    return None


def _task_row(task_id: str):
    with db() as conn:
        return conn.execute("SELECT * FROM tasks WHERE id=?", (task_id,)).fetchone()


def _next_msg_to(task_id: str, to_role: str, after_id: int):
    with db() as conn:
        row = conn.execute(
            "SELECT id, from_role, to_role, type, content FROM messages "
            "WHERE task_id=? AND to_role=? AND id>? "
            "ORDER BY id LIMIT 1",
            (task_id, to_role, after_id),
        ).fetchone()
        return dict(row) if row else None


def _bump_last_seen(task_id: str, msg_id: int):
    with db() as conn:
        conn.execute(
            "UPDATE tasks SET last_seen_dispatcher=? WHERE id=? AND last_seen_dispatcher<?",
            (msg_id, task_id, msg_id),
        )


def _bump_role_cursor(role: str, msg_id: int):
    """Bump the per-role cursor used by wait_any. Idempotent — only advances."""
    with db() as conn:
        conn.execute(
            "INSERT INTO cursors (role, last_seen_msg_id) VALUES (?, ?) "
            "ON CONFLICT(role) DO UPDATE SET last_seen_msg_id=excluded.last_seen_msg_id "
            "WHERE excluded.last_seen_msg_id > cursors.last_seen_msg_id",
            (role, msg_id),
        )


def _touch_presence(role: str):
    """Mark `role` as just-active. If the prior `last_seen_at` is older
    than PRESENCE_WINDOW_SEC, this is a brand-new session segment and
    `segment_started_at` resets to now — so a later instance under the
    same role is not treated as the same one for loop_closed delivery."""
    now = time.time()
    with db() as conn:
        row = conn.execute(
            "SELECT last_seen_at, segment_started_at FROM presence WHERE role=?",
            (role,),
        ).fetchone()
        is_continuous = (
            row is not None
            and row["segment_started_at"] > 0
            and (now - row["last_seen_at"]) <= PRESENCE_WINDOW_SEC
        )
        if is_continuous:
            conn.execute(
                "UPDATE presence SET last_seen_at=? WHERE role=?",
                (now, role),
            )
        else:
            conn.execute(
                "INSERT INTO presence (role, last_seen_at, segment_started_at) "
                "VALUES (?, ?, ?) "
                "ON CONFLICT(role) DO UPDATE SET "
                "last_seen_at=excluded.last_seen_at, "
                "segment_started_at=excluded.segment_started_at",
                (role, now, now),
            )


def _online_roles(now: Optional[float] = None) -> set:
    """Roles whose last tool call was within the presence window."""
    cutoff = (now or time.time()) - PRESENCE_WINDOW_SEC
    with db() as conn:
        rows = conn.execute(
            "SELECT role FROM presence WHERE last_seen_at >= ?", (cutoff,)
        ).fetchall()
    return {r["role"] for r in rows}


def _latest_unseen_close_for(role: str):
    """Most recent loop_summaries row deliverable to `role`.

    Eligibility:
      - role's presence segment started at or before the close (i.e. this
        instance was alive when the loop closed — not a fresh session
        wearing the same role label),
      - role still online within PRESENCE_WINDOW_SEC,
      - close is within LOOP_CLOSE_TTL_SEC (TTL safety net),
      - role hasn't ack'd it via last_seen_by, and isn't the closer.
    """
    now = time.time()
    cutoff_ttl = now - LOOP_CLOSE_TTL_SEC
    cutoff_presence = now - PRESENCE_WINDOW_SEC
    with db() as conn:
        row = conn.execute(
            "SELECT s.id, s.closer, s.summary, s.last_seen_by, s.created_at "
            "FROM loop_summaries s "
            "JOIN presence p ON p.role = ? "
            "WHERE s.created_at >= ? "
            "  AND p.segment_started_at > 0 "
            "  AND p.segment_started_at <= s.created_at "
            "  AND p.last_seen_at >= ? "
            "ORDER BY s.created_at DESC LIMIT 1",
            (role, cutoff_ttl, cutoff_presence),
        ).fetchone()
    if not row:
        return None
    seen = set(s for s in row["last_seen_by"].split(",") if s)
    if role in seen or row["closer"] == role:
        return None
    return dict(row)


def _ack_close(role: str, summary_id: int):
    with db() as conn:
        row = conn.execute(
            "SELECT last_seen_by FROM loop_summaries WHERE id=?", (summary_id,)
        ).fetchone()
        if not row:
            return
        seen = set(s for s in row["last_seen_by"].split(",") if s)
        seen.add(role)
        conn.execute(
            "UPDATE loop_summaries SET last_seen_by=? WHERE id=?",
            (",".join(sorted(seen)), summary_id),
        )


def _last_seen(task_id: str) -> int:
    with db() as conn:
        row = conn.execute(
            "SELECT last_seen_dispatcher FROM tasks WHERE id=?", (task_id,)
        ).fetchone()
        return int(row["last_seen_dispatcher"]) if row else 0


# When tunneled (cloudflared / ngrok / VPS-behind-proxy), the Host header
# arrives as the public hostname and FastMCP's default DNS-rebinding
# protection rejects it. Disable by default; opt back in by setting
# LOOP_DNS_REBINDING_PROTECTION=1 if running with an explicit allow-list.
_transport_security = None
if os.environ.get("LOOP_DNS_REBINDING_PROTECTION", "0") != "1":
    from mcp.server.transport_security import TransportSecuritySettings

    _transport_security = TransportSecuritySettings(
        enable_dns_rebinding_protection=False,
    )


SERVER_INSTRUCTIONS = """\
You are connected to **collab-loop**, a symmetric collaborator protocol
that lets Alta's Chat (claude.ai web), Cowork (Claude desktop), and CC
(Claude Code CLI) hand tasks back and forth.

# Self-identify on first use

Before calling any tool, claim your `me` identity (decision tree, first match wins):

1. No file/shell tools → me = "Chat" (claude.ai web)
2. File Read/Write but no Bash → me = "Cowork"
3. Has Bash → walk process tree (`ps -o ppid= -p $$` upward). If ancestors
   include `/Applications/Claude.app/` (or similar Electron desktop bundle)
   → me = "CCD" (Claude Code Desktop). Otherwise → me = "CC" (vanilla
   Claude Code CLI in a terminal).

The process-tree check is the canonical signal for CC vs CCD. Don't rely
on tool-list heuristics — those are user-configurable. The bundle path
in the process ancestry is set at launch and not spoofable in practice.

Use the same `me` for every call in this session. Never spoof another role.

# Tools

| Tool | Args | Returns |
|------|------|---------|
| `inbox` | `me` | `{incoming, outgoing}` — state snapshot |
| `wait_any` | `me`, `timeout=30` | next event for me — `incoming_queued` / `outgoing_question` / `outgoing_done` / `incoming_answer` / `loop_closed` / `still_waiting` |
| `dispatch` | `me`, `to`, `context` | `{task_id}` |
| `respond` | `me`, `task_id`, `answer` | `{ok: true}` (dispatcher answers worker's question) |
| `report` | `me`, `task_id`, `summary`, `status="completed"` | `{ok: true}` (worker finalizes) |
| `propose_close` | `me`, `summary` | `{you_close: true, summary_id, higher_priority_online?, note?}` (first-mover wins) |
| `pull` (legacy) | `me`, `timeout=30` | task-targeted long-poll — superseded by `wait_any` |
| `wait` (legacy) | `me`, `task_id`, `timeout=30` | task-scoped long-poll — superseded by `wait_any` |
| `ask` (legacy) | `me`, `task_id`, `question`, `timeout=30` | worker→dispatcher question with synchronous wait — pair with `wait_any` instead |

`me`/`to` ∈ {"Chat", "Cowork", "CC"}. `status` ∈ {"completed", "failed",
"blocked", "rejected"}.

# Recommended pattern: event-driven loop with `wait_any`

```
loop:
    e = wait_any(me)
    case e.type:
        "incoming_queued"   → service as worker; ask?/report
        "outgoing_question" → respond
        "outgoing_done"     → surface to Alta
        "incoming_answer"   → continue work
        "still_waiting"     → call inbox(me); if outgoing has stale task,
                              emit a one-line user notice; continue loop
```

No dispatcher/worker mode commitment up front — react to events as they
arrive. Concurrent dispatcher-of-A + worker-of-B falls out naturally.

# Loop close (default mode)

When `inbox` is empty AND you've seen ~5 consecutive `still_waiting`,
call `propose_close(me, summary)`. **First-mover wins** — whoever calls
first persists the summary and closes the loop. Priority (Chat > Cowork
> CCD > CC) is informational only; if `higher_priority_online` is in
the response, that's a hint but not a block. Other peers receive a
`loop_closed` event in their next `wait_any` and post a received-summary
template pointing to your surface.

`/standby` (or "常驻同步" / "long-term sync") trigger skips this — stay
in `wait_any` indefinitely without proposing close.

Every long-poll (`wait_any`, plus legacy `pull`/`wait`/`ask`) returns
`{still_waiting: true}` (or `{type: "still_waiting"}`) on timeout — NOT
an error. Always loop. Caps live in the SKILL, not the protocol.

# Routing & identity

- `dispatch(me, to, ...)` — me is sender, to is target. Server records both.
- `pull(me, ...)` — pulls tasks where `assigned_to == me`.
- `wait(me, task_id, ...)` — only the dispatcher of that task may wait.
- `ask(me, task_id, ...)` — only the worker (`assigned_to`) may ask.
- `respond(me, task_id, ...)` — only the dispatcher may respond.
- `report(me, task_id, ...)` — only the worker may report.

The server enforces these. If `me` doesn't match the role on the task, you
get an error.

# Style for human-visible text

Prefix `summary`, `question`, and `answer` with `[<me> → <to>]` so Alta can
see the routing in her chat (e.g. `[Cowork → Chat] Filed 3 notes under …`).
"""


mcp = FastMCP(
    "collab-loop",
    instructions=SERVER_INSTRUCTIONS,
    host=os.environ.get("LOOP_HOST", "127.0.0.1"),
    port=int(os.environ.get("LOOP_PORT", "8765")),
    transport_security=_transport_security,
    # Stateless mode: each tool call is an independent session. Eliminates
    # session-level multiplexing bugs we saw in smoke #2 (409 Conflicts +
    # cross-routed responses between concurrent inflight calls). Trade-off:
    # slightly higher per-call overhead, but the protocol is low-frequency.
    stateless_http=True,
)


# ─── Symmetric tools ───────────────────────────────────────────────────


@mcp.tool()
async def inbox(me: str) -> dict:
    """Read-only snapshot of task state relevant to `me`. Call on entry to
    decide whether to act as worker (pull/ask/report) or dispatcher
    (wait/respond) — instead of pre-committing to a role from the trigger
    phrase.

    Returns:
      {
        "incoming": [  # tasks assigned to me (I'm the worker)
          {task_id, dispatched_by, status, context_preview, age_seconds,
           latest_dispatcher_msg?}
        ],
        "outgoing": [  # tasks I dispatched (I'm the dispatcher)
          {task_id, assigned_to, status, age_seconds, latest_worker_msg?}
        ],
      }

    `status` ∈ {"queued", "in_progress", "awaiting_response"}. Done tasks
    are excluded. `latest_*_msg` is included when status="awaiting_response"
    (worker is waiting for dispatcher's answer, or dispatcher should
    surface worker's question).
    """
    if err := _check_role(me):
        return err
    _touch_presence(me)

    now = time.time()
    with db() as conn:
        incoming_rows = conn.execute(
            "SELECT id, dispatched_by, status, context, created_at "
            "FROM tasks WHERE assigned_to=? AND status != 'done' "
            "ORDER BY created_at",
            (me,),
        ).fetchall()
        outgoing_rows = conn.execute(
            "SELECT id, assigned_to, status, created_at "
            "FROM tasks WHERE dispatched_by=? AND status != 'done' "
            "ORDER BY created_at",
            (me,),
        ).fetchall()

        def latest_msg(task_id: str, to_role: str):
            row = conn.execute(
                "SELECT type, content FROM messages "
                "WHERE task_id=? AND to_role=? ORDER BY id DESC LIMIT 1",
                (task_id, to_role),
            ).fetchone()
            return dict(row) if row else None

        def preview(s, n=240):
            s = s.replace("\n", " ")
            return s if len(s) <= n else s[:n] + "…"

        incoming = []
        for r in incoming_rows:
            entry = {
                "task_id": r["id"],
                "dispatched_by": r["dispatched_by"],
                "status": r["status"],
                "context_preview": preview(r["context"]),
                "age_seconds": int(now - r["created_at"]),
            }
            if r["status"] == "awaiting_response":
                # I (worker) asked, dispatcher hasn't answered. Show my own question.
                msg = latest_msg(r["id"], r["dispatched_by"])
                if msg:
                    entry["my_pending_question"] = preview(msg["content"])
            incoming.append(entry)

        outgoing = []
        for r in outgoing_rows:
            entry = {
                "task_id": r["id"],
                "assigned_to": r["assigned_to"],
                "status": r["status"],
                "age_seconds": int(now - r["created_at"]),
            }
            if r["status"] == "awaiting_response":
                # Worker asked me a question I haven't answered. Show it.
                msg = latest_msg(r["id"], me)
                if msg and msg["type"] == "question":
                    entry["worker_question"] = preview(msg["content"])
            outgoing.append(entry)

    return {"incoming": incoming, "outgoing": outgoing}


@mcp.tool()
async def wait_any(me: str, timeout: int = 30) -> dict:
    """Long-poll for the next event involving `me`, across ALL tasks
    (whether `me` is dispatcher or worker on them). Replaces the
    pull/wait/ask trinity for event-driven loops — agent doesn't have to
    decide its role up front, just reacts to events as they arrive.

    Returns one of:
      {type: "incoming_queued",   task_id, context, dispatched_by}
        — Someone dispatched a task to you. Server has atomically claimed
          it (status: queued → in_progress). You should service it as
          worker.
      {type: "outgoing_question", task_id, question, from_role}
        — Worker on a task you dispatched is asking you a question. You
          should `respond`.
      {type: "outgoing_done",     task_id, summary, status, from_role}
        — Worker finished a task you dispatched. Surface to Alta.
      {type: "incoming_answer",   task_id, answer, from_role}
        — Dispatcher answered your pending `ask`. Continue work.
      {type: "still_waiting"}
        — Timed out. Loop again.

    Priority when multiple events ready: incoming_queued first (so
    workers get work fastest), then messages by id ascending (FIFO).

    Cursor: server tracks per-role `last_seen_msg_id`. Each returned
    message bumps the cursor so you don't re-receive it. Mixing
    `wait_any` with the legacy `wait`/`pull`/`ask` trinity on the same
    role's session is undefined — pick one pattern.
    """
    if err := _check_role(me):
        return err
    _touch_presence(me)

    deadline = time.monotonic() + timeout
    while True:
        # 0. Highest-highest priority: an unack'd loop_close addressed to me.
        close = _latest_unseen_close_for(me)
        if close:
            _ack_close(me, close["id"])
            return {
                "type": "loop_closed",
                "closer": close["closer"],
                "summary": close["summary"],
            }

        with db() as conn:
            # 1. Highest priority: queued task assigned to me. Claim atomically.
            queued = conn.execute(
                "SELECT id, context, dispatched_by FROM tasks "
                "WHERE assigned_to=? AND status='queued' "
                "ORDER BY created_at LIMIT 1",
                (me,),
            ).fetchone()
            if queued:
                cur = conn.execute(
                    "UPDATE tasks SET status='in_progress', updated_at=? "
                    "WHERE id=? AND status='queued'",
                    (time.time(), queued["id"]),
                )
                if cur.rowcount == 1:
                    return {
                        "type": "incoming_queued",
                        "task_id": queued["id"],
                        "context": queued["context"],
                        "dispatched_by": queued["dispatched_by"],
                    }
                continue  # raced with another puller, retry

            # 2. Next message addressed to me beyond the per-role cursor.
            row = conn.execute(
                "SELECT last_seen_msg_id FROM cursors WHERE role=?", (me,)
            ).fetchone()
            cursor_id = row["last_seen_msg_id"] if row else 0

            msg = conn.execute(
                "SELECT id, task_id, from_role, type, content "
                "FROM messages WHERE to_role=? AND id > ? "
                "ORDER BY id LIMIT 1",
                (me, cursor_id),
            ).fetchone()
            if msg:
                _bump_role_cursor(me, msg["id"])
                task = conn.execute(
                    "SELECT dispatched_by, assigned_to, outcome FROM tasks WHERE id=?",
                    (msg["task_id"],),
                ).fetchone()
                if not task:
                    continue  # task vanished (pruned mid-flight), skip

                if msg["type"] == "question":
                    return {
                        "type": "outgoing_question",
                        "task_id": msg["task_id"],
                        "question": msg["content"],
                        "from_role": msg["from_role"],
                    }
                if msg["type"] == "answer":
                    return {
                        "type": "incoming_answer",
                        "task_id": msg["task_id"],
                        "answer": msg["content"],
                        "from_role": msg["from_role"],
                    }
                if msg["type"] == "done":
                    return {
                        "type": "outgoing_done",
                        "task_id": msg["task_id"],
                        "summary": msg["content"],
                        "status": task["outcome"] or "completed",
                        "from_role": msg["from_role"],
                    }
                # Unknown type — skip (cursor already bumped)
                continue

        # 3. Room broadcast messages (not from self)
        room_msgs = _unread_room_msgs(me, limit=1)
        if room_msgs:
            rm = room_msgs[0]
            _bump_room_cursor(me, rm["id"])
            return {
                "type": "room_message",
                "sender": rm["sender"],
                "content": rm["content"],
                "msg_id": rm["id"],
            }

        remaining = deadline - time.monotonic()
        if remaining <= 0:
            return {"type": "still_waiting"}
        c = cond()
        try:
            async with c:
                await asyncio.wait_for(c.wait(), timeout=remaining)
        except asyncio.TimeoutError:
            return {"type": "still_waiting"}


@mcp.tool()
async def propose_close(me: str, summary: str) -> dict:
    """Propose to close the current loop and post the canonical summary.

    Call this when:
      - Your inbox.incoming and inbox.outgoing are both empty
      - You've seen ~5 consecutive `still_waiting` from `wait_any`
      - You're not in standby mode
      - OR: `peers(me)` shows you are the only role online (everyone
        else dropped) — exit cleanly rather than wait_any forever

    First-mover-writes: whoever calls first persists the summary and the
    loop closes under their name. Other online peers (whose presence
    segment predates the close) receive a `{type: "loop_closed",
    closer, summary}` event in their next `wait_any` and exit.

    Priority (Chat > Cowork > CCD > CC) is no longer blocking — peers
    don't reach the close threshold synchronously, and forcing the
    first-mover to defer used to drop their summary on the floor. If a
    higher-priority peer is online, the response includes
    `higher_priority_online` as a hint, but the summary is still
    recorded.

    Returns:
      - `{ok: true, you_close: true, summary_id}` — you close.
        Post the closer-template message to Alta.
      - `{ok: true, you_close: true, summary_id, higher_priority_online,
        note}` — you close, but a higher-priority peer is online; first
        mover still wins.
      - `{ok: false, error}` — invalid me or empty summary.
    """
    if err := _check_role(me):
        return err
    _touch_presence(me)

    summary = (summary or "").strip()
    if not summary:
        return {"ok": False, "error": "summary cannot be empty"}

    # First-mover-writes: whoever calls propose_close first persists the
    # summary, regardless of priority. Originally this branch deferred to
    # higher-priority online peers, but peers don't hit the close
    # threshold synchronously — forcing the first-mover to defer dropped
    # their summary and left the loop hanging when the "designated"
    # closer never reached threshold. See ideas.md Bug A (2026-04-27 16:50).
    #
    # `_close_priority` is still computed for the response so the caller
    # knows whether a higher-priority peer was online — informational, not
    # blocking. Future "peer-consensus close" (ideas.md option A) can build
    # on this without re-introducing the silent-drop path.
    online = _online_roles()
    online.add(me)
    me_key = _close_priority(me)
    higher_online = sorted(
        (r for r in online if r != me and _close_priority(r) < me_key),
        key=_close_priority,
    )

    now = time.time()
    with db() as conn:
        cur = conn.execute(
            "INSERT INTO loop_summaries (closer, summary, created_at, last_seen_by) "
            "VALUES (?, ?, ?, ?)",
            (me, summary, now, me),  # closer pre-acks itself
        )
        summary_id = cur.lastrowid
    await notify()
    response = {"ok": True, "you_close": True, "summary_id": summary_id}
    if higher_online:
        response["higher_priority_online"] = higher_online
        response["note"] = (
            f"first-mover wins: summary recorded under {me}. "
            f"higher-priority peer(s) {higher_online} online — they will "
            f"receive loop_closed via wait_any."
        )
    return response


@mcp.tool()
async def peers(me: str) -> dict:
    """Snapshot of which collaborator roles are currently online.

    A role counts as "online" if it has called any Aleph tool within the
    last 90 seconds (PRESENCE_WINDOW_SEC). Useful for:
      - Deciding whether to `propose_close` (e.g. only `me` is online →
        no point holding the loop further; close it).
      - Surfacing presence to Alta ("CC dropped, Chat and CCD still here").
      - Avoiding dispatch to a role that isn't around to service it.
      - On entry: detecting that another instance of your base role is
        already in the loop (use `pre_self` — see below — and pick a
        digit-suffixed role to join as a second seat).

    Calling this tool itself touches `me`'s presence, so `me` will always
    appear in `online`. `pre_self` is the snapshot taken *before* that
    touch — that's the field to consult on entry to decide whether your
    base role is already taken.

    Returns:
      {
        "online":   [role, ...],  # within last 90s, after this call
        "pre_self": [role, ...],  # online snapshot before this call's touch
        "offline":  [base, ...],  # base roles with no live instance
        "me_alone": bool,         # online == [me]
      }
    """
    if err := _check_role(me):
        return err
    pre_self = sorted(_online_roles())
    _touch_presence(me)

    online = _online_roles()
    online_list = sorted(online)
    live_bases = {_base_role(r) for r in online}
    offline_list = sorted(b for b in BASE_ROLES if b not in live_bases)
    return {
        "online": online_list,
        "pre_self": pre_self,
        "offline": offline_list,
        "me_alone": online_list == [me],
    }


@mcp.tool()
async def dispatch(me: str, to: str, context: str) -> dict:
    """Hand off a task to another collaborator.

    `me` is your role (Chat/Cowork/CC). `to` is the target role. `context`
    is the full uncompressed natural-language briefing. Returns task_id.
    """
    if err := _check_role(me):
        return err
    _touch_presence(me)
    if err := _check_role(to):
        return {
            "ok": False,
            "error": (
                f"`to` must match <base><digits?> where base is one of "
                f"{BASE_ROLES} (e.g. Chat, Chat2, CC3); got {to!r}"
            ),
        }
    if me == to:
        return {"ok": False, "error": "cannot dispatch to self"}

    task_id = uuid.uuid4().hex[:12]
    now = time.time()
    with db() as conn:
        conn.execute(
            "INSERT INTO tasks "
            "(id, status, context, dispatched_by, assigned_to, created_at, updated_at) "
            "VALUES (?, 'queued', ?, ?, ?, ?, ?)",
            (task_id, context, me, to, now, now),
        )
    await notify()
    return {"task_id": task_id, "dispatched_by": me, "assigned_to": to}


@mcp.tool()
async def pull(me: str, timeout: int = 30) -> dict:
    """Long-poll for the next task addressed to `me`.

    Returns {task_id, context, dispatched_by} or {still_waiting: true} on
    timeout. Atomically claims the task by transitioning its status
    queued → in_progress. Loop on still_waiting.
    """
    if err := _check_role(me):
        return err
    _touch_presence(me)

    deadline = time.monotonic() + timeout
    while True:
        now = time.time()
        with db() as conn:
            row = conn.execute(
                "SELECT id, context, dispatched_by FROM tasks "
                "WHERE status='queued' AND assigned_to=? "
                "ORDER BY created_at LIMIT 1",
                (me,),
            ).fetchone()
            if row:
                cur = conn.execute(
                    "UPDATE tasks SET status='in_progress', updated_at=? "
                    "WHERE id=? AND status='queued'",
                    (now, row["id"]),
                )
                if cur.rowcount == 1:
                    return {
                        "task_id": row["id"],
                        "context": row["context"],
                        "dispatched_by": row["dispatched_by"],
                    }
                continue  # raced with another puller

        remaining = deadline - time.monotonic()
        if remaining <= 0:
            return {"still_waiting": True}
        c = cond()
        try:
            async with c:
                await asyncio.wait_for(c.wait(), timeout=remaining)
        except asyncio.TimeoutError:
            return {"still_waiting": True}


@mcp.tool()
async def wait(me: str, task_id: str, timeout: int = 30) -> dict:
    """Dispatcher long-polls for the next event on a task it dispatched.

    Returns one of:
      {type: "question",      question: str,  from_role: str}
      {type: "done",          summary:  str,  status: str, from_role: str}
      {type: "still_waiting"}
    """
    if err := _check_role(me):
        return err
    _touch_presence(me)

    task = _task_row(task_id)
    if not task:
        return {"type": "error", "error": f"unknown task_id {task_id}"}
    if task["dispatched_by"] != me:
        return {
            "type": "error",
            "error": f"only dispatcher ({task['dispatched_by']}) can wait on this task; you are {me}",
        }

    deadline = time.monotonic() + timeout
    while True:
        last = _last_seen(task_id)
        msg = _next_msg_to(task_id, me, last)
        if msg:
            _bump_last_seen(task_id, msg["id"])
            _bump_role_cursor(me, msg["id"])  # keep per-role cursor in sync for wait_any
            if msg["type"] == "done":
                row = _task_row(task_id)
                outcome = row["outcome"] if row and row["outcome"] else "completed"
                return {
                    "type": "done",
                    "summary": msg["content"],
                    "status": outcome,
                    "from_role": msg["from_role"],
                }
            if msg["type"] == "question":
                return {
                    "type": "question",
                    "question": msg["content"],
                    "from_role": msg["from_role"],
                }
            return {"type": msg["type"], "content": msg["content"]}

        remaining = deadline - time.monotonic()
        if remaining <= 0:
            return {"type": "still_waiting"}
        c = cond()
        try:
            async with c:
                await asyncio.wait_for(c.wait(), timeout=remaining)
        except asyncio.TimeoutError:
            return {"type": "still_waiting"}


@mcp.tool()
async def ask(me: str, task_id: str, question: str, timeout: int = 30) -> dict:
    """Worker asks the dispatcher a question. Long-polls for the answer.

    Returns {answer: str} on success, {still_waiting: true} on timeout.
    Loop on still_waiting until you get an answer or decide to give up.
    """
    if err := _check_role(me):
        return err
    _touch_presence(me)

    task = _task_row(task_id)
    if not task:
        return {"ok": False, "error": f"unknown task_id {task_id}"}
    if task["assigned_to"] != me:
        return {
            "ok": False,
            "error": f"only worker ({task['assigned_to']}) can ask on this task; you are {me}",
        }

    dispatcher = task["dispatched_by"]
    now = time.time()
    with db() as conn:
        cur = conn.execute(
            "INSERT INTO messages (task_id, from_role, to_role, type, content, ts) "
            "VALUES (?, ?, ?, 'question', ?, ?)",
            (task_id, me, dispatcher, question, now),
        )
        q_id = cur.lastrowid
        conn.execute(
            "UPDATE tasks SET status='awaiting_response', updated_at=? WHERE id=?",
            (now, task_id),
        )
    await notify()

    deadline = time.monotonic() + timeout
    while True:
        with db() as conn:
            row = conn.execute(
                "SELECT id, content FROM messages "
                "WHERE task_id=? AND to_role=? AND type='answer' AND id>? "
                "ORDER BY id LIMIT 1",
                (task_id, me, q_id),
            ).fetchone()
            if row:
                _bump_role_cursor(me, row["id"])  # keep per-role cursor in sync for wait_any
                return {"answer": row["content"]}

        remaining = deadline - time.monotonic()
        if remaining <= 0:
            return {"still_waiting": True}
        c = cond()
        try:
            async with c:
                await asyncio.wait_for(c.wait(), timeout=remaining)
        except asyncio.TimeoutError:
            return {"still_waiting": True}


@mcp.tool()
async def respond(me: str, task_id: str, answer: str) -> dict:
    """Dispatcher answers the worker's pending question."""
    if err := _check_role(me):
        return err
    _touch_presence(me)

    task = _task_row(task_id)
    if not task:
        return {"ok": False, "error": f"unknown task_id {task_id}"}
    if task["dispatched_by"] != me:
        return {
            "ok": False,
            "error": f"only dispatcher ({task['dispatched_by']}) can respond on this task; you are {me}",
        }

    worker = task["assigned_to"]
    now = time.time()
    with db() as conn:
        conn.execute(
            "INSERT INTO messages (task_id, from_role, to_role, type, content, ts) "
            "VALUES (?, ?, ?, 'answer', ?, ?)",
            (task_id, me, worker, answer, now),
        )
        conn.execute(
            "UPDATE tasks SET status='in_progress', updated_at=? WHERE id=?",
            (now, task_id),
        )
    await notify()
    return {"ok": True}


@mcp.tool()
async def report(me: str, task_id: str, summary: str, status: str = "completed") -> dict:
    """Worker finalizes the task. Final worker→dispatcher message.

    status:
      "completed" — work finished.
      "blocked"   — needs out-of-band action from Alta (folder access, etc).
                    Dispatcher should surface and not auto-retry.
      "failed"    — tried but couldn't finish (partial / unrecoverable error).
                    Dispatcher MAY retry / reformulate.
      "rejected"  — judged the task unreasonable (destructive, principle
                    violation, out of scope) and did not attempt. Dispatcher
                    should NOT auto-retry. Use sparingly.
    """
    if err := _check_role(me):
        return err
    _touch_presence(me)
    if status not in VALID_OUTCOMES:
        return {"ok": False, "error": f"status must be one of {VALID_OUTCOMES}"}

    task = _task_row(task_id)
    if not task:
        return {"ok": False, "error": f"unknown task_id {task_id}"}
    if task["assigned_to"] != me:
        return {
            "ok": False,
            "error": f"only worker ({task['assigned_to']}) can report on this task; you are {me}",
        }

    dispatcher = task["dispatched_by"]
    now = time.time()
    with db() as conn:
        conn.execute(
            "INSERT INTO messages (task_id, from_role, to_role, type, content, ts) "
            "VALUES (?, ?, ?, 'done', ?, ?)",
            (task_id, me, dispatcher, summary, now),
        )
        conn.execute(
            "UPDATE tasks SET status='done', outcome=?, summary=?, updated_at=? WHERE id=?",
            (status, summary, now, task_id),
        )
    await notify()
    return {"ok": True}


# ── Room (broadcast channel) ────────────────────────────────────────

def _bump_room_cursor(role: str, msg_id: int):
    with db() as conn:
        conn.execute(
            "INSERT INTO room_cursors (role, last_seen_msg_id) VALUES (?, ?) "
            "ON CONFLICT(role) DO UPDATE SET last_seen_msg_id=excluded.last_seen_msg_id "
            "WHERE excluded.last_seen_msg_id > room_cursors.last_seen_msg_id",
            (role, msg_id),
        )


def _unread_room_msgs(role: str, limit: int = 20):
    with db() as conn:
        cursor_row = conn.execute(
            "SELECT last_seen_msg_id FROM room_cursors WHERE role=?", (role,)
        ).fetchone()
        after = cursor_row["last_seen_msg_id"] if cursor_row else 0
        rows = conn.execute(
            "SELECT id, sender, content, created_at FROM room "
            "WHERE id > ? ORDER BY id LIMIT ?",
            (after, limit),
        ).fetchall()
        return [dict(r) for r in rows]


@mcp.tool()
async def room_send(me: str, content: str) -> dict:
    """Send a message to the shared room. All peers see it via wait_any
    (event type 'room_message') or room_read. Broadcast — no 'to' needed."""
    if err := _check_role(me):
        return err
    _touch_presence(me)
    content = (content or "").strip()
    if not content:
        return {"ok": False, "error": "content cannot be empty"}
    now = time.time()
    with db() as conn:
        cur = conn.execute(
            "INSERT INTO room (sender, content, created_at) VALUES (?, ?, ?)",
            (me, content, now),
        )
        msg_id = cur.lastrowid
    # Auto-bump sender's cursor so they don't re-read their own message
    _bump_room_cursor(me, msg_id)
    await notify()
    return {"ok": True, "msg_id": msg_id}


@mcp.tool()
async def room_read(me: str, limit: int = 50) -> dict:
    """Read recent room messages. Returns all messages after your cursor.
    Cursor auto-advances so you don't re-read."""
    if err := _check_role(me):
        return err
    _touch_presence(me)
    msgs = _unread_room_msgs(me, limit)
    if msgs:
        _bump_room_cursor(me, msgs[-1]["id"])
    return {"messages": msgs, "count": len(msgs)}


def main():
    init_db()
    prune_old_tasks()
    transport = os.environ.get("LOOP_TRANSPORT", "streamable-http")
    mcp.run(transport=transport)


if __name__ == "__main__":
    main()
