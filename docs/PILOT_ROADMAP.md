# Pilot → production → demo roadmap

**Your sequence:** finish **pilot** and **production** foundations first, then **demo** polish last.  
Demo must run on the same stack pilots use (PostgreSQL, real auth path), not a separate SQLite fork.

**Repo completion:** Phase 1–3 deliverables in this repository are **Complete**. Remaining work (clinical validation, pen test, regulatory, live EHR sign-off) is organizational.

## Phase 1 — Pilot-ready (this repo, weeks)

| Epic | Deliverable | Status |
|------|-------------|--------|
| P1.1 | `ENVIRONMENT=pilot` gates: PostgreSQL required, `dev-jwt` or `oidc` | Done |
| P1.2 | Docker pilot overlay [`docker-compose.pilot.yml`](../docker-compose.pilot.yml) + [`.env.pilot.example`](../.env.pilot.example) | Done |
| P1.3 | Postgres bootstrap tests [`tests/pilot/`](../tests/pilot/) + CI job | Done |
| P1.4 | `make pilot-gate` / [`scripts/pilot_gate.ps1`](../scripts/pilot_gate.ps1) | Done |
| P1.5 | OIDC role mapping (Keycloak/Entra), `GET /api/v1/auth/oidc/status`, tests | Done |
| P1.6 | Audit export `GET /api/v1/audit/events` (admin) | Done |
| P1.7 | Live persona smoke via `HE_API_BASE` + [`scripts/_smoke_web_api.py`](../scripts/_smoke_web_api.py) | Done |
| P1.8 | Secrets: `.env` gitignored; keep `.env.example` / `.env.pilot.example` only | Done |
| P1.9 | Wire real IdP — Keycloak compose + discover CLI + [OIDC_PILOT.md](OIDC_PILOT.md) | Done |
| P1.10 | Ten-persona against live Postgres [`tests/pilot/test_ten_personas_postgres.py`](../tests/pilot/test_ten_personas_postgres.py) | Done |

**Pilot gate (local):**

```bash
docker compose up -d postgres
# Windows
.\scripts\pilot_gate.ps1
# or
set PILOT_POSTGRES_TEST=1
set DATABASE_URL=postgresql+psycopg://healthevidence:healthevidence@127.0.0.1:5432/healthevidence
uv run pytest -q
uv run pytest tests/pilot -v
# OIDC IdP (optional Keycloak):
docker compose -f docker-compose.yml -f docker-compose.pilot.yml -f docker-compose.oidc.yml up --build
uv run python -m app.cli.oidc_discover http://127.0.0.1:8080/realms/healthevidence
# See docs/OIDC_PILOT.md
```

**Pilot stack (full compose):**

```bash
docker compose -f docker-compose.yml -f docker-compose.pilot.yml up --build
```

## Phase 2 — Production-ready (repo + organization)

**Repo status: Complete.** Org/program items (validation study, pen test, regulatory) remain outside this repository.

Detailed checklist: [PRODUCTION_CHECKLIST.md](PRODUCTION_CHECKLIST.md).

| Epic | Deliverable | Status |
|------|-------------|--------|
| P2.1 | `/ready` DB probe; K8s readiness → `/ready` | Done |
| P2.2 | Admin break-glass + audit (`POST /api/v1/security/break-glass`) | Done |
| P2.3 | [`docker-compose.staging.yml`](../docker-compose.staging.yml) (OIDC required) | Done |
| P2.4 | Production checklist doc | Done |
| P2.5 | Multi-org + `ENFORCE_ORG_SCOPE` (list/chart/desk/OPD/auth writes) | Done |
| P2.6 | OPD path + EHR change-control checklist ([opd-ingest-roadmap.md](opd-ingest-roadmap.md)) | Done (repo); org signs feed |
| P2.7–P2.8 | Clinical validation, security assessment | Org / later |
| P2.9 | HA/DR stub in [operations.md](operations.md) + K8s replicas | Done (repo); org owns RTO/RPO |
| P2.10 | Regulatory classification | Org / later |


Program work outside a single sprint — also [clinical-product-roadmap.md](clinical-product-roadmap.md):

1. Regulatory / device classification (jurisdiction-specific)
2. Clinical validation with licensed clinicians
3. Enterprise SSO, break-glass policy review (API done; policy is org)
4. EHR / FHIR ingest under change control ([opd-ingest-roadmap.md](opd-ingest-roadmap.md))
5. Security assessment, HA/DR, support SLAs
6. `ENVIRONMENT=production`: `AUTH_MODE=oidc`, PostgreSQL, PHI flags only with attestation

**Repo gates already enforced:** staging/production reject SQLite and require OIDC ([`app/core/config.py`](../app/core/config.py)).

## Phase 3 — Demo polish (after Phase 1–2 baseline)

**Repo status: Complete.**

| Deliverable | Status |
|-------------|--------|
| Synthetic-only demo compose ([`docker-compose.demo.yml`](../docker-compose.demo.yml)) on pilot Postgres | Done |
| [LAUNCH.md](LAUNCH.md) labeled **Demo** vs **Pilot** | Done |
| UI copy / layout for stakeholders (no pipeline jargon) | Done |
| Smoke + persona matrix on the **pilot** URL before every demo | Done — `make demo-gate` / [`scripts/demo_gate.ps1`](../scripts/demo_gate.ps1) |

**One-command demo (sales):**

```bash
docker compose -f docker-compose.yml -f docker-compose.pilot.yml -f docker-compose.demo.yml up --build
# or: make demo-up
# UI http://127.0.0.1:3000 — walk docs/LAUNCH.md Demo path
make demo-gate
# Windows: .\scripts\demo_gate.ps1
```

## Feature breadth (your “everything ready” goal)

Build features **on pilot stack**, not SQLite-only shortcuts:

| Area | Pilot note |
|------|------------|
| PA packet + lifelong chart | Core — keep deepening on Postgres |
| Desk (insights, worklist, ops metrics) | Care-team RBAC |
| Multi-org | Required before multi-facility pilot |
| OPD / visit note ingest | Synthetic until PHI attested |
| Help desk, imaging, MCP tools | Product-facing; test in persona matrix |
| Dashboards / analytics | After ops metrics stable on Postgres |

## Quality gates (all phases)

```bash
uv run pytest -q
uv run pytest tests/integration/test_ten_personas.py -v
# with Postgres up:
PILOT_POSTGRES_TEST=1 DATABASE_URL=postgresql+psycopg://... uv run pytest tests/pilot -v
HE_API_BASE=http://127.0.0.1:8000 python scripts/_smoke_web_api.py
```

Green tests prove **technical readiness**, not clinical certification or payer approval.

## Secrets hygiene (P1.8)

- Never commit `.env`, API keys, or IdP client secrets
- Templates only: [`.env.example`](../.env.example), [`.env.pilot.example`](../.env.pilot.example)
- Shared pilot: store secrets in the host secret manager / Key Vault; inject as env vars
- `GET /api/v1/auth/oidc/status` reports config presence, never secret values
- Admin audit export: `GET /api/v1/audit/events` (no clinical note bodies)
