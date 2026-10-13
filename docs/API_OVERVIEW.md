# API overview

Base path for domain APIs: **`/api/v1`**.  
Live contract: OpenAPI at **`/docs`** (and `/openapi.json`) when the server is running.

Auth: Bearer JWT unless noted. Product roles: `patient`, `staff`, `resident`, `senior_clinician`, `admin` (legacy `reviewer` → senior).

## Platform

| Method | Path | Auth | Notes |
|--------|------|------|-------|
| GET | `/health` | Public | Liveness |
| GET | `/ready` | Public | Readiness (DB probe) |
| GET | `/docs` | Public | Swagger UI |
| GET | `/openapi.json` | Public | OpenAPI schema |

## Auth — `/api/v1/auth`

| Method | Path | Auth | Notes |
|--------|------|------|-------|
| POST | `/auth/dev-token` | Public | Mint HS256 token when `AUTH_MODE` is `dev-jwt`/`none`; body: roles, optional `patient_id`, `org_id`/`org_code` |
| GET | `/auth/me` | Bearer | Subject, roles, product_roles, patient_id, org claims |
| GET | `/auth/oidc/status` | Public | Config presence / optional discover; never secrets |

## Patients — `/api/v1/patients`

Requires chart-read roles; patient self-scope enforced.

| Method | Path | Notes |
|--------|------|-------|
| GET | `/patients` | List (self-only for patient; org-filtered when enforced) |
| GET | `/patients/{id}` | Chart detail |
| GET | `/patients/{id}/essentials` | Sticky demographics |
| GET | `/patients/{id}/timeline` | Timeline |
| GET | `/patients/{id}/lifelong` | Lifelong summary |
| GET | `/patients/{id}/documents` | Document list |

## Policies & documents

| Method | Path | Notes |
|--------|------|-------|
| GET | `/policies` | Policy catalog |
| GET | `/policies/{id}` | Policy + criteria |
| GET | `/documents/{id}` | Document content |
| POST | `/documents` | Create document (write roles + scope) |

## Evidence

| Method | Path | Notes |
|--------|------|-------|
| POST | `/evidence/search` | Hybrid RAG search |
| POST | `/evidence/graph` | Evidence graph from review-shaped payload |

## Authorization — `/api/v1/authorization`

| Method | Path | Roles | Notes |
|--------|------|-------|-------|
| GET | `/authorization/cases` | Care team | Org-filtered when enforced |
| POST | `/authorization/prepare` | Packet prep | Patient + org access enforced |
| POST | `/authorization/review` | Evidence check | `interactive` pauses at HITL |
| POST | `/authorization/review/{run_id}/resume` | HITL (senior/admin) | Patient access from saved run |

## OPD / visit ingest — `/api/v1/opd`

| Method | Path | Notes |
|--------|------|-------|
| POST | `/opd/ingest` | Manual HIS-style packet; synthetic + consent by default |
| POST | `/opd/ingest/fhir` | FHIR R4 Bundle map then ingest |

## Desk / meta

Mounted without extra prefix (still under `/api/v1`):

| Method | Path | Notes |
|--------|------|-------|
| GET | `/stats` | Counts (org-aware when enforced) |
| GET | `/worklist` | Today queue |
| GET | `/insights` | Care insights cards |
| GET | `/specialties` | Specialty catalog |
| GET | `/metrics/ops` | Packet cycle-time metrics |
| GET | `/organizations` | Tenant orgs |

## Tools / A2A / imaging

| Method | Path | Notes |
|--------|------|-------|
| GET | `/tools` | MCP tool catalog |
| POST | `/tools/invoke` | Invoke tool (agent permission) |
| GET | `/tools/patient-summary` | Convenience summary |
| GET | `/a2a/capabilities` | A2A agents |
| POST | `/a2a/message` | A2A message |
| POST | `/imaging/analyze` | Non-diagnostic imaging |
| POST | `/imaging/compare` | Compare studies |

## Security & audit

| Method | Path | Roles | Notes |
|--------|------|-------|-------|
| POST | `/security/check-permission` | Care team | Agent permission probe |
| POST | `/security/inspect-prompt` | Care team | Prompt safety inspect |
| POST | `/security/break-glass` | Admin | Emergency access declaration |
| GET | `/audit/events` | Admin | Filterable audit export |

## Help

| Method | Path | Notes |
|--------|------|-------|
| GET | `/help/topics` | Help topics |
| POST | `/help/chat` | Desk help (refuses coverage/diagnosis) |

## Error shape

Errors return JSON with `error_code`, `message`, and HTTP status. UI maps RBAC/OIDC/org codes to plain language ([`frontend/src/api.ts`](../frontend/src/api.ts)).

## Related

- [SEQUENCE_FLOWS.md](SEQUENCE_FLOWS.md)
- [SECURITY_DESIGN.md](SECURITY_DESIGN.md)
- [HLD.md](HLD.md)
