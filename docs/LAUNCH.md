# Launch

Paths for **Demo** (sales) vs **Pilot** (shared tenant). Same product; different stack expectations.

> **Going live?** Use [GO_LIVE.md](GO_LIVE.md): the step-by-step DEMO runbook and the
> REAL-DATA TRIAL runbook (non-code prerequisites, `make go-live-check MODE=demo|trial`,
> `docker-compose.trial.yml`, monitoring, stop criteria). Green CI is not clinical or legal approval.

**Product:** prior-auth evidence prep + lifelong digital health record across hospitals.  
**Stance:** decision support for documentation readiness — not a medical device; does not diagnose, approve, or deny care.

| Path | Use when | Stack |
|------|----------|--------|
| **Demo** | Stakeholder walkthrough, synthetic only | Postgres + `dev-jwt` + seed ([`docker-compose.demo.yml`](../docker-compose.demo.yml)) |
| **Pilot** | Shared UAT / IdP | Postgres + **OIDC required** ([`PILOT_ROADMAP.md`](PILOT_ROADMAP.md), [`OIDC_PILOT.md`](OIDC_PILOT.md)) |
| **Staging / prod** | Accountable environments | OIDC required ([`PRODUCTION_CHECKLIST.md`](PRODUCTION_CHECKLIST.md)) |
| **Real-data trial** | One hospital, real patients, IEC-approved | [`docker-compose.trial.yml`](../docker-compose.trial.yml) + [`GO_LIVE.md`](GO_LIVE.md) |

## Prerequisites

- Python 3.12+, [uv](https://docs.astral.sh/uv/), Node.js 22+
- LLM: `local` (always-on), or Ollama / OpenAI / Anthropic / Gemini via `.env`
- Auth: `AUTH_MODE=dev-jwt` **locally only** (set `DEV_JWT_SECRET` ≥ 32 chars; `/auth/dev-token` is disabled in pilot/staging/production). Pilot and shared live require `AUTH_MODE=oidc`.

## One-time setup (local / demo)

```bash
uv sync
cp .env.example .env
# Set LLM_PROVIDER + credentials (gemini | openai | anthropic | ollama | local)
# Confirm AUTH_MODE=dev-jwt, DEV_JWT_SECRET (≥32 chars), and OIDC_REQUIRED_ROLES includes:
# patient,senior_clinician,resident,staff,admin,reviewer

uv run python -m app.cli.seed
cd frontend && npm ci
```

---

## Demo — one-command Docker (sales)

Uses the **pilot Postgres path** with synthetic seed and PHI flags off:

```bash
# Demo uses ENVIRONMENT=local + AUTH_MODE=dev-jwt (not pilot auth).
# Set your own signing secret first (≥32 characters):
export DEV_JWT_SECRET="$(openssl rand -hex 24)"   # Windows: set in .env
docker compose -f docker-compose.yml -f docker-compose.pilot.yml -f docker-compose.demo.yml up --build
```

- UI: [http://127.0.0.1:3000](http://127.0.0.1:3000)
- API: [http://127.0.0.1:8000](http://127.0.0.1:8000)

Before a live stakeholder session on a shared host:

```bash
make go-live-check MODE=demo GO_LIVE_FLAGS=--offline   # config gate (see GO_LIVE.md)
make demo-gate
# Windows: .\scripts\demo_gate.ps1
# or: HE_API_BASE=http://127.0.0.1:8000 python scripts/_smoke_web_api.py
```

### Demo — local (no Docker)

Terminal 1 — API:

```bash
uv run python -m uvicorn app.main:app --reload --host 127.0.0.1 --port 8010
```

Terminal 2 — UI:

```bash
cd frontend && npm run dev -- --host 127.0.0.1 --port 5173
```

Open: [http://127.0.0.1:5173](http://127.0.0.1:5173) (proxies `/api` → `:8010`)

### Demo path (sales / stakeholder)

1. Top bar → **Facility** (e.g. Multispecialty) + **Signed-in** role.
2. **Patient (my record)** → Lifelong history (surgeries, disc/back pain, physio, LSCS-style milestones) → **Add note**.
3. Switch to **Records / PA staff** → **Patients** → open chart → sticky age/sex/DOB → **Lifelong history** → **Prepare packet**.
4. Close a gap with **Visit note** (hospital + department) → re-check readiness → copy handoff.
5. Switch to **Senior clinician** → **Reviews** → Check evidence → acknowledge or send back (never approve/deny).
6. Confirm UI never shows raw RBAC errors or “Your desk…” coaching copy.

Live sample cases: `PA-000001` (complete) · `PA-000002` (gaps / human review).

---

## Pilot (shared tenant)

Pilot **requires** `AUTH_MODE=oidc` (dev-jwt minting is disabled). Use Keycloak or your IdP:

```bash
cp .env.pilot.example .env.pilot
# Set OIDC_ISSUER + OIDC_JWKS_URL (see .env.pilot.example)
docker compose -f docker-compose.yml -f docker-compose.pilot.yml -f docker-compose.oidc.yml up --build
```

Details: [PILOT_ROADMAP.md](PILOT_ROADMAP.md), [OIDC_PILOT.md](OIDC_PILOT.md).

Org scoping (multi-facility): set `ENFORCE_ORG_SCOPE=true` and mint care-team tokens with `org_code` / `org_id`.

---

## Verification gate

```bash
uv run pytest -q
cd frontend && npm run build
```

API smoke:

```bash
curl -s http://127.0.0.1:8010/health
curl -s -X POST http://127.0.0.1:8010/api/v1/auth/dev-token ^
  -H "Content-Type: application/json" ^
  -d "{\"subject\":\"launch\",\"roles\":[\"senior_clinician\"]}"
```

Checklist:

- [ ] `/health` returns ok
- [ ] Dev token mints for `staff`, `resident`, `senior_clinician`, `patient`
- [ ] Lifelong summary: `GET /api/v1/patients/PAT-000001/lifelong`
- [ ] Prepare packet works as staff
- [ ] Reviews HITL resume works as senior; forbidden as staff/resident/patient
- [ ] Frontend production build succeeds
- [ ] Ops metrics: `GET /api/v1/metrics/ops` returns packet cycle fields
- [ ] Organizations: `GET /api/v1/organizations` returns demo org
- [ ] No clinical approve/deny language in packet or review outputs

## Pitch line

> Cut prior-auth chart-chase time with readiness packets seniors can acknowledge — on a lifelong multi-hospital chart. Never an approval engine.

## Related

- [Go-live runbooks (demo + real-data trial)](GO_LIVE.md)
- [Operations](operations.md)
- [Kubernetes](kubernetes.md)
- [Safety notes](clinical-product-roadmap.md)
- [README](../README.md)
