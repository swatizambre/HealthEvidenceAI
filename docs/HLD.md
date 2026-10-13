# High-level design (HLD)

Version aligned with application **0.3.x**. Describes the system as implemented in this repository.

## 1. Purpose

HealthEvidence AI helps care teams **assemble prior-authorization evidence packets** and maintain a **lifelong chart** across facilities. Clinicians and staff confirm documentation readiness; the system never approves, denies, diagnoses, or submits payer decisions.

Primary users:

| Persona | Job |
|---------|-----|
| Records / PA staff | Prepare packets, close documentation gaps, hand off |
| Resident | Prep + check evidence; escalate HITL |
| Senior clinician | Acknowledge or send back HITL reviews |
| Patient | View/update own lifelong record (linked `patient_id`) |
| Facility admin | Audit export, break-glass, org-wide access |

## 2. System context

```text
┌──────────────┐     JWT / OIDC      ┌─────────────────┐
│  React UI    │ ───────────────────► │  FastAPI API    │
│  (Vite)      │◄── /api/v1 + /docs ──│  app.main       │
└──────────────┘                      └────────┬────────┘
                                               │
         ┌─────────────────────────────────────┼──────────────────────────┐
         ▼                     ▼               ▼                          ▼
   ┌───────────┐        ┌───────────┐   ┌────────────┐            ┌────────────┐
   │ LangGraph │        │ MCP tools │   │ Hybrid RAG │            │ A2A bus    │
   │ review    │───────►│ + perms   │──►│ + records  │            │ imaging    │
   └─────┬─────┘        └───────────┘   └─────┬──────┘            └─────┬──────┘
         │                                    │                         │
         ▼                                    ▼                         ▼
   ┌───────────┐                        ┌──────────┐              ┌──────────┐
   │ LLM       │                        │ Postgres │              │ MONAI    │
   │ providers │                        │ / SQLite │              │ analyzer │
   └───────────┘                        └──────────┘              └──────────┘
         ▲
         │ optional
   ┌───────────┐
   │ OIDC IdP  │  (Keycloak / Entra / Auth0)
   └───────────┘
```

Canonical diagram source: [architecture.mmd](architecture.mmd).

## 3. Logical components

| Component | Responsibility |
|-----------|----------------|
| **React UI** | Desk roles, Today worklist, chart, Reviews, visit notes, OPD ingest |
| **FastAPI** | REST `/api/v1`, auth middleware, OpenAPI |
| **Auth** | `dev-jwt` or `oidc`; product RBAC; patient + org scope |
| **LangGraph orchestrator** | Authorization review state machine + HITL pause/resume |
| **MCP layer** | Permission-gated tools for agents (patient, policy, evidence, HITL) |
| **Domain services** | Packet prep, OPD ingest, lifelong summary, evaluator, audit |
| **Hybrid RAG** | Dense + lexical + RRF retrieval over document chunks |
| **A2A imaging** | Isolated imaging consult (non-diagnostic) |
| **Persistence** | SQLAlchemy entities; seed / Synthea catalog |

## 4. Trust boundaries

1. **Browser ↔ API** — Bearer JWT; CORS allow-list; no secrets in frontend.
2. **API ↔ IdP** — JWKS validation when `AUTH_MODE=oidc`.
3. **Agents ↔ data** — Agents use MCP tools; permissions enforced per agent name.
4. **Imaging** — MONAI path is decision-support only; not a diagnostic claim.
5. **PHI** — Default synthetic/consent-gated; live PHI requires `ALLOW_PHI` + attestation.

## 5. Environments (summary)

| Environment | Auth | Database |
|-------------|------|----------|
| local / docker | `dev-jwt` typical | SQLite or Postgres |
| pilot | `dev-jwt` or `oidc` | Postgres required |
| staging / production | `oidc` required | Postgres required |
| test | may use `none` | in-memory SQLite |

Details: [DEPLOYMENT.md](DEPLOYMENT.md), [operations.md](operations.md).

## 6. Cross-cutting concerns

| Concern | Approach |
|---------|----------|
| Authorization | JWT roles + patient self-scope + optional `ENFORCE_ORG_SCOPE` |
| Audit | `AuditEvent` rows; admin export; break-glass logged |
| Safety copy | Disclaimers; prompt/output guard against approve/deny/diagnose language |
| Observability | In-process spans; optional Langfuse env hooks |
| Multi-org | `Organization` + patient/case `org_id`; IdP org claims |

## 7. Non-goals (explicit)

- Not a medical device; not for clinical diagnosis or prescribing
- Not a payer adjudication / PAS submit engine
- Not an EHR system of record (ingests visit packets; does not replace HIS)
- Not unsupervised bulk PHI scraping without change control

## 8. Related design docs

- [LLD.md](LLD.md) — module and agent detail
- [WEB_UI.md](WEB_UI.md) — React desk IA and screens
- [SEQUENCE_FLOWS.md](SEQUENCE_FLOWS.md) — runtime flows
- [SECURITY_DESIGN.md](SECURITY_DESIGN.md) — authz design
- [API_OVERVIEW.md](API_OVERVIEW.md) — HTTP surface
- [DATA_MODEL.md](DATA_MODEL.md) — persistence
- [PILOT_ROADMAP.md](PILOT_ROADMAP.md) — delivery status
