"""Aleph realtime dashboard — native Tkinter chat window.

Alta can join the loop as 'Human' and talk directly to any peer.
Polls wait_any in a background thread; dispatches from the input box.

Usage:
    uv run python dashboard.py
"""

import asyncio
import json
import queue
import re
import threading
import tkinter as tk
from tkinter import ttk, scrolledtext
from datetime import datetime

# ── MCP client ──────────────────────────────────────────────────────

URL = "http://127.0.0.1:8765/mcp"
ME = "Human"

import httpx


def _parse_sse_result(text: str):
    """Extract JSON result from an SSE response body."""
    for line in text.split("\n"):
        if line.startswith("data: "):
            try:
                msg = json.loads(line[6:])
                if "result" in msg:
                    return msg["result"]
                if "error" in msg:
                    return {"error": msg["error"]}
            except json.JSONDecodeError:
                continue
    return None


class AlephClient:
    """Thin synchronous wrapper around MCP streamable-http."""

    def __init__(self, url: str = URL):
        self.url = url
        self.session_id = None
        self.client = httpx.Client(timeout=60)
        self._msg_id = 0

    def _next_id(self):
        self._msg_id += 1
        return self._msg_id

    def _headers(self):
        h = {
            "Content-Type": "application/json",
            "Accept": "application/json, text/event-stream",
        }
        if self.session_id:
            h["Mcp-Session-Id"] = self.session_id
        return h

    def _call(self, method: str, params: dict = None):
        body = {
            "jsonrpc": "2.0",
            "id": self._next_id(),
            "method": method,
        }
        if params:
            body["params"] = params
        resp = self.client.post(self.url, json=body, headers=self._headers())
        # Capture session id from response headers
        sid = resp.headers.get("mcp-session-id")
        if sid:
            self.session_id = sid
        return _parse_sse_result(resp.text)

    def initialize(self):
        result = self._call("initialize", {
            "protocolVersion": "2024-11-05",
            "capabilities": {},
            "clientInfo": {"name": "aleph-dashboard", "version": "1.0"},
        })
        # Send initialized notification
        self._call("notifications/initialized")
        return result

    def call_tool(self, name: str, arguments: dict):
        result = self._call("tools/call", {"name": name, "arguments": arguments})
        if result and isinstance(result, dict) and "content" in result:
            for block in result["content"]:
                if block.get("type") == "text":
                    try:
                        return json.loads(block["text"])
                    except (json.JSONDecodeError, KeyError):
                        return block["text"]
        return result

    def peers(self):
        return self.call_tool("peers", {"me": ME})

    def inbox(self):
        return self.call_tool("inbox", {"me": ME})

    def dispatch(self, to: str, context: str):
        return self.call_tool("dispatch", {"me": ME, "to": to, "context": context})

    def wait_any(self, timeout: int = 10):
        return self.call_tool("wait_any", {"me": ME, "timeout": timeout})

    def respond(self, task_id: str, answer: str):
        return self.call_tool("respond", {"me": ME, "task_id": task_id, "answer": answer})

    def room_send(self, content: str):
        return self.call_tool("room_send", {"me": ME, "content": content})

    def room_read(self):
        return self.call_tool("room_read", {"me": ME})

    def report(self, task_id: str, summary: str):
        return self.call_tool("report", {"me": ME, "task_id": task_id, "summary": summary})


# ── GUI ─────────────────────────────────────────────────────────────

class Dashboard:
    def __init__(self):
        self.root = tk.Tk()
        self.root.title("Aleph · Human")
        self.root.geometry("700x550")
        self.root.configure(bg="#1a1a1a")

        self.msg_queue = queue.Queue()
        self.client = None
        self.running = True

        self._build_ui()
        self._start_poll_thread()
        self.root.after(100, self._process_queue)
        self.root.protocol("WM_DELETE_WINDOW", self._on_close)

    def _build_ui(self):
        # Status bar
        self.status_frame = tk.Frame(self.root, bg="#2a2a2a", height=30)
        self.status_frame.pack(fill=tk.X)
        self.status_label = tk.Label(
            self.status_frame, text="connecting...",
            bg="#2a2a2a", fg="#888", font=("SF Mono", 11), anchor="w", padx=10
        )
        self.status_label.pack(fill=tk.X, pady=4)

        # Input area — pack FIRST with side=BOTTOM so it's always visible
        input_frame = tk.Frame(self.root, bg="#2a2a2a")
        input_frame.pack(fill=tk.X, side=tk.BOTTOM)

        # Chat area — fills remaining space
        self.chat = scrolledtext.ScrolledText(
            self.root, wrap=tk.WORD, state=tk.DISABLED,
            bg="#1a1a1a", fg="#ddd", font=("PingFang SC", 13),
            insertbackground="#ddd", relief=tk.FLAT,
            padx=12, pady=8, spacing3=4
        )
        self.chat.pack(fill=tk.BOTH, expand=True)
        self.chat.tag_config("role", foreground="#6aaf6a", font=("SF Mono", 11, "bold"))
        self.chat.tag_config("my_role", foreground="#af8a5a", font=("SF Mono", 11, "bold"))
        self.chat.tag_config("time", foreground="#555", font=("SF Mono", 10))
        self.chat.tag_config("system", foreground="#666", font=("SF Mono", 11, "italic"))

        # Text input
        self.entry = tk.Entry(
            input_frame, bg="#333", fg="#ddd", font=("PingFang SC", 13),
            insertbackground="#ddd", relief=tk.FLAT
        )
        self.entry.pack(side=tk.LEFT, fill=tk.X, expand=True, pady=8, ipady=4)
        self.entry.bind("<Return>", self._on_send)
        self.entry.focus()

        # Send button
        self.send_btn = tk.Button(
            input_frame, text="发送", command=self._on_send,
            bg="#444", fg="#ddd", relief=tk.FLAT, font=("PingFang SC", 12),
            padx=12
        )
        self.send_btn.pack(side=tk.RIGHT, padx=10, pady=8)

    def _append(self, text: str, tag: str = None):
        self.chat.config(state=tk.NORMAL)
        if tag:
            self.chat.insert(tk.END, text, tag)
        else:
            self.chat.insert(tk.END, text)
        self.chat.config(state=tk.DISABLED)
        self.chat.see(tk.END)

    def _show_message(self, role: str, content: str, is_me: bool = False):
        now = datetime.now().strftime("%H:%M")
        self._append(f"  {now} ", "time")
        self._append(f"{role}", "my_role" if is_me else "role")
        self._append(f"  {content}\n")

    def _show_system(self, text: str):
        self._append(f"  {text}\n", "system")

    def _on_send(self, event=None):
        text = self.entry.get().strip()
        if not text:
            return
        self.entry.delete(0, tk.END)
        self._show_message("Alta", text, is_me=True)

        def do_send():
            try:
                r = self.client.room_send(text)
                if r and isinstance(r, dict) and r.get("error"):
                    self.msg_queue.put(("system", f"error: {r['error']}"))
            except Exception as e:
                self.msg_queue.put(("system", f"send failed: {e}"))

        threading.Thread(target=do_send, daemon=True).start()

    def _poll_loop(self):
        """Background thread: connect + poll wait_any."""
        try:
            self.client = AlephClient()
            self.client.initialize()
            self.msg_queue.put(("system", "connected to Aleph (localhost:8765)"))

            # Initial peers check
            p = self.client.peers()
            if p and isinstance(p, dict):
                online = p.get("online", [])
                self.msg_queue.put(("peers", online))
        except Exception as e:
            self.msg_queue.put(("system", f"connection failed: {e}"))
            return

        while self.running:
            try:
                event = self.client.wait_any(timeout=10)
                if not event or not isinstance(event, dict):
                    continue
                etype = event.get("type")
                if etype == "still_waiting":
                    # Refresh peers silently
                    try:
                        p = self.client.peers()
                        if p and isinstance(p, dict):
                            self.msg_queue.put(("peers", p.get("online", [])))
                    except:
                        pass
                    continue
                elif etype == "incoming_queued":
                    fr = event.get("dispatched_by", "?")
                    ctx = event.get("context", "")
                    tid = event.get("task_id", "")
                    self.msg_queue.put(("msg", fr, ctx, tid))
                elif etype == "outgoing_done":
                    fr = event.get("from_role", "?")
                    summary = event.get("summary", "")
                    self.msg_queue.put(("done", fr, summary))
                elif etype == "outgoing_question":
                    fr = event.get("from_role", "?")
                    q = event.get("question", "")
                    tid = event.get("task_id", "")
                    self.msg_queue.put(("question", fr, q, tid))
                elif etype == "room_message":
                    sender = event.get("sender", "?")
                    content = event.get("content", "")
                    self.msg_queue.put(("room", sender, content))
                else:
                    self.msg_queue.put(("system", f"event: {etype}"))
            except Exception as e:
                if self.running:
                    self.msg_queue.put(("system", f"poll error: {e}"))
                    import time; time.sleep(3)

    def _start_poll_thread(self):
        t = threading.Thread(target=self._poll_loop, daemon=True)
        t.start()

    def _process_queue(self):
        while True:
            try:
                item = self.msg_queue.get_nowait()
            except queue.Empty:
                break

            if item[0] == "system":
                self._show_system(item[1])
            elif item[0] == "peers":
                online = [r for r in item[1] if r != ME]
                self.status_label.config(
                    text=f"  online: {', '.join(online) if online else '(none)'}  ·  you: {ME}"
                )
            elif item[0] == "room":
                sender, content = item[1], item[2]
                self._show_message(sender, content)
            elif item[0] == "msg":
                fr, ctx, tid = item[1], item[2], item[3]
                self._show_message(f"[{fr} → Human]", ctx)
            elif item[0] == "done":
                fr, summary = item[1], item[2]
                self._show_message(f"[{fr} ✓]", summary)
            elif item[0] == "question":
                fr, q, tid = item[1], item[2], item[3]
                self._show_message(f"[{fr} ?]", q)

        if self.running:
            self.root.after(100, self._process_queue)

    def _on_close(self):
        self.running = False
        self.root.destroy()

    def run(self):
        self.root.mainloop()


if __name__ == "__main__":
    Dashboard().run()
