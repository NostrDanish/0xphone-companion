# 0xPhone Companion — Phase 1 prototype

"Hermes requests, the OS decides." Two deliverables, one contract (see `SPEC.md`):

- `gateway/` — FastAPI secure task gateway: policy engine, SQLite persistence, audit log.
- `android/` — Kotlin/Jetpack Compose companion app skeleton mirroring the gateway API 1:1.

## Quickstart

### Gateway

Requires Python 3.11+.

```bash
cd 0xphone-companion
pip install -r requirements.txt

# owner pairing token: protects ALL client /jobs* endpoints (submit, status,
# cancel, and the human-in-the-loop approve gate). Clients send it as
# `Authorization: Bearer $GATEWAY_TOKEN` (or `X-Gateway-Token`).
# REQUIRED before binding beyond loopback (e.g. any tunnel deployment):
# if unset, /jobs* stays open to loopback clients (dev workflow) but the
# server REFUSES non-loopback clients (503) and logs a loud warning.
export GATEWAY_TOKEN="$(openssl rand -hex 32)"
# admin token protects /workers/register, /workers/{id}/revoke, /audit, /admin/config
export GATEWAY_ADMIN_TOKEN="dev-token"
# optional: file-backed DB (default is in-memory), paid models off by default
# export GATEWAY_DB=gateway.db
# export GATEWAY_PAID_ENABLED=1

uvicorn gateway.app:app --reload --port 8000
```

Try it:

```bash
# submit a job (routed on-device)
curl -X POST localhost:8000/jobs -H "Authorization: Bearer $GATEWAY_TOKEN" \
  -H 'content-type: application/json' -d '{
  "task_type": "summarize", "payload_ref": "mem://note/1",
  "data_classification": "public",
  "requested_capabilities": ["summarize"],
  "budget_cents": 0, "deadline_s": 600}'

# register a remote worker (returns a scoped, revocable capability token)
curl -X POST localhost:8000/workers/register \
  -H "X-Admin-Token: $GATEWAY_ADMIN_TOKEN" -H 'content-type: application/json' -d '{
  "capabilities": ["code"], "route_type": "remote", "free": true}'

# view the append-only audit log
curl localhost:8000/audit -H "X-Admin-Token: $GATEWAY_ADMIN_TOKEN"
```

Note: worker calls to `/jobs/{id}/claim` and `/jobs/{id}/complete` must also
carry the gateway token header in addition to their scoped `worker_token` in
the request body.

### Tests

```bash
cd 0xphone-companion
python -m pytest tests/ -v
```

Covers the server-side MVP acceptance checks: capability enforcement,
privacy routing (`secret` never leaves the device), cost control (paid calls
denied when disabled or budget exhausted), idempotent job claims on
reconnect, credential scoping/revocation, and client auth (`GATEWAY_TOKEN`
gating of all `/jobs*` endpoints, incl. non-loopback refusal when unset).
**24/24 passing.**

### Android app

1. Open `android/` in Android Studio (Hedgehog or newer).
2. Provide the tokens via `local.properties` (`GATEWAY_TOKEN=...`,
   `GATEWAY_ADMIN_TOKEN=dev-token`) or environment variables — never commit
   them. `GATEWAY_TOKEN` is sent as `Authorization: Bearer` on every request.
3. Run on an emulator (minSdk 26). The app targets the gateway at
   `http://10.0.2.2:8000/` (emulator loopback to the host running uvicorn).

No build verification is expected in the sandbox (no Android SDK); the code
mirrors the gateway API exactly (`android/app/.../net/GatewayClient.kt` ↔
`gateway/models.py`).

Security notes: release builds forbid cleartext traffic
(`usesCleartextTraffic="false"`); a debug-only manifest overlay re-enables
it so the emulator→host dev loop keeps working. The stack-trace crash
reporter (`CompanionApplication`) is installed only in `BuildConfig.DEBUG`
builds.

## Policy summary (gateway/policy.py)

Routing order: on-device → authorized local/free worker → approved remote
worker → paid model (only if enabled + budget remains + classification
permits). `secret` data is rejected whenever the only routes would leave the
device. Workers can never exceed granted capabilities (checked server-side on
every claim). All submissions, routing decisions, approvals, cancels, claims,
and denials land in the append-only audit log (`GET /audit`).
