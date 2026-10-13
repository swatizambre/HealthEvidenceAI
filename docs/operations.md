# Operations

## Environments

| Environment | Auth | Database | LLM |
| --- | --- | --- | --- |
| `local` / `docker` | `dev-jwt` | SQLite or PostgreSQL | Ollama, OpenAI, Anthropic, or Gemini |
| `pilot` | `dev-jwt` or `oidc` | PostgreSQL (required) | Configured provider |
| `staging` / `production` | `oidc` (required) | PostgreSQL (required) | Configured live provider |

Pilot rollout order and epics: [PILOT_ROADMAP.md](PILOT_ROADMAP.md).

Startup validates production and staging settings and fails closed when incomplete.

## Locales and residency

- `DEFAULT_LOCALE` / `SUPPORTED_LOCALES` — UI and API metadata for multi-market deployments
- `DATA_RESIDENCY_REGION` — label for regional deployment inventories

## Observability

Enable tracing with `ENABLE_TRACING=true`. Wire Langfuse or OpenTelemetry exporters through the corresponding environment variables when available.

## Imaging

`IMAGING_BACKEND=monai` is required. Install the optional imaging extra for full MONAI transforms:

```bash
uv sync --extra imaging
```

Without that extra, the service uses a NumPy tensor bridge with the same non-diagnostic contract.

## Kubernetes

See [kubernetes.md](kubernetes.md), [DEPLOYMENT.md](DEPLOYMENT.md), and manifests under `deploy/kubernetes/`.

- Liveness: `GET /health`
- Readiness: `GET /ready` (database connectivity)
- Staging overlay: `docker-compose.staging.yml` (requires OIDC env)
- Production checklist: [PRODUCTION_CHECKLIST.md](PRODUCTION_CHECKLIST.md)

## HA / DR (P2.9 — operator-owned targets)

Repo starting points (not a certified DR plan). Operators still own RTO/RPO, on-call, and restore evidence.

| Topic | In-repo starting point |
|-------|------------------------|
| API replicas / HPA | `deploy/kubernetes/api-deployment.yaml` (2 replicas + HPA) |
| Readiness / liveness | `/ready` (DB + live surface), `/health` |
| Postgres | Operator-managed backups; restore drill before go-live |
| Desk realtime multi-replica | `REDIS_URL` + `uv sync --extra realtime` |
| Hospital feeds | Persist runs in `hospital_pipeline_runs`; `HOSPITAL_INTERFACE_API_KEY` for HIS/FHIR |
| Secrets | Vault / K8s secrets — never git |
| Break-glass | `POST /api/v1/security/break-glass` + audit export |
| Org scope | `ENFORCE_ORG_SCOPE` + IdP org claims ([OIDC_PILOT.md](OIDC_PILOT.md)) |
| Packet SLA | `PACKET_SLA_MINUTES` (default 240) → Today `sla_breached` + ops `sla_breach_count` |

### Suggested targets (fill with site values)

| Metric | Suggested starting point | Site value |
|--------|--------------------------|------------|
| RTO (API) | ≤ 60 minutes | _____ |
| RPO (Postgres) | ≤ 15 minutes (PITR) | _____ |
| Backup | Daily full + WAL / continuous | _____ |
| Restore drill | Quarterly proven restore | _____ |
| On-call | Primary + secondary; break-glass owner | _____ |

Go-live checklist: [LIVE_READY.md](LIVE_READY.md).
