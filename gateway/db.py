"""SQLite persistence layer (stdlib sqlite3, dependency-light).

A single Database object owns one connection; FastAPI handlers share it.
All writes go through helpers that also append to the audit log.
"""
from __future__ import annotations

import json
import sqlite3
import threading
import time
import uuid

SCHEMA = """
CREATE TABLE IF NOT EXISTS jobs (
    job_id TEXT PRIMARY KEY,
    task_type TEXT NOT NULL,
    payload_ref TEXT NOT NULL,
    data_classification TEXT NOT NULL,
    requested_capabilities TEXT NOT NULL,
    budget_cents INTEGER NOT NULL,
    spent_cents INTEGER NOT NULL DEFAULT 0,
    deadline_s INTEGER NOT NULL,
    status TEXT NOT NULL,
    route TEXT,
    worker_id TEXT,
    result TEXT,
    created_at REAL NOT NULL
);
CREATE TABLE IF NOT EXISTS workers (
    worker_id TEXT PRIMARY KEY,
    token TEXT UNIQUE NOT NULL,
    capabilities TEXT NOT NULL,
    route_type TEXT NOT NULL,
    free INTEGER NOT NULL DEFAULT 1,
    revoked INTEGER NOT NULL DEFAULT 0,
    created_at REAL NOT NULL
);
CREATE TABLE IF NOT EXISTS claims (
    claim_id TEXT PRIMARY KEY,
    job_id TEXT NOT NULL,
    worker_id TEXT NOT NULL,
    idempotency_key TEXT NOT NULL,
    created_at REAL NOT NULL,
    UNIQUE (job_id, idempotency_key)
);
CREATE TABLE IF NOT EXISTS audit (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    ts REAL NOT NULL,
    event TEXT NOT NULL,
    job_id TEXT,
    actor TEXT NOT NULL,
    detail TEXT NOT NULL
);
"""


def _new_id(prefix: str) -> str:
    return f"{prefix}_{uuid.uuid4().hex[:16]}"


class Database:
    def __init__(self, path: str = ":memory:"):
        self._conn = sqlite3.connect(path, check_same_thread=False)
        self._conn.row_factory = sqlite3.Row
        self._conn.execute("PRAGMA journal_mode=WAL") if path != ":memory:" else None
        self._conn.execute("PRAGMA foreign_keys=ON")
        self._lock = threading.RLock()
        with self._lock, self._conn:
            self._conn.executescript(SCHEMA)

    def close(self) -> None:
        self._conn.close()

    # ---- audit ------------------------------------------------------------
    def audit(self, event: str, actor: str, job_id: str | None = None,
              detail: dict | None = None) -> None:
        with self._lock, self._conn:
            self._conn.execute(
                "INSERT INTO audit (ts, event, job_id, actor, detail) VALUES (?,?,?,?,?)",
                (time.time(), event, job_id, actor, json.dumps(detail or {})),
            )

    def audit_log(self) -> list[dict]:
        with self._lock:
            rows = self._conn.execute(
                "SELECT * FROM audit ORDER BY id ASC").fetchall()
        return [dict(r) | {"detail": json.loads(r["detail"])} for r in rows]

    # ---- jobs -------------------------------------------------------------
    def create_job(self, *, task_type: str, payload_ref: str,
                   data_classification: str, requested_capabilities: list[str],
                   budget_cents: int, deadline_s: int, status: str,
                   route: str | None) -> dict:
        job_id = _new_id("job")
        with self._lock, self._conn:
            self._conn.execute(
                "INSERT INTO jobs (job_id, task_type, payload_ref,"
                " data_classification, requested_capabilities, budget_cents,"
                " spent_cents, deadline_s, status, route, created_at)"
                " VALUES (?,?,?,?,?,?,0,?,?,?,?)",
                (job_id, task_type, payload_ref, data_classification,
                 json.dumps(requested_capabilities), budget_cents, deadline_s,
                 status, route, time.time()),
            )
        return self.get_job(job_id)

    def get_job(self, job_id: str) -> dict | None:
        with self._lock:
            r = self._conn.execute(
                "SELECT * FROM jobs WHERE job_id=?", (job_id,)).fetchone()
        if r is None:
            return None
        d = dict(r)
        d["requested_capabilities"] = json.loads(d["requested_capabilities"])
        d["result"] = json.loads(d["result"]) if d["result"] else None
        return d

    def update_job(self, job_id: str, **fields) -> dict | None:
        if not fields:
            return self.get_job(job_id)
        cols = ", ".join(f"{k}=?" for k in fields)
        vals = [
            json.dumps(v) if k in ("requested_capabilities", "result")
            and not isinstance(v, (str, type(None))) else v
            for k, v in fields.items()
        ]
        with self._lock, self._conn:
            self._conn.execute(
                f"UPDATE jobs SET {cols} WHERE job_id=?", (*vals, job_id))
        return self.get_job(job_id)

    # ---- workers ----------------------------------------------------------
    def create_worker(self, *, capabilities: list[str], route_type: str,
                      free: bool, worker_id: str | None = None) -> dict:
        worker_id = worker_id or _new_id("wrk")
        token = _new_id("wtk")
        with self._lock, self._conn:
            self._conn.execute(
                "INSERT INTO workers (worker_id, token, capabilities,"
                " route_type, free, revoked, created_at) VALUES (?,?,?,?,?,0,?)",
                (worker_id, token, json.dumps(capabilities), route_type,
                 1 if free else 0, time.time()),
            )
        return self.get_worker(worker_id)

    def get_worker(self, worker_id: str) -> dict | None:
        with self._lock:
            r = self._conn.execute(
                "SELECT * FROM workers WHERE worker_id=?", (worker_id,)).fetchone()
        return self._worker_row(r)

    def get_worker_by_token(self, token: str) -> dict | None:
        with self._lock:
            r = self._conn.execute(
                "SELECT * FROM workers WHERE token=?", (token,)).fetchone()
        return self._worker_row(r)

    def list_workers(self) -> list[dict]:
        with self._lock:
            rows = self._conn.execute("SELECT * FROM workers").fetchall()
        return [self._worker_row(r) for r in rows]

    def revoke_worker(self, worker_id: str) -> dict | None:
        with self._lock, self._conn:
            self._conn.execute(
                "UPDATE workers SET revoked=1 WHERE worker_id=?", (worker_id,))
        return self.get_worker(worker_id)

    @staticmethod
    def _worker_row(r) -> dict | None:
        if r is None:
            return None
        d = dict(r)
        d["capabilities"] = json.loads(d["capabilities"])
        d["free"] = bool(d["free"])
        d["revoked"] = bool(d["revoked"])
        return d

    # ---- claims -----------------------------------------------------------
    def create_claim(self, *, job_id: str, worker_id: str,
                     idempotency_key: str) -> dict:
        claim_id = _new_id("clm")
        with self._lock, self._conn:
            self._conn.execute(
                "INSERT INTO claims (claim_id, job_id, worker_id,"
                " idempotency_key, created_at) VALUES (?,?,?,?,?)",
                (claim_id, job_id, worker_id, idempotency_key, time.time()),
            )
        return self.get_claim(job_id, idempotency_key)

    def get_claim(self, job_id: str, idempotency_key: str) -> dict | None:
        with self._lock:
            r = self._conn.execute(
                "SELECT * FROM claims WHERE job_id=? AND idempotency_key=?",
                (job_id, idempotency_key)).fetchone()
        return dict(r) if r else None
