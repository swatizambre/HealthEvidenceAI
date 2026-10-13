# Production / staging readiness checklist (Phase 2)

**Order:** Pilot (Phase 1) → **Production foundations (this doc)** → Demo polish (Phase 3).  
This checklist is for accountable operators. Completing repo items does **not** certify clinical use.

**Real patient data:** follow [GO_LIVE.md](GO_LIVE.md) (real-data trial runbook) and run
`make go-live-check MODE=trial`. When `ALLOW_PHI` + `PHI_PROGRAM_ATTESTED` are true the API also
requires `TRIAL_ETHICS_APPROVAL_REF`, `DPO_CONTACT`, `SECURITY_ASSESSMENT_REF`,
`BREACH_RUNBOOK_URL`, a concrete `DATA_RESIDENCY_REGION`, `TRIAL_SITE_ORG_CODE` and a
non-past `TRIAL_END_DATE`, in any environment.

See also: [clinical-product-roadmap.md](clinical-product-roadmap.md), [PILOT_ROADMAP.md](PILOT_ROADMAP.md), [OIDC_PILOT.md](OIDC_PILOT.md).

## Phase 2 epics (repo + org)

| Epic | Repo deliverable | Org / program |
|------|------------------|---------------|
| P2.1 | `/ready` DB probe + K8s probes | Load balancer / SRE |
| P2.2 | Break-glass audit API (`POST /api/v1/security/break-glass`) | Break-glass policy + review |
| P2.3 | Staging compose / prod config gates | Staging IdP + secrets |
| P2.4 | Production checklist (this doc) | Sign-off owners |
| P2.5 | `ENFORCE_ORG_SCOPE` + org claims on tokens; chart/list filter | Assign facilities in IdP; panel rules |
| P2.6 | OPD ingest path + [change-control checklist](opd-ingest-roadmap.md#change-control-p26--before-any-live-ehr-feed) | Sign EHR feed change record |
| P2.7 | — | Clinical validation study |
| P2.8 | — | Security assessment / pen test |
| P2.9 | — | HA/DR runbooks + SLA ([operations.md](operations.md) stub) |
| P2.10 | — | Regulatory classification |

## Runtime gates (already enforced)

When `ENVIRONMENT` is `staging`, `production`, `prod`, or `kubernetes`:

- `AUTH_MODE=oidc` with `OIDC_ISSUER` + `OIDC_JWKS_URL`
- PostgreSQL only (no SQLite)
- `SEED_ON_STARTUP=false` (hard fail if seed on)
- `ENFORCE_ORG_SCOPE` on (or unset for auto-on)
- `ALLOW_PHI=true` requires `PHI_PROGRAM_ATTESTED=true`
- Hospital simulator off for attested PHI live (and by default in staging compose)

When `ALLOW_PHI` **and** `PHI_PROGRAM_ATTESTED` are true (any `ENVIRONMENT`): never
`local`/`test`, OIDC, PostgreSQL, org scope on, seed off, synthetic lifelong off, plus the
trial attestations listed in [GO_LIVE.md §2.3](GO_LIVE.md#23-configuration).

Go-live runbook: [LIVE_READY.md](LIVE_READY.md).

Check:

```bash
curl -s http://127.0.0.1:8000/health
curl -s http://127.0.0.1:8000/ready
curl -s "http://127.0.0.1:8000/api/v1/auth/oidc/status?discover=true"
```

## Staging stack

```bash
# Requires real OIDC issuer/JWKS in the environment
docker compose -f docker-compose.yml -f docker-compose.staging.yml up --build
```

## Break-glass

Admins declare emergency chart access with a written reason; the event is audit-logged (no note body):

```bash
curl -s -X POST http://127.0.0.1:8000/api/v1/security/break-glass \
  -H "Authorization: Bearer $ADMIN_TOKEN" \
  -H "Content-Type: application/json" \
  -d '{"patient_id":"PAT-000002","reason":"On-call override for PA documentation review"}'
```

Export: `GET /api/v1/audit/events?action=break_glass` (admin).

## Pre-go-live checklist

- [ ] Staging IdP live; `AUTH_MODE=oidc`; `/auth/oidc/status` → `oidc_ready`
- [ ] `/ready` returns 200 against Postgres
- [ ] `PILOT_POSTGRES_TEST=1` pytest + ten-persona green on staging DB
- [ ] Secrets only in vault / K8s secrets (not git)
- [ ] Break-glass policy documented; sample audit reviewed
- [ ] `ALLOW_PHI=false` unless program attested
- [ ] Backup / restore drill for Postgres
- [ ] On-call / SLA contacts listed in ops runbook
- [ ] Clinical / legal stakeholders signed non-device decision-support language
- [ ] `make go-live-check MODE=trial` has no FAIL (WARNs have a written owner decision)
- [ ] Real-data trial prerequisites in [GO_LIVE.md §2.1](GO_LIVE.md#21-non-code-prerequisites-all-signed-before-allow_phitrue) signed

## Demo (Phase 3 — only after staging green)

Use the **same** Postgres + auth path with synthetic data and sales UI polish — see [LAUNCH.md](LAUNCH.md).
