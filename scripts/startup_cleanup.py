"""
EverLoop startup cleanup.

Run before starting the backend to avoid stale Python processes and old memory
summaries causing the Agent to repeat removed demo/mock search answers.

Default behavior is intentionally conservative but useful:
- delete Python __pycache__ directories under the project;
- remove known bad demo/mock search memories from everloop.db;
- optionally stop old EverLoop backend processes detected via /health.

Usage:
  python scripts/startup_cleanup.py --host 127.0.0.1 --port-start 8001 --port-span 50 --kill-backends
"""

from __future__ import annotations

import argparse
import http.client
import json
import os
import shutil
import sqlite3
import subprocess
import sys
from pathlib import Path


BAD_MEMORY_TERMS = [
    "演示模式",
    "示例搜索结果",
    "模拟结果",
    "相关结果 1",
    "相关结果 2",
    "example.com",
    "https://example.com",
]


def is_everloop_backend(host: str, port: int) -> bool:
    conn = http.client.HTTPConnection(host, port, timeout=0.6)
    try:
        conn.request("GET", "/health")
        resp = conn.getresponse()
        body = resp.read().decode("utf-8", errors="replace")
    except OSError:
        return False
    finally:
        conn.close()

    if resp.status != 200:
        return False
    try:
        data = json.loads(body)
    except json.JSONDecodeError:
        return "EverLoop Agent" in body
    return data.get("service") == "EverLoop Agent"


def cleanup_pycache(root: Path) -> int:
    removed = 0
    skip_names = {".git", "node_modules", "dist"}
    for path in list(root.rglob("__pycache__")):
        if not path.is_dir():
            continue
        if any(part in skip_names for part in path.parts):
            continue
        try:
            shutil.rmtree(path)
            removed += 1
        except OSError as exc:
            print(f"[WARN] failed to remove {path}: {exc}")
    return removed


def cleanup_bad_memories(db_path: Path) -> dict[str, int]:
    if not db_path.exists():
        return {}

    report: dict[str, int] = {}
    conn = sqlite3.connect(str(db_path))
    try:
        cur = conn.cursor()
        targets = [
            ("memories", "content"),
            ("messages", "content"),
            ("user_facts", "value"),
        ]
        patterns = [f"%{term}%" for term in BAD_MEMORY_TERMS]

        for table, column in targets:
            exists = cur.execute(
                "SELECT name FROM sqlite_master WHERE type='table' AND name=?",
                (table,),
            ).fetchone()
            if not exists:
                continue
            where = " OR ".join([f"{column} LIKE ?" for _ in patterns])
            count = cur.execute(
                f"SELECT COUNT(*) FROM {table} WHERE {where}",
                patterns,
            ).fetchone()[0]
            if count:
                cur.execute(f"DELETE FROM {table} WHERE {where}", patterns)
            report[table] = int(count)

        conn.commit()
        # Rewrite pages so removed text does not remain in SQLite free pages.
        cur.execute("PRAGMA secure_delete=ON")
        cur.execute("VACUUM")
    finally:
        conn.close()
    return report


def find_windows_pid_for_port(port: int) -> set[int]:
    if os.name != "nt":
        return set()
    try:
        proc = subprocess.run(
            ["netstat", "-ano"],
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="ignore",
            check=False,
        )
    except OSError:
        return set()

    pids: set[int] = set()
    marker = f":{port}"
    for line in proc.stdout.splitlines():
        parts = line.split()
        if len(parts) < 5:
            continue
        local_addr = parts[1]
        state = parts[-2] if len(parts) >= 5 else ""
        pid_text = parts[-1]
        if marker in local_addr and state.upper() == "LISTENING":
            try:
                pids.add(int(pid_text))
            except ValueError:
                pass
    return pids


def stop_process(pid: int) -> bool:
    if pid <= 0 or pid == os.getpid():
        return False
    if os.name == "nt":
        result = subprocess.run(
            ["taskkill", "/PID", str(pid), "/F"],
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="ignore",
            check=False,
        )
        return result.returncode == 0

    try:
        os.kill(pid, 15)
        return True
    except OSError:
        return False


def stop_old_everloop_backends(host: str, port_start: int, port_span: int) -> list[tuple[int, int, bool]]:
    stopped: list[tuple[int, int, bool]] = []
    for port in range(port_start, port_start + port_span):
        if not is_everloop_backend(host, port):
            continue
        for pid in find_windows_pid_for_port(port):
            ok = stop_process(pid)
            stopped.append((port, pid, ok))
    return stopped


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--root", default=str(Path(__file__).resolve().parents[1]))
    parser.add_argument("--db", default="everloop.db")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port-start", type=int, default=8001)
    parser.add_argument("--port-span", type=int, default=50)
    parser.add_argument("--kill-backends", action="store_true")
    parser.add_argument("--skip-db", action="store_true")
    parser.add_argument("--skip-pycache", action="store_true")
    args = parser.parse_args()

    root = Path(args.root).resolve()
    print("[CLEAN] EverLoop startup cleanup")

    if args.kill_backends:
        stopped = stop_old_everloop_backends(args.host, args.port_start, args.port_span)
        if stopped:
            for port, pid, ok in stopped:
                print(f"[CLEAN] old backend port={port} pid={pid} stopped={ok}")
        else:
            print("[CLEAN] no old EverLoop backend detected")

    if not args.skip_pycache:
        removed = cleanup_pycache(root)
        print(f"[CLEAN] removed __pycache__ dirs: {removed}")

    if not args.skip_db:
        db_path = Path(args.db)
        if not db_path.is_absolute():
            db_path = root / db_path
        report = cleanup_bad_memories(db_path)
        if report:
            print(f"[CLEAN] removed bad memory rows: {report}")
        else:
            print("[CLEAN] db not found or no memory tables")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
