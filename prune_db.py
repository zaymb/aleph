"""Prune old completed tasks and stale loop summaries from loop.db.

Drops tasks (and their messages) where status='done' AND updated_at is
older than the retention window, plus loop_summaries older than the same
cutoff. Then VACUUMs.

Usage:
  uv run python prune_db.py                # use LOOP_RETENTION_DAYS or default 7
  uv run python prune_db.py --days 1       # explicit override
  uv run python prune_db.py --dry-run      # show what would be dropped
  uv run python prune_db.py --all          # drop everything done regardless of age

Add to cron / launchd if you want automatic retention:
  0 4 * * *  cd ~/collab-loop && uv run python prune_db.py
"""

from __future__ import annotations

import argparse
import os
import sqlite3
import sys
import time


DEFAULT_DB = os.path.expanduser("~/collab-loop/loop.db")
DEFAULT_DAYS = int(os.environ.get("LOOP_RETENTION_DAYS", "7"))


def main():
    p = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    p.add_argument("--db", default=os.environ.get("LOOP_DB", DEFAULT_DB),
                   help=f"SQLite path (default: {DEFAULT_DB})")
    p.add_argument("--days", type=int, default=DEFAULT_DAYS,
                   help=f"retention window in days (default: {DEFAULT_DAYS})")
    p.add_argument("--all", action="store_true",
                   help="drop ALL done tasks regardless of age")
    p.add_argument("--dry-run", action="store_true",
                   help="report what would be dropped without changing anything")
    args = p.parse_args()

    if not os.path.exists(args.db):
        print(f"db not found: {args.db}", file=sys.stderr)
        sys.exit(1)

    # cutoff is "older than this" — for --all we want everything done, so
    # set cutoff to "now" (every done task is older than now).
    cutoff = time.time() if args.all else time.time() - args.days * 86400

    conn = sqlite3.connect(args.db)
    conn.row_factory = sqlite3.Row
    try:
        rows = conn.execute(
            "SELECT id, assigned_to, dispatched_by, outcome, "
            "       datetime(updated_at, 'unixepoch', 'localtime') AS done_at "
            "FROM tasks WHERE status='done' AND updated_at < ? "
            "ORDER BY updated_at",
            (cutoff,),
        ).fetchall()

        if not rows:
            print(f"nothing to prune (cutoff: {args.days}d, db: {args.db})")
            return

        msg_count = conn.execute(
            "SELECT COUNT(*) AS n FROM messages WHERE task_id IN ("
            "  SELECT id FROM tasks WHERE status='done' AND updated_at < ?"
            ")",
            (cutoff,),
        ).fetchone()["n"]

        for row in rows:
            print(f"  {row['id']}  {row['dispatched_by']:>6} → {row['assigned_to']:<6} "
                  f"{row['outcome']:<10}  {row['done_at']}")
        print(f"\n{len(rows)} task(s), {msg_count} message(s) would be dropped.")

        if args.dry_run:
            print("(dry-run — no changes made)")
            return

        conn.execute(
            "DELETE FROM messages WHERE task_id IN ("
            "  SELECT id FROM tasks WHERE status='done' AND updated_at < ?"
            ")",
            (cutoff,),
        )
        conn.execute(
            "DELETE FROM tasks WHERE status='done' AND updated_at < ?",
            (cutoff,),
        )
        sum_dropped = conn.execute(
            "DELETE FROM loop_summaries WHERE created_at < ?", (cutoff,),
        ).rowcount
        if sum_dropped:
            print(f"  + {sum_dropped} stale loop_summaries row(s) dropped")
        conn.commit()
    finally:
        conn.close()

    # VACUUM in its own connection (cannot run inside a transaction)
    conn = sqlite3.connect(args.db)
    try:
        conn.execute("VACUUM")
    finally:
        conn.close()

    print(f"\npruned. db now: {os.path.getsize(args.db) / 1024:.1f}K")


if __name__ == "__main__":
    main()
