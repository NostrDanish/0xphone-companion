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
curl -X POST localhost:8000/jobs -H 'content-type: application/json' -d '{
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

### Tests

```bash
cd 0xphone-companion
python -m pytest tests/ -v
```

Covers the server-side MVP acceptance checks: capability enforcement,
privacy routing (`secret` never leaves the device), cost control (paid calls
denied when disabled or budget exhausted), idempotent job claims on
reconnect, and credential scoping/revocation. **19/19 passing.**

### Android app

1. Open `android/` in Android Studio (Hedgehog or newer).
2. Provide the admin token via `local.properties` (`GATEWAY_ADMIN_TOKEN=dev-token`)
   or an environment variable — never commit it.
3. Run on an emulator (minSdk 26). The app targets the gateway at
   `http://10.0.2.2:8000/` (emulator loopback to the host running uvicorn).

No build verification is expected in the sandbox (no Android SDK); the code
mirrors the gateway API exactly (`android/app/.../net/GatewayClient.kt` ↔
`gateway/models.py`).

## Policy summary (gateway/policy.py)

Routing order: on-device → authorized local/free worker → approved remote
worker → paid model (only if enabled + budget remains + classification
permits). `secret` data is rejected whenever the only routes would leave the
device. Workers can never exceed granted capabilities (checked server-side on
every claim). All submissions, routing decisions, approvals, cancels, claims,
and denials land in the append-only audit log (`GET /audit`).
