# Deployment design

How to run HealthEvidence AI across local, demo, pilot, staging, and Kubernetes. Day-2 ops notes remain in [operations.md](operations.md).

## 1. Runtime gates (`ENVIRONMENT`)

Validated in `app/core/config.py` (`validate_live_configuration`):

| Environment | Auth | Database | PHI |
|-------------|------|----------|-----|
| `local` / `docker` | `dev-jwt` typical | SQLite or Postgres | Prefer `ALLOW_PHI=false` |
| `pilot` | `dev-jwt` or `oidc` | **Postgres required** | Attestation if PHI on |
| `staging` / `production` / `prod` | **`oidc` required** | **Postgres required** | Attestation if PHI on |
| `test` | may be `none` | any | synthetic tests |

`IMAGING_BACKEND` must be `monai` or `monai-isolated` for live configs that validate imaging.

## 2. Docker Compose overlays

| Command | Purpose |
|---------|---------|
| `docker compose up --build` | Base: Postgres + Ollama + API + frontend |
| `… -f docker-compose.pilot.yml` | `ENVIRONMENT=pilot`, Postgres URL |
| `… -f docker-compose.demo.yml` | Sales demo: synthetic PHI flags off, seed on |
| `… -f docker-compose.staging.yml` | Staging: OIDC required |
| `… -f docker-compose.oidc.yml` | Local Keycloak + realm import |

Make targets:

```bash
make demo-up      # pilot + demo overlays
make pilot-up
make pilot-oidc-up
make demo-gate    # pytest + personas + live smoke (API up)
make pilot-gate   # pytest + tests/pilot (Postgres up)
```

Windows: `.\scripts\demo_gate.ps1`, `.\scripts\pilot_gate.ps1`.

## 3. Local process (no Docker API)

```bash
uv sync
cp .env.example .env
uv run python -m app.cli.seed
uv run python -m uvicorn app.main:app --reload --host 127.0.0.1 --port 8010
cd frontend && npm ci && npm run dev -- --host 127.0.0.1 --port 5173
```

See [LAUNCH.md](LAUNCH.md).

## 4. Kubernetes

Manifests under `deploy/kubernetes/`. Apply notes: [kubernetes.md](kubernetes.md).

| Probe | Path |
|-------|------|
| Liveness | `GET /health` |
| Readiness | `GET /ready` |

Sample ConfigMap uses OIDC for shared clusters. Provide Postgres and secrets out-of-band (not committed).

## 5. Configuration surfaces

| Area | Env examples |
|------|----------------|
| DB | `DATABASE_URL` |
| Auth | `AUTH_MODE`, `OIDC_*` |
| Org | `DEFAULT_ORG_CODE`, `ENFORCE_ORG_SCOPE` |
| LLM | `LLM_PROVIDER`, `MODEL_NAME`, provider keys, `LLM_FALLBACK_PROVIDERS` |
| PHI | `ALLOW_PHI`, `PHI_PROGRAM_ATTESTED` |
| Imaging | `IMAGING_BACKEND`, `A2A_ENABLED` |
| Seed | `SEED_ON_STARTUP` |

Templates: [`.env.example`](../.env.example), [`.env.pilot.example`](../.env.pilot.example).

## 6. Quality gates before go-live / demo

| Gate | Command |
|------|---------|
| Unit + integration | `uv run pytest -q` |
| Lint + types + coverage + UI build | `make quality-gate` |
| Frontend build | `make launch-check` |
| Postgres pilot | `make pilot-gate` (or CI `tests/pilot`) |
| Live demo smoke | `make demo-gate` with stack up |
| OpenAPI contract walk | `HE_API_BASE=… uv run python scripts/api_contract_smoke.py` |

Green tests = technical readiness, not clinical certification.

## 7. HA / DR

Repo stub: [operations.md](operations.md#ha--dr-stub-p29--org-completes-runbooks). Org owns RTO/RPO, backup drills, and on-call.

## Related

- [HLD.md](HLD.md)
- [OIDC_PILOT.md](OIDC_PILOT.md)
- [PRODUCTION_CHECKLIST.md](PRODUCTION_CHECKLIST.md)
- [PILOT_ROADMAP.md](PILOT_ROADMAP.md)
