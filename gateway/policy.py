"""Core policy engine: "Hermes requests, the OS decides."

Routing order (SPEC section A):
  1. on-device
  2. authorized local/free worker
  3. approved remote worker (non-public classifications require user approval)
  4. paid model (only if authorized + budget remains + classification permits)

Hard rules:
  - `secret` data never leaves the device (only route 1 is legal).
  - Workers can never exceed granted capabilities (enforced at claim time).
  - Paid calls denied when paid models are disabled or the budget is exhausted.
"""
from __future__ import annotations

from dataclasses import dataclass, field

from .models import Classification, EXTERNAL_ROUTES, Route

# Capabilities the on-device executor provides.
DEVICE_CAPABILITIES: set[str] = {"summarize", "classify", "reminder"}

# Capabilities the paid model provider offers.
PAID_MODEL_CAPABILITIES: set[str] = {"summarize", "translate", "code", "reasoning"}

# Classifications permitted to reach the paid model.
PAID_MODEL_CLASSIFICATIONS: set[Classification] = {
    Classification.public, Classification.internal,
}

# Classifications a remote worker may handle *without* user approval.
REMOTE_DIRECT_CLASSIFICATIONS: set[Classification] = {Classification.public}

# Default cost charged to the job ledger for one paid model call.
PAID_CALL_COST_CENTS = 5


class PolicyReject(Exception):
    """Raised when no legal route exists for a job."""

    def __init__(self, reason: str):
        super().__init__(reason)
        self.reason = reason


@dataclass
class Config:
    paid_enabled: bool = False


@dataclass
class RouteDecision:
    route: Route
    worker_id: str | None = None
    needs_approval: bool = False
    reason: str = ""


def route_leaves_device(route: Route) -> bool:
    return route in EXTERNAL_ROUTES


def decide_route(*, classification: Classification,
                 requested_capabilities: list[str],
                 budget_cents: int, workers: list[dict],
                 config: Config) -> RouteDecision:
    """Pick a route for a job or raise PolicyReject.

    `workers` are registered, non-revoked worker dicts from the DB.
    """
    requested = set(requested_capabilities)
    cls = classification

    # 1. On-device execution. The only legal destination for `secret` data.
    if requested <= DEVICE_CAPABILITIES:
        return RouteDecision(Route.on_device, reason="capabilities on-device")
    if cls == Classification.secret:
        raise PolicyReject(
            "secret classification cannot leave the device and the requested "
            "capabilities are not available on-device")

    # 2. Authorized local/free worker (same trust domain as the device;
    #    still not allowed for secret data).
    for w in workers:
        if w["route_type"] == "local" and w["free"] \
                and requested <= set(w["capabilities"]):
            return RouteDecision(Route.local_worker, worker_id=w["worker_id"],
                                 reason="local free worker with capabilities")

    # 3. Approved remote worker. Non-public classifications need explicit
    #    user approval before the job is queued for the worker.
    for w in workers:
        if w["route_type"] == "remote" \
                and requested <= set(w["capabilities"]):
            if cls in REMOTE_DIRECT_CLASSIFICATIONS:
                return RouteDecision(Route.remote_worker,
                                     worker_id=w["worker_id"],
                                     reason="remote worker, public data")
            return RouteDecision(Route.remote_worker, worker_id=w["worker_id"],
                                 needs_approval=True,
                                 reason="remote worker requires approval for "
                                        f"{cls.value} data")

    # 4. Paid model — only if enabled, budgeted, and classification permits.
    if requested <= PAID_MODEL_CAPABILITIES:
        if cls not in PAID_MODEL_CLASSIFICATIONS:
            raise PolicyReject(
                f"paid model not permitted for {cls.value} classification")
        if not config.paid_enabled:
            raise PolicyReject("paid model disabled by policy")
        if budget_cents - 0 < PAID_CALL_COST_CENTS:
            raise PolicyReject("budget exhausted for paid model route")
        return RouteDecision(Route.paid_model, reason="paid model authorized")

    raise PolicyReject(
        f"missing capabilities: no route can satisfy "
        f"{sorted(requested - DEVICE_CAPABILITIES - PAID_MODEL_CAPABILITIES)}")


def can_afford_paid_call(job: dict, cost_cents: int = PAID_CALL_COST_CENTS) -> bool:
    """Budget ledger check: is there enough remaining budget for a paid call?"""
    return job["budget_cents"] - job["spent_cents"] >= cost_cents


def worker_may_claim(worker: dict, job: dict) -> tuple[bool, str]:
    """Server-side capability check on every job claim.

    A worker can never exceed its granted capabilities, regardless of what
    its token claims.
    """
    if worker["revoked"]:
        return False, "worker credential revoked"
    if job["worker_id"] and job["worker_id"] != worker["worker_id"]:
        return False, "job assigned to a different worker"
    expected_route = {
        "local": Route.local_worker.value,
        "remote": Route.remote_worker.value,
    }.get(worker["route_type"])
    if job["route"] != expected_route:
        return False, f"worker route_type does not match job route {job['route']}"
    missing = set(job["requested_capabilities"]) - set(worker["capabilities"])
    if missing:
        return False, f"worker lacks capabilities: {sorted(missing)}"
    return True, ""
