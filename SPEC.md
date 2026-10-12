# 0xPhone Companion — SPEC (Phase 1 prototype)

Two deliverables in one repo `0xphone-companion`:

## A. `gateway/` — secure task gateway adapter (runnable, tested)
Python 3.11+ FastAPI service. This is the piece that enforces "Hermes requests, the OS decides."

Endpoints:
- `POST /jobs` — submit job. Body: `{task_type, payload_ref, data_classification (public|internal|confidential|secret), requested_capabilities[], budget_cents, deadline_s}`. Returns job_id. Rules: `secret` classification → rejected if route would leave device; missing capabilities → rejected.
- `GET /jobs/{id}` — status: `queued|running|awaiting_approval|completed|failed|cancelled`.
- `POST /jobs/{id}/cancel` — idempotent cancel.
- `POST /jobs/{id}/approve` — approve a job in `awaiting_approval`.
- `POST /workers/register` — register worker with scoped capability token (revocable).
- `GET /audit` — append-only audit log (every submission, routing decision, approval, cancel).

Core policy engine (`gateway/policy.py`):
- Routing order: on-device → authorized local/free worker → approved remote worker → paid model (only if authorized + budget remains + classification permits).
- Workers can never exceed granted capabilities; server-side check on every job claim.
- Budget ledger: paid model calls denied when disabled or exhausted.
- Idempotency: reconnect must not duplicate non-idempotent actions (idempotency keys on job claims).

Persistence: SQLite. No external services required.
Tests: pytest covering the MVP acceptance checks that apply server-side (permissions, privacy routing, cost control, reliability/idempotency, credential scoping/revocation). `pytest` must pass.

## B. `android/` — companion app skeleton (Kotlin)
Minimal Android app (Kotlin, Jetpack Compose, minSdk 26):
- `TaskSubmitScreen` — task text, classification picker, worker picker, submit → gateway.
- `JobStatusScreen` — live status, cancel button, result viewer.
- `ApprovalsScreen` — approve/deny pending privileged actions.
- `AuditScreen` — local view of audit history.
- `net/GatewayClient.kt` — Retrofit client matching the gateway API exactly.
No build verification expected (no Android SDK in sandbox) — code must be coherent and match SPEC interfaces.

## Contracts
Gateway API = the contract; Android client mirrors it 1:1. Job schema fields are fixed as above.

## Constraints
- No secrets in code. Token auth via env var `GATEWAY_ADMIN_TOKEN`.
- README.md with quickstart (uvicorn, pytest, Android Studio open instructions).
