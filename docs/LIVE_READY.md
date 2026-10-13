# Live-ready hospital desk

This is the go-live runbook for shared hospital environments (staging / production / Kubernetes). Completing these steps makes the **platform** live-ready. Turning on live PHI still requires an attested privacy program and EHR change-control.

## What “live ready” means here

| Layer | Ready when |
|-------|------------|
| Platform | OIDC, Postgres, seed off, org scope on, simulator off, `/ready` green |
| Practice feeds | HIS/FHIR webhooks with `synthetic=true` + `consent_attested=true` |
| Live PHI feeds | `ALLOW_PHI=true` **and** `PHI_PROGRAM_ATTESTED=true` + change-control signed |

Real-data trial runbook (prerequisites, `make go-live-check MODE=trial`, monitoring, stop
criteria): [GO_LIVE.md](GO_LIVE.md).

Default remains **synthetic / practice**. The product is evidence-pack decision support — not a clinical device.

## Hospital interface (completed platform pieces)

- Durable runs: `hospital_pipeline_runs` (status survives restart)
- Machine auth: `HOSPITAL_INTERFACE_KEYS=ORG-000001:<key>,...` (each ≥32 chars) → header
  `X-Hospital-Api-Key`; the caller authenticates as `hospital-interface:ORG-xxxxxx` bound to that
  org. The legacy single `HOSPITAL_INTERFACE_API_KEY` has no org and is refused while org scope is on.
- SSE: the desk calls `POST /api/v1/events/stream-ticket` (bearer) and opens
  `/api/v1/events/stream?ticket=…` (60 s, single-use, signed with `STREAM_TICKET_SECRET`).
  `?access_token=` is no longer accepted.
- Rate limiting (`RATE_LIMIT_*`): in-process sliding window **per replica** — auth 20/min per IP,
  OPD + hospital pipeline 120/min and evidence search + tool invoke 120/min per principal (or IP).
  429 responses carry `Retry-After`. A shared Redis-backed limiter is future work.
- Multi-replica desk: `REDIS_URL` + `uv sync --extra realtime`
- Pack export: `GET /api/v1/authorization/cases/{case_id}/export.pdf`
- SLA: `PACKET_SLA_MINUTES` (default 240) on Today / ops metrics

## Hard gates (enforced at boot)

When `ENVIRONMENT` is `staging`, `production`, `prod`, or `kubernetes`:

1. `AUTH_MODE=oidc` with `OIDC_ISSUER` + `OIDC_JWKS_URL`
2. PostgreSQL only (no SQLite)
3. `SEED_ON_STARTUP=false`
4. `ENFORCE_ORG_SCOPE` enabled (or unset for auto-on)
5. `ALLOW_PHI` requires `PHI_PROGRAM_ATTESTED=true`
6. Hospital simulator off when PHI live is attested

Alembic upgrades **fail closed** on shared Postgres (pilot + shared live).

## Quick verify

```bash
curl -s http://127.0.0.1:8000/health
curl -s http://127.0.0.1:8000/ready
# expect: status=ok, seed_on_startup=false, auth_mode=oidc, org_scope=true

curl -s "http://127.0.0.1:8000/api/v1/auth/oidc/status?discover=true"
curl -s -H "Authorization: Bearer $TOKEN" \
  http://127.0.0.1:8000/api/v1/hospital/pipeline/status
# expect: mode=synthetic_practice (or production_phi) ; simulate_allowed=false in prod
```

Automated:

```bash
uv run pytest tests/unit/test_live_ready.py tests/unit/test_production_readiness.py -q
uv run python scripts/big_hospital_verify.py   # practice desk with HE_API_BASE
```

## Staging bring-up

```bash
export OIDC_ISSUER=...
export OIDC_JWKS_URL=...
docker compose -f docker-compose.yml -f docker-compose.staging.yml up --build
```

Compose staging defaults: `SEED_ON_STARTUP=false`, `ENFORCE_ORG_SCOPE=true`, `HOSPITAL_ALLOW_SIMULATE=false`.

Kubernetes ConfigMap (`deploy/kubernetes/configmap.yaml`) uses `ENVIRONMENT=production` with the same hard gates. Put issuer/JWKS and DB URL in Secrets — never git.

## Enabling live PHI (after program sign-off)

1. Complete [OPD change-control](opd-ingest-roadmap.md#change-control-p26--before-any-live-ehr-feed)
   and every prerequisite in [GO_LIVE.md §2.1](GO_LIVE.md#21-non-code-prerequisites-all-signed-before-allow_phitrue)
2. Set `ALLOW_PHI=true` and `PHI_PROGRAM_ATTESTED=true` plus the trial attestations
   (`TRIAL_ETHICS_APPROVAL_REF`, `DPO_CONTACT`, `SECURITY_ASSESSMENT_REF`, `BREACH_RUNBOOK_URL`,
   `DATA_RESIDENCY_REGION`, `TRIAL_SITE_ORG_CODE`, `TRIAL_END_DATE`). Boot fails otherwise
3. Confirm `HOSPITAL_ALLOW_SIMULATE=false`
4. Send HIS/FHIR packets with `synthetic=false` and `consent_attested=true`
5. Re-check `/ready` → `phi_live=true`, `hospital_mode=production_phi`, `mode=trial`

## Operator checklist

- [ ] IdP live; tokens carry product roles + `org_id` / `org_code`
- [ ] `/ready` 200 on Postgres; migrations at Alembic head
- [ ] No seed in shared live; no weaken `ENFORCE_ORG_SCOPE=false`
- [ ] Break-glass policy + sample audit reviewed
- [ ] Backup / restore drill documented
- [ ] HIS/FHIR interface accounts use least-privilege roles (`staff` / chart-write)
- [ ] Clinical / legal sign non-device decision-support language

See also: [PRODUCTION_CHECKLIST.md](PRODUCTION_CHECKLIST.md), [OIDC_PILOT.md](OIDC_PILOT.md), [DEPLOYMENT.md](DEPLOYMENT.md).
