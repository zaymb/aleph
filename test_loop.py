"""End-to-end test of the symmetric Collaborator protocol.

Spins up the server, runs a mock Chat (initiator) and a mock Cowork (worker)
concurrently. Verifies a full round of:

    Chat.dispatch(to=Cowork)
    → Cowork.pull(me=Cowork)
    → Cowork.ask(me=Cowork, q1)  →  Chat.wait → Chat.respond
    → Cowork.ask(me=Cowork, q2)  →  Chat.wait → Chat.respond
    → Cowork.report(me=Cowork)   →  Chat.wait → done.

Also smoke-tests routing enforcement (worker can't wait, dispatcher can't ask).
"""

from __future__ import annotations

import asyncio
import os
import signal
import socket
import subprocess
import sys
import time
from contextlib import closing
from pathlib import Path

from mcp import ClientSession
from mcp.client.streamable_http import streamablehttp_client


HERE = Path(__file__).parent


def free_port() -> int:
    with closing(socket.socket(socket.AF_INET, socket.SOCK_STREAM)) as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


async def wait_until_listening(host: str, port: int, timeout: float = 10.0):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        try:
            r, w = await asyncio.open_connection(host, port)
            w.close()
            await w.wait_closed()
            return
        except OSError:
            await asyncio.sleep(0.1)
    raise RuntimeError(f"server never came up on {host}:{port}")


def unwrap(result) -> dict:
    """FastMCP returns CallToolResult; pull the structured content out."""
    if result.structuredContent is not None:
        sc = result.structuredContent
        if isinstance(sc, dict) and set(sc.keys()) == {"result"}:
            return sc["result"]
        return sc
    if result.content:
        import json
        for c in result.content:
            if hasattr(c, "text"):
                try:
                    return json.loads(c.text)
                except Exception:
                    return {"text": c.text}
    return {}


async def chat_role(url: str, log):
    async with streamablehttp_client(url) as (read, write, _):
        async with ClientSession(read, write) as s:
            await s.initialize()
            log("chat: dispatching")
            r = unwrap(await s.call_tool(
                "dispatch",
                {
                    "me": "Chat",
                    "to": "Cowork",
                    "context": "[Chat → Cowork] rewrite README.md to add a usage section",
                },
            ))
            task_id = r["task_id"]
            log(f"chat: task_id={task_id}")

            answers = iter([
                "[Chat → Cowork] use markdown headings, target audience is developers",
                "[Chat → Cowork] no, that's all",
            ])

            for _ in range(20):  # cap retries
                upd = unwrap(await s.call_tool(
                    "wait", {"me": "Chat", "task_id": task_id, "timeout": 5},
                ))
                log(f"chat: update={upd}")
                t = upd.get("type")
                if t == "question":
                    a = next(answers)
                    log(f"chat: answering: {a}")
                    unwrap(await s.call_tool(
                        "respond",
                        {"me": "Chat", "task_id": task_id, "answer": a},
                    ))
                elif t == "done":
                    log(f"chat: DONE — summary: {upd.get('summary')}")
                    return upd
                elif t == "still_waiting":
                    log("chat: still_waiting, looping")
                    continue
                else:
                    raise RuntimeError(f"unexpected update: {upd}")
            raise RuntimeError("chat: hit retry cap")


async def cowork_role(url: str, log):
    async with streamablehttp_client(url) as (read, write, _):
        async with ClientSession(read, write) as s:
            await s.initialize()
            log("cowork: pulling task")
            for _ in range(20):
                r = unwrap(await s.call_tool("pull", {"me": "Cowork", "timeout": 5}))
                if r.get("still_waiting"):
                    log("cowork: still_waiting on pull, looping")
                    continue
                break
            else:
                raise RuntimeError("cowork: never pulled a task")
            log(f"cowork: pulled {r}")
            task_id = r["task_id"]
            assert r["dispatched_by"] == "Chat", r

            log("cowork: asking Q1")
            a1 = unwrap(await s.call_tool(
                "ask",
                {"me": "Cowork", "task_id": task_id,
                 "question": "[Cowork → Chat] what style for the README?",
                 "timeout": 30},
            ))
            log(f"cowork: A1={a1}")

            log("cowork: asking Q2")
            a2 = unwrap(await s.call_tool(
                "ask",
                {"me": "Cowork", "task_id": task_id,
                 "question": "[Cowork → Chat] anything else to include?",
                 "timeout": 30},
            ))
            log(f"cowork: A2={a2}")

            log("cowork: reporting done")
            unwrap(await s.call_tool(
                "report",
                {"me": "Cowork", "task_id": task_id,
                 "summary": "[Cowork → Chat] README rewritten with developer-focused usage section."},
            ))
            return {"a1": a1, "a2": a2}


async def routing_smoke(url: str, log):
    """Verify server enforces role restrictions."""
    async with streamablehttp_client(url) as (read, write, _):
        async with ClientSession(read, write) as s:
            await s.initialize()
            # dispatch as CC for an isolated test task
            r = unwrap(await s.call_tool(
                "dispatch",
                {"me": "CC", "to": "Cowork", "context": "[routing smoke]"},
            ))
            tid = r["task_id"]

            # CC is dispatcher — should NOT be able to ask
            r = unwrap(await s.call_tool(
                "ask",
                {"me": "CC", "task_id": tid, "question": "should fail", "timeout": 1},
            ))
            assert r.get("ok") is False and "worker" in r.get("error", ""), r
            log(f"routing: CC.ask → correctly rejected: {r}")

            # Chat is bystander — should NOT be able to wait
            r = unwrap(await s.call_tool(
                "wait",
                {"me": "Chat", "task_id": tid, "timeout": 1},
            ))
            assert r.get("type") == "error" and "dispatcher" in r.get("error", ""), r
            log(f"routing: Chat.wait on CC's task → correctly rejected: {r}")

            # invalid role
            r = unwrap(await s.call_tool(
                "dispatch",
                {"me": "Mobile", "to": "Cowork", "context": "x"},
            ))
            assert r.get("ok") is False and "must be one of" in r.get("error", ""), r
            log(f"routing: invalid `me` → correctly rejected: {r}")

            # self-dispatch
            r = unwrap(await s.call_tool(
                "dispatch",
                {"me": "Chat", "to": "Chat", "context": "x"},
            ))
            assert r.get("ok") is False and "self" in r.get("error", ""), r
            log(f"routing: self-dispatch → correctly rejected: {r}")


async def wait_any_dispatcher(url: str, log):
    """Chat-as-dispatcher: dispatch + wait_any-driven event loop."""
    async with streamablehttp_client(url) as (read, write, _):
        async with ClientSession(read, write) as s:
            await s.initialize()
            log("dispatcher: dispatching CCD task")
            r = unwrap(await s.call_tool(
                "dispatch",
                {"me": "Chat", "to": "CCD", "context": "[Chat → CCD] format the changelog file with bullets"},
            ))
            tid = r["task_id"]
            log(f"dispatcher: task_id={tid}")

            for _ in range(20):
                e = unwrap(await s.call_tool(
                    "wait_any", {"me": "Chat", "timeout": 5},
                ))
                log(f"dispatcher: event={e}")
                t = e.get("type")
                if t == "outgoing_done":
                    assert e["task_id"] == tid, e
                    return {"last_event": "outgoing_done", "status": e["status"], "summary": e["summary"], "from_role": e["from_role"]}
                elif t == "still_waiting":
                    continue
                else:
                    raise RuntimeError(f"unexpected: {e}")
            raise RuntimeError("dispatcher: hit retry cap")


async def wait_any_worker(url: str, log):
    """CCD-as-worker: pure wait_any event loop, no ask."""
    async with streamablehttp_client(url) as (read, write, _):
        async with ClientSession(read, write) as s:
            await s.initialize()
            events = []
            for _ in range(20):
                e = unwrap(await s.call_tool(
                    "wait_any", {"me": "CCD", "timeout": 5},
                ))
                log(f"worker: event={e}")
                t = e.get("type")
                if t == "incoming_queued":
                    events.append("incoming_queued")
                    tid = e["task_id"]
                    assert e["dispatched_by"] == "Chat", e
                    # Do the work directly (no ask), then report
                    unwrap(await s.call_tool(
                        "report",
                        {"me": "CCD", "task_id": tid,
                         "summary": "[CCD → Chat] formatted changelog with bullets, all good."},
                    ))
                    return {"events": events, "task_id": tid}
                elif t == "still_waiting":
                    continue
                else:
                    raise RuntimeError(f"unexpected: {e}")
            raise RuntimeError("worker: hit retry cap")


async def main():
    port = free_port()
    db_path = HERE / "test_loop.db"
    if db_path.exists():
        db_path.unlink()
    env = {
        **os.environ,
        "LOOP_PORT": str(port),
        "LOOP_DB": str(db_path),
        "LOOP_TRANSPORT": "streamable-http",
    }
    proc = subprocess.Popen(
        [sys.executable, str(HERE / "server.py")],
        env=env,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
    )
    try:
        await wait_until_listening("127.0.0.1", port)
        url = f"http://127.0.0.1:{port}/mcp/"
        events = []
        def log(s):
            events.append((time.monotonic(), s))
            print(s, flush=True)

        # Round 1: Chat→Cowork happy path
        chat_task = asyncio.create_task(chat_role(url, log))
        cowork_task = asyncio.create_task(cowork_role(url, log))
        chat_result, cowork_result = await asyncio.wait_for(
            asyncio.gather(chat_task, cowork_task), timeout=30,
        )
        print("\n=== ROUND 1 RESULTS ===")
        print("chat:", chat_result)
        print("cowork:", cowork_result)
        assert chat_result.get("type") == "done", chat_result
        assert chat_result.get("status") == "completed", chat_result
        assert chat_result.get("from_role") == "Cowork", chat_result
        assert "use markdown" in cowork_result["a1"]["answer"]
        assert "no" in cowork_result["a2"]["answer"]

        # Round 2: routing enforcement
        print("\n=== ROUND 2: routing checks ===")
        await asyncio.wait_for(routing_smoke(url, log), timeout=10)

        # Round 3: event-driven wait_any flow (CCD ↔ Chat)
        print("\n=== ROUND 3: wait_any event-driven ===")
        chat_task = asyncio.create_task(wait_any_dispatcher(url, log))
        ccd_task = asyncio.create_task(wait_any_worker(url, log))
        chat_r3, ccd_r3 = await asyncio.wait_for(
            asyncio.gather(chat_task, ccd_task), timeout=30,
        )
        print("dispatcher (Chat):", chat_r3)
        print("worker (CCD):", ccd_r3)
        assert chat_r3["last_event"] == "outgoing_done", chat_r3
        assert chat_r3["status"] == "completed", chat_r3
        assert chat_r3["from_role"] == "CCD", chat_r3
        assert ccd_r3["events"] == ["incoming_queued"], ccd_r3

        print("\nOK")
    finally:
        proc.send_signal(signal.SIGINT)
        try:
            out, _ = proc.communicate(timeout=5)
        except subprocess.TimeoutExpired:
            proc.kill()
            out, _ = proc.communicate()
        if out:
            print("\n--- server log ---")
            print(out.decode(errors="replace"))


if __name__ == "__main__":
    asyncio.run(main())
