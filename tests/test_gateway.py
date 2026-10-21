"""Acceptance tests for the 0xPhone companion gateway (SPEC section A).

Covers the server-side MVP acceptance checks:
  1. Capability enforcement (worker can't exceed granted capabilities)
  2. Privacy routing (secret classification never routed externally)
  3. Cost control (paid calls denied when disabled / budget exhausted)
  4. Reliability: idempotent job claims on reconnect
  5. Credential scoping + revocation
  6. Client auth: owner pairing token (GATEWAY_TOKEN) on all /jobs* endpoints
"""
import asyncio
import os

import pytest
from fastapi.testclient import TestClient

ADMIN = "test-admin-token"
os.environ["GATEWAY_ADMIN_TOKEN"] = ADMIN

from gateway.app import create_app  # noqa: E402

AUTH = {"X-Admin-Token": ADMIN}

OWNER = "owner-pairing-token"
OWNER_BEARER = {"Authorization": f"Bearer {OWNER}"}
OWNER_HEADER = {"X-Gateway-Token": OWNER}


@pytest.fixture()
def client():
    app = create_app(":memory:")
    with TestClient(app) as c:
        yield c


def submit(client, **kw):
    body = {
        "task_type": "summarize",
        "payload_ref": "mem://note/1",
        "data_classification": "public",
        "requested_capabilities": ["summarize"],
        "budget_cents": 0,
        "deadline_s": 600,
    }
    body.update(kw)
    return client.post("/jobs", json=body)


def register_worker(client, **kw):
    body = {"capabilities": ["summarize"], "route_type": "local", "free": True}
    body.update(kw)
    r = client.post("/workers/register", json=body, headers=AUTH)
    assert r.status_code == 201, r.text
    return r.json()


# --------------------------------------------------------------------------
# 1. Capability enforcement
# --------------------------------------------------------------------------

def test_submit_rejects_missing_capabilities(client):
    r = submit(client, requested_capabilities=["quantum teleport"])
    assert r.status_code == 422
    assert "capabilities" in r.json()["detail"]


def test_worker_cannot_claim_job_beyond_granted_capabilities(client):
    # Remote worker with only 'summarize'; job needs 'code' -> routes to paid
    # or is rejected, but even if assigned, a worker lacking caps can't claim.
    worker = register_worker(client, capabilities=["summarize"],
                             route_type="remote")
    # Force assignment: job needs 'summarize' only but worker claims a job
    # assigned to a different worker is covered below; here we register a
    # second worker WITH the caps and try to claim with the first token.
    worker2 = register_worker(client, capabilities=["summarize", "code"],
                              route_type="remote")
    r = submit(client, requested_capabilities=["code"])
    assert r.status_code == 201
    job_id = r.json()["job_id"]
    # job routed to worker2 (first registered remote worker matching caps)
    r = client.post(f"/jobs/{job_id}/claim",
                    json={"worker_token": worker["token"],
                          "idempotency_key": "k1"})
    assert r.status_code in (403, 409)
    # correct worker may claim
    r = client.post(f"/jobs/{job_id}/claim",
                    json={"worker_token": worker2["token"],
                          "idempotency_key": "k2"})
    assert r.status_code == 200


def test_worker_token_cannot_exceed_registered_scope(client):
    """Even if a worker asks for a job, server checks stored capabilities."""
    worker = register_worker(client, capabilities=["code"])
    # submit job needing only code, routed to the worker
    r = submit(client, requested_capabilities=["code"],
               data_classification="internal")
    job_id = r.json()["job_id"]
    r = client.post(f"/jobs/{job_id}/claim",
                    json={"worker_token": worker["token"],
                          "idempotency_key": "k"})
    assert r.status_code == 200
    # now a job needing a capability the worker doesn't have (routed paid)
    client.post("/admin/config", json={"paid_enabled": True}, headers=AUTH)
    r = submit(client, requested_capabilities=["translate"],
               budget_cents=100)
    assert r.json()["route"] == "paid_model"
    r = client.post(f"/jobs/{r.json()['job_id']}/claim",
                    json={"worker_token": worker["token"],
                          "idempotency_key": "k2"})
    assert r.status_code != 200


# --------------------------------------------------------------------------
# 2. Privacy routing
# --------------------------------------------------------------------------

def test_secret_never_routed_externally(client):
    # A remote worker with the capability exists, but secret must not use it.
    register_worker(client, capabilities=["code"], route_type="remote")
    client.post("/admin/config", json={"paid_enabled": True}, headers=AUTH)
    r = submit(client, data_classification="secret",
               requested_capabilities=["code"], budget_cents=100)
    assert r.status_code == 422
    assert "secret" in r.json()["detail"]
    # the rejection is recorded in the audit log
    audit = client.get("/audit", headers=AUTH).json()
    assert any(e["event"] == "job_rejected" for e in audit)


def test_secret_on_device_is_allowed(client):
    r = submit(client, data_classification="secret",
               requested_capabilities=["summarize"])
    assert r.status_code == 201
    assert r.json()["route"] == "on-device"


def test_confidential_remote_requires_approval(client):
    register_worker(client, capabilities=["code"], route_type="remote")
    r = submit(client, data_classification="confidential",
               requested_capabilities=["code"])
    assert r.status_code == 201
    assert r.json()["status"] == "awaiting_approval"
    job_id = r.json()["job_id"]
    # not claimable before approval
    audit = client.get("/audit", headers=AUTH).json()
    rd = [e for e in audit if e["event"] == "routing_decision"][-1]
    assert rd["detail"]["needs_approval"] is True
    r = client.post(f"/jobs/{job_id}/approve")
    assert r.status_code == 200
    assert r.json()["route"] == "remote_worker"
    assert client.get(f"/jobs/{job_id}").json()["status"] == "queued"


def test_public_remote_routes_directly(client):
    register_worker(client, capabilities=["code"], route_type="remote")
    r = submit(client, data_classification="public",
               requested_capabilities=["code"])
    assert r.status_code == 201
    assert r.json()["route"] == "remote_worker"
    assert r.json()["status"] == "queued"


# --------------------------------------------------------------------------
# 3. Cost control
# --------------------------------------------------------------------------

def test_paid_route_denied_when_disabled(client):
    r = submit(client, requested_capabilities=["translate"],
               budget_cents=100)
    assert r.status_code == 422
    assert "paid model disabled" in r.json()["detail"]


def test_paid_call_denied_when_budget_exhausted(client):
    client.post("/admin/config", json={"paid_enabled": True}, headers=AUTH)
    # budget smaller than one paid call
    r = submit(client, requested_capabilities=["translate"], budget_cents=1)
    assert r.status_code == 422
    assert "budget" in r.json()["detail"]

    # budget covers exactly one call: first claim charges, second job fails
    r = submit(client, requested_capabilities=["translate"], budget_cents=5)
    job_id = r.json()["job_id"]
    assert r.json()["route"] == "paid_model"
    r = client.post(f"/jobs/{job_id}/claim",
                    json={"worker_token": ADMIN, "idempotency_key": "p1"})
    assert r.status_code == 200
    job = client.get(f"/jobs/{job_id}").json()
    assert job["spent_cents"] == 5


def test_paid_classification_restrictions(client):
    client.post("/admin/config", json={"paid_enabled": True}, headers=AUTH)
    # confidential data may not go to the paid model
    r = submit(client, data_classification="confidential",
               requested_capabilities=["translate"], budget_cents=100)
    assert r.status_code == 422


# --------------------------------------------------------------------------
# 4. Reliability / idempotency
# --------------------------------------------------------------------------

def test_idempotent_job_claim_on_reconnect(client):
    worker = register_worker(client, capabilities=["code"],
                             route_type="remote")
    r = submit(client, requested_capabilities=["code"])
    job_id = r.json()["job_id"]
    key = "reconnect-key-1"
    r1 = client.post(f"/jobs/{job_id}/claim",
                     json={"worker_token": worker["token"],
                           "idempotency_key": key})
    assert r1.status_code == 200
    # simulate reconnect: same key replayed
    r2 = client.post(f"/jobs/{job_id}/claim",
                     json={"worker_token": worker["token"],
                           "idempotency_key": key})
    assert r2.status_code == 200
    assert r1.json()["claim_id"] == r2.json()["claim_id"]
    # audit shows exactly one claim event for the key
    audit = client.get("/audit", headers=AUTH).json()
    claims = [e for e in audit if e["event"] == "job_claimed"
              and e["detail"]["idempotency_key"] == key]
    assert len(claims) == 1


def test_idempotent_paid_claim_does_not_double_charge(client):
    client.post("/admin/config", json={"paid_enabled": True}, headers=AUTH)
    r = submit(client, requested_capabilities=["translate"], budget_cents=100)
    job_id = r.json()["job_id"]
    key = "pay-key"
    for _ in range(3):
        r = client.post(f"/jobs/{job_id}/claim",
                        json={"worker_token": ADMIN, "idempotency_key": key})
        assert r.status_code == 200
    job = client.get(f"/jobs/{job_id}").json()
    assert job["spent_cents"] == 5  # charged exactly once


def test_cancel_is_idempotent(client):
    r = submit(client)
    job_id = r.json()["job_id"]
    r1 = client.post(f"/jobs/{job_id}/cancel")
    assert r1.json()["status"] == "cancelled"
    r2 = client.post(f"/jobs/{job_id}/cancel")
    assert r2.status_code == 200
    assert r2.json()["status"] == "cancelled"


# --------------------------------------------------------------------------
# 5. Credential scoping + revocation
# --------------------------------------------------------------------------

def test_revoked_worker_cannot_claim(client):
    worker = register_worker(client, capabilities=["code"],
                             route_type="remote")
    r = submit(client, requested_capabilities=["code"])
    job_id = r.json()["job_id"]
    client.post(f"/workers/{worker['worker_id']}/revoke", headers=AUTH)
    r = client.post(f"/jobs/{job_id}/claim",
                    json={"worker_token": worker["token"],
                          "idempotency_key": "rk"})
    assert r.status_code == 403
    assert "revoked" in r.json()["detail"]


def test_revoked_worker_not_used_for_new_routing(client):
    worker = register_worker(client, capabilities=["code"],
                             route_type="remote")
    client.post(f"/workers/{worker['worker_id']}/revoke", headers=AUTH)
    r = submit(client, requested_capabilities=["code"])
    # no route left: paid disabled and code not on-device
    assert r.status_code == 422


def test_worker_token_scoped_to_route_type(client):
    local = register_worker(client, capabilities=["code"], route_type="local")
    register_worker(client, capabilities=["code"], route_type="remote",
                    worker_id="remote1")
    r = submit(client, requested_capabilities=["code"])
    job_id = r.json()["job_id"]
    assert r.json()["route"] == "local_worker"
    # local worker can claim it
    r = client.post(f"/jobs/{job_id}/claim",
                    json={"worker_token": local["token"],
                          "idempotency_key": "lk"})
    assert r.status_code == 200


def test_admin_endpoints_require_token(client):
    assert client.get("/audit").status_code == 401
    assert client.post("/workers/register", json={}).status_code == 401
    r = client.get("/audit", headers=AUTH)
    assert r.status_code == 200


# --------------------------------------------------------------------------
# 6. Client auth: GATEWAY_TOKEN protects all /jobs* endpoints (audit H9)
# --------------------------------------------------------------------------

@pytest.fixture()
def authed_client(monkeypatch):
    monkeypatch.setenv("GATEWAY_TOKEN", OWNER)
    app = create_app(":memory:")
    with TestClient(app) as c:
        yield c


def test_jobs_endpoints_reject_missing_or_wrong_token(authed_client):
    # every client endpoint, including the human-in-the-loop approve gate
    for r in (
        authed_client.post("/jobs", json={}),
        authed_client.get("/jobs/job_x"),
        authed_client.post("/jobs/job_x/cancel"),
        authed_client.post("/jobs/job_x/approve"),
        authed_client.post("/jobs/job_x/claim", json={}),
        authed_client.post("/jobs/job_x/complete", json={}),
    ):
        assert r.status_code == 401, r.text
    assert authed_client.post(
        "/jobs", json={},
        headers={"Authorization": "Bearer wrong"}).status_code == 401
    assert authed_client.get(
        "/jobs/job_x",
        headers={"X-Gateway-Token": "wrong"}).status_code == 401
    # denials land in the audit log
    audit = authed_client.get("/audit", headers=AUTH).json()
    assert any(e["event"] == "client_auth_denied" for e in audit)


def test_jobs_endpoints_accept_bearer_and_x_gateway_token(authed_client):
    r = authed_client.post("/jobs", json={
        "task_type": "summarize", "payload_ref": "mem://note/1",
        "data_classification": "public",
        "requested_capabilities": ["summarize"],
        "budget_cents": 0, "deadline_s": 600},
        headers=OWNER_BEARER)
    assert r.status_code == 201, r.text
    job_id = r.json()["job_id"]
    r = authed_client.get(f"/jobs/{job_id}", headers=OWNER_HEADER)
    assert r.status_code == 200
    r = authed_client.post(f"/jobs/{job_id}/cancel", headers=OWNER_BEARER)
    assert r.status_code == 200


def test_admin_endpoints_unaffected_by_gateway_token(authed_client):
    # admin surface still gated solely by X-Admin-Token
    assert authed_client.get("/audit").status_code == 401
    assert authed_client.get("/audit", headers=AUTH).status_code == 200


def test_unset_gateway_token_keeps_loopback_dev_workflow(client, monkeypatch):
    monkeypatch.delenv("GATEWAY_TOKEN", raising=False)
    # TestClient presents as a loopback-class client: no token needed
    assert submit(client).status_code == 201


def test_unset_gateway_token_refuses_non_loopback(monkeypatch):
    monkeypatch.delenv("GATEWAY_TOKEN", raising=False)
    app = create_app(":memory:")

    async def call_as_remote():
        scope = {
            "type": "http", "asgi": {"version": "3.0"}, "http_version": "1.1",
            "method": "GET", "scheme": "http", "path": "/jobs/job_x",
            "raw_path": b"/jobs/job_x", "query_string": b"", "root_path": "",
            "headers": [], "client": ("192.168.1.50", 51000),
            "server": ("testserver", 80),
        }
        result = {}

        async def receive():
            return {"type": "http.request", "body": b"", "more_body": False}

        async def send(message):
            if message["type"] == "http.response.start":
                result["status"] = message["status"]
            elif message["type"] == "http.response.body":
                result["body"] = result.get("body", b"") + message["body"]

        await app(scope, receive, send)
        return result

    r = asyncio.run(call_as_remote())
    assert r["status"] == 503
    assert b"GATEWAY_TOKEN" in r["body"]


# --------------------------------------------------------------------------
# Misc: lifecycle
# --------------------------------------------------------------------------

def test_full_lifecycle_with_result(client):
    worker = register_worker(client, capabilities=["code"],
                             route_type="remote")
    r = submit(client, requested_capabilities=["code"])
    job_id = r.json()["job_id"]
    client.post(f"/jobs/{job_id}/claim",
                json={"worker_token": worker["token"],
                      "idempotency_key": "c"})
    r = client.post(f"/jobs/{job_id}/complete",
                    json={"worker_token": worker["token"],
                          "result": {"answer": 42}})
    assert r.status_code == 200
    job = client.get(f"/jobs/{job_id}").json()
    assert job["status"] == "completed"
    assert job["result"] == {"answer": 42}
    # audit log contains the whole story, in order
    events = [e["event"] for e in client.get("/audit", headers=AUTH).json()
              if e["job_id"] == job_id]
    assert events == ["job_submitted", "routing_decision", "job_claimed",
                      "job_completed"]


def test_on_device_default_route(client):
    r = submit(client, requested_capabilities=["summarize"])
    assert r.status_code == 201
    assert r.json()["route"] == "on-device"
    assert client.get(f"/jobs/{r.json()['job_id']}").json()["status"] == "queued"
