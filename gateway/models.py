"""Pydantic schemas for the gateway API. These are the contract mirrored by
the Android client (android/net/GatewayClient.kt)."""
from __future__ import annotations

from enum import Enum
from typing import Any, Literal

from pydantic import BaseModel, Field


class Classification(str, Enum):
    public = "public"
    internal = "internal"
    confidential = "confidential"
    secret = "secret"


CLASSIFICATION_ORDER = ["public", "internal", "confidential", "secret"]


class JobStatus(str, Enum):
    queued = "queued"
    running = "running"
    awaiting_approval = "awaiting_approval"
    completed = "completed"
    failed = "failed"
    cancelled = "cancelled"


TERMINAL_STATUSES = {JobStatus.completed, JobStatus.failed, JobStatus.cancelled}


class Route(str, Enum):
    on_device = "on-device"
    local_worker = "local_worker"
    remote_worker = "remote_worker"
    paid_model = "paid_model"


# Routes whose execution leaves the device.
EXTERNAL_ROUTES = {Route.remote_worker, Route.paid_model}


class JobSubmit(BaseModel):
    task_type: str
    payload_ref: str
    data_classification: Classification
    requested_capabilities: list[str] = Field(default_factory=list)
    budget_cents: int = Field(default=0, ge=0)
    deadline_s: int = Field(default=3600, gt=0)


class JobSubmitResponse(BaseModel):
    job_id: str
    status: JobStatus
    route: Route | None = None


class JobStatusResponse(BaseModel):
    job_id: str
    status: JobStatus
    route: Route | None = None
    task_type: str
    data_classification: Classification
    requested_capabilities: list[str]
    budget_cents: int
    spent_cents: int
    deadline_s: int
    worker_id: str | None = None
    result: Any | None = None
    created_at: float


class JobCancelResponse(BaseModel):
    job_id: str
    status: JobStatus


class JobApproveResponse(BaseModel):
    job_id: str
    status: JobStatus
    route: Route | None = None


class WorkerRegister(BaseModel):
    worker_id: str | None = None
    capabilities: list[str] = Field(default_factory=list)
    route_type: Literal["local", "remote"] = "local"
    free: bool = True


class WorkerRegisterResponse(BaseModel):
    worker_id: str
    token: str
    capabilities: list[str]
    route_type: str
    free: bool


class JobClaim(BaseModel):
    worker_token: str
    idempotency_key: str


class JobClaimResponse(BaseModel):
    job_id: str
    claim_id: str
    worker_id: str
    status: JobStatus
    idempotency_key: str


class JobComplete(BaseModel):
    worker_token: str
    result: Any | None = None


class AuditEntry(BaseModel):
    id: int
    ts: float
    event: str
    job_id: str | None = None
    actor: str
    detail: dict[str, Any] = Field(default_factory=dict)


class AdminConfig(BaseModel):
    paid_enabled: bool | None = None
