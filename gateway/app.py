"""FastAPI secure task gateway (SPEC section A).

Run:  uvicorn gateway.app:app --reload
Auth: client /jobs* endpoints require `Authorization: Bearer $GATEWAY_TOKEN`
      (or `X-Gateway-Token`); admin endpoints require
      `X-Admin-Token: $GATEWAY_ADMIN_TOKEN`.
"""
from __future__ import annotations

import hmac
import logging
import os

from fastapi import Depends, FastAPI, Header, HTTPException, Request
from fastapi.responses import JSONResponse

from . import policy
from .db import Database
from .models import (
    AdminConfig, AuditEntry, Classification, JobApproveResponse, JobCancelResponse,
    JobClaim, JobClaimResponse, JobComplete, JobStatus, JobStatusResponse,
    JobSubmit, JobSubmitResponse, Route, TERMINAL_STATUSES, WorkerRegister,
    WorkerRegisterResponse,
)

logger = logging.getLogger("gateway")

# Client hosts treated as loopback. "testclient" is the host Starlette's
# TestClient reports, so the in-process dev/test workflow keeps working.
LOOPBACK_CLIENT_HOSTS = frozenset({"127.0.0.1", "::1", "localhost", "testclient"})


def create_app(db_path: str = ":memory:") -> FastAPI:
    app = FastAPI(title="0xPhone Companion Gateway", version="0.1.0")
    db = Database(db_path)
    config = policy.Config(
        paid_enabled=os.environ.get("GATEWAY_PAID_ENABLED", "0") == "1")
    app.state.db = db
    app.state.config = config

    # ---- client auth (owner pairing token) ---------------------------------
    # All /jobs* endpoints are owner-only. If GATEWAY_TOKEN is unset the
    # loopback dev workflow keeps working, but any non-loopback client is
    # refused: an unauthenticated gateway must never be reachable off-host
    # (audit H9/PC-01 — /jobs/{id}/approve releases confidential jobs).
    if not os.environ.get("GATEWAY_TOKEN"):
        logger.warning(
            "GATEWAY_TOKEN is unset: /jobs* endpoints are UNAUTHENTICATED for "
            "loopback clients and REFUSED for non-loopback clients. Set "
            "GATEWAY_TOKEN before binding beyond loopback (tunnel deploys).")

    @app.middleware("http")
    async def require_gateway_token(request: Request, call_next):
        if not request.url.path.startswith("/jobs"):
            return await call_next(request)
        token = os.environ.get("GATEWAY_TOKEN")
        if token:
            provided = request.headers.get("x-gateway-token")
            auth = request.headers.get("authorization", "")
            if not provided and auth.lower().startswith("bearer "):
                provided = auth[len("bearer "):].strip()
            if not provided or not hmac.compare_digest(provided, token):
                db.audit("client_auth_denied", actor="client", job_id=None,
                         detail={"path": request.url.path,
                                 "reason": "missing or invalid gateway token"})
                return JSONResponse(
                    status_code=401,
                    content={"detail": "missing or invalid gateway token"})
        else:
            host = request.client.host if request.client else ""
            if host not in LOOPBACK_CLIENT_HOSTS:
                logger.error(
                    "REFUSING non-loopback request to %s from %s: "
                    "GATEWAY_TOKEN is unset; refusing to serve non-loopback "
                    "clients without an owner token",
                    request.url.path, host)
                return JSONResponse(
                    status_code=503,
                    content={"detail": "GATEWAY_TOKEN not configured; "
                                       "refusing non-loopback clients"})
        return await call_next(request)

    # ---- dependencies ------------------------------------------------------
    def get_db() -> Database:
        return app.state.db

    def get_config() -> policy.Config:
        return app.state.config

    def require_admin(x_admin_token: str | None = Header(default=None)) -> str:
        expected = os.environ.get("GATEWAY_ADMIN_TOKEN")
        if not expected:
            raise HTTPException(503, "GATEWAY_ADMIN_TOKEN not configured")
        if x_admin_token != expected:
            raise HTTPException(401, "invalid admin token")
        return "admin"

    # ---- helpers -----------------------------------------------------------
    def job_response(j: dict) -> JobStatusResponse:
        return JobStatusResponse(
            job_id=j["job_id"], status=JobStatus(j["status"]),
            route=Route(j["route"]) if j["route"] else None,
            task_type=j["task_type"],
            data_classification=Classification(j["data_classification"]),
            requested_capabilities=j["requested_capabilities"],
            budget_cents=j["budget_cents"], spent_cents=j["spent_cents"],
            deadline_s=j["deadline_s"], worker_id=j["worker_id"],
            result=j["result"], created_at=j["created_at"])

    def get_job_or_404(job_id: str) -> dict:
        j = db.get_job(job_id)
        if j is None:
            raise HTTPException(404, "job not found")
        return j

    # ---- jobs --------------------------------------------------------------
    @app.post("/jobs", response_model=JobSubmitResponse, status_code=201)
    def submit_job(body: JobSubmit, d: Database = Depends(get_db),
                   cfg: policy.Config = Depends(get_config)):
        workers = [w for w in d.list_workers() if not w["revoked"]]
        try:
            decision = policy.decide_route(
                classification=body.data_classification,
                requested_capabilities=body.requested_capabilities,
                budget_cents=body.budget_cents, workers=workers, config=cfg)
        except policy.PolicyReject as e:
            d.audit("job_rejected", actor="client",
                    detail={"task_type": body.task_type,
                            "classification": body.data_classification.value,
                            "reason": e.reason})
            raise HTTPException(422, e.reason)

        status = (JobStatus.awaiting_approval if decision.needs_approval
                  else JobStatus.queued)
        job = d.create_job(
            task_type=body.task_type, payload_ref=body.payload_ref,
            data_classification=body.data_classification.value,
            requested_capabilities=body.requested_capabilities,
            budget_cents=body.budget_cents, deadline_s=body.deadline_s,
            status=status.value,
            route=None if decision.needs_approval else decision.route.value)
        if decision.worker_id:
            d.update_job(job["job_id"], worker_id=decision.worker_id)
        d.audit("job_submitted", actor="client", job_id=job["job_id"],
                detail={"task_type": body.task_type,
                        "classification": body.data_classification.value,
                        "requested_capabilities": body.requested_capabilities,
                        "budget_cents": body.budget_cents})
        d.audit("routing_decision", actor="policy", job_id=job["job_id"],
                detail={"route": decision.route.value,
                        "worker_id": decision.worker_id,
                        "needs_approval": decision.needs_approval,
                        "reason": decision.reason})
        return JobSubmitResponse(
            job_id=job["job_id"], status=status,
            route=None if decision.needs_approval else decision.route)

    @app.get("/jobs/{job_id}", response_model=JobStatusResponse)
    def get_job(job_id: str):
        return job_response(get_job_or_404(job_id))

    @app.post("/jobs/{job_id}/cancel", response_model=JobCancelResponse)
    def cancel_job(job_id: str):
        j = get_job_or_404(job_id)
        status = JobStatus(j["status"])
        if status in TERMINAL_STATUSES:
            # Idempotent: cancelling a terminal job is a no-op.
            return JobCancelResponse(job_id=job_id, status=status)
        db.update_job(job_id, status=JobStatus.cancelled.value)
        db.audit("job_cancelled", actor="client", job_id=job_id,
                detail={"previous_status": status.value})
        return JobCancelResponse(job_id=job_id, status=JobStatus.cancelled)

    @app.post("/jobs/{job_id}/approve", response_model=JobApproveResponse)
    def approve_job(job_id: str):
        j = get_job_or_404(job_id)
        if JobStatus(j["status"]) != JobStatus.awaiting_approval:
            raise HTTPException(
                409, f"job is {j['status']}, not awaiting_approval")
        # Approval was requested for a remote worker route; queue it there.
        db.update_job(job_id, status=JobStatus.queued.value,
                     route=Route.remote_worker.value)
        db.audit("job_approved", actor="user", job_id=job_id,
                detail={"route": Route.remote_worker.value})
        return JobApproveResponse(job_id=job_id, status=JobStatus.queued,
                                  route=Route.remote_worker)

    @app.post("/jobs/{job_id}/claim", response_model=JobClaimResponse)
    def claim_job(job_id: str, body: JobClaim,
                  cfg: policy.Config = Depends(get_config)):
        j = get_job_or_404(job_id)

        # Idempotency: a reconnect replaying the same key gets the original
        # claim back; no duplicate claim, no duplicate ledger charge.
        existing = db.get_claim(job_id, body.idempotency_key)
        if existing is not None:
            return JobClaimResponse(
                job_id=job_id, claim_id=existing["claim_id"],
                worker_id=existing["worker_id"], status=JobStatus(j["status"]),
                idempotency_key=body.idempotency_key)

        if JobStatus(j["status"]) != JobStatus.queued:
            raise HTTPException(409, f"job is {j['status']}, not queued")

        route = Route(j["route"]) if j["route"] else None
        if route == Route.paid_model:
            # Paid model claims are made by the provider using admin auth.
            require_admin(body.worker_token)
            worker_id = "paid-model-provider"
            if not cfg.paid_enabled:
                db.audit("paid_call_denied", actor=worker_id, job_id=job_id,
                         detail={"reason": "paid model disabled"})
                raise HTTPException(403, "paid model disabled")
            if not policy.can_afford_paid_call(j):
                db.audit("paid_call_denied", actor=worker_id, job_id=job_id,
                         detail={"reason": "budget exhausted"})
                raise HTTPException(402, "budget exhausted")
            cost = policy.PAID_CALL_COST_CENTS
            db.update_job(job_id, spent_cents=j["spent_cents"] + cost)
            db.audit("paid_call", actor=worker_id, job_id=job_id,
                     detail={"cost_cents": cost})
        else:
            worker = db.get_worker_by_token(body.worker_token)
            if worker is None:
                db.audit("claim_denied", actor="unknown", job_id=job_id,
                         detail={"reason": "unknown worker token"})
                raise HTTPException(401, "unknown worker token")
            ok, reason = policy.worker_may_claim(worker, j)
            if not ok:
                db.audit("claim_denied", actor=worker["worker_id"],
                         job_id=job_id, detail={"reason": reason})
                status_code = 403 if "revoked" in reason else 409
                raise HTTPException(status_code, reason)
            worker_id = worker["worker_id"]

        claim = db.create_claim(job_id=job_id, worker_id=worker_id,
                                idempotency_key=body.idempotency_key)
        db.update_job(job_id, status=JobStatus.running.value,
                      worker_id=worker_id)
        db.audit("job_claimed", actor=worker_id, job_id=job_id,
                 detail={"idempotency_key": body.idempotency_key})
        return JobClaimResponse(job_id=job_id, claim_id=claim["claim_id"],
                                worker_id=worker_id,
                                status=JobStatus.running,
                                idempotency_key=body.idempotency_key)

    @app.post("/jobs/{job_id}/complete", response_model=JobStatusResponse)
    def complete_job(job_id: str, body: JobComplete):
        j = get_job_or_404(job_id)
        if Route(j["route"] or "") != Route.paid_model:
            worker = db.get_worker_by_token(body.worker_token)
            if worker is None or worker["revoked"]:
                raise HTTPException(401, "invalid worker token")
            if j["worker_id"] != worker["worker_id"]:
                raise HTTPException(403, "job not claimed by this worker")
        else:
            require_admin(body.worker_token)
        if JobStatus(j["status"]) not in (JobStatus.running, JobStatus.queued):
            raise HTTPException(409, f"job is {j['status']}")
        d = db.update_job(job_id, status=JobStatus.completed.value,
                          result=body.result)
        db.audit("job_completed", actor=j["worker_id"] or "unknown",
                 job_id=job_id, detail={})
        return job_response(d)

    # ---- workers -----------------------------------------------------------
    @app.post("/workers/register", response_model=WorkerRegisterResponse,
              status_code=201)
    def register_worker(body: WorkerRegister, actor: str = Depends(require_admin)):
        w = db.create_worker(capabilities=body.capabilities,
                             route_type=body.route_type, free=body.free,
                             worker_id=body.worker_id)
        db.audit("worker_registered", actor=actor, job_id=None,
                 detail={"worker_id": w["worker_id"],
                         "capabilities": w["capabilities"],
                         "route_type": w["route_type"], "free": w["free"]})
        return WorkerRegisterResponse(
            worker_id=w["worker_id"], token=w["token"],
            capabilities=w["capabilities"], route_type=w["route_type"],
            free=w["free"])

    @app.post("/workers/{worker_id}/revoke",
              response_model=WorkerRegisterResponse)
    def revoke_worker(worker_id: str, actor: str = Depends(require_admin)):
        w = db.revoke_worker(worker_id)
        if w is None:
            raise HTTPException(404, "worker not found")
        db.audit("worker_revoked", actor=actor,
                 detail={"worker_id": worker_id})
        return WorkerRegisterResponse(
            worker_id=w["worker_id"], token=w["token"],
            capabilities=w["capabilities"], route_type=w["route_type"],
            free=w["free"])

    # ---- admin / audit -----------------------------------------------------
    @app.get("/audit", response_model=list[AuditEntry])
    def get_audit(actor: str = Depends(require_admin)):
        return [AuditEntry(**row) for row in db.audit_log()]

    @app.post("/admin/config", response_model=AdminConfig)
    def set_config(body: AdminConfig, actor: str = Depends(require_admin)):
        if body.paid_enabled is not None:
            config.paid_enabled = body.paid_enabled
        db.audit("config_changed", actor=actor,
                 detail={"paid_enabled": config.paid_enabled})
        return AdminConfig(paid_enabled=config.paid_enabled)

    return app


app = create_app(os.environ.get("GATEWAY_DB", ":memory:"))
