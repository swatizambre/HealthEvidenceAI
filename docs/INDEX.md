# Documentation index

Canonical design and operations docs for HealthEvidence AI.

**Product:** prior-auth evidence prep + lifelong digital health record.  
**Stance:** decision support only — not a medical device; does not diagnose, approve, or deny care.

## Design (HLD / LLD)

| Document | Purpose |
|----------|---------|
| [HLD.md](HLD.md) | High-level design — components, trust boundaries, non-goals |
| [LLD.md](LLD.md) | Low-level design — modules, agents, MCP, permissions |
| [SEQUENCE_FLOWS.md](SEQUENCE_FLOWS.md) | End-to-end sequences (packet, review, OPD, MCP) |
| [API_OVERVIEW.md](API_OVERVIEW.md) | HTTP API catalog (`/api/v1`, health, auth) |
| [DATA_MODEL.md](DATA_MODEL.md) | Persistence entities and codes |
| [SECURITY_DESIGN.md](SECURITY_DESIGN.md) | Auth, RBAC, patient/org scope, audit |
| [DEPLOYMENT.md](DEPLOYMENT.md) | Compose overlays, env gates, Kubernetes |
| [WEB_UI.md](WEB_UI.md) | React desk — routes, roles, screens, client |
| [MULTI_AGENT.md](MULTI_AGENT.md) | Critic/Pathway agents, RAG upgrades, readiness |
| [architecture.mmd](architecture.mmd) | System diagram (Mermaid source) |

## Run / launch

| Document | Purpose |
|----------|---------|
| [GO_LIVE.md](GO_LIVE.md) | Go-live runbooks: synthetic demo + real-data hospital trial |
| [LAUNCH.md](LAUNCH.md) | Demo vs pilot vs staging paths |
| [operations.md](operations.md) | Day-2 ops, locales, imaging, HA/DR stub |
| [kubernetes.md](kubernetes.md) | Cluster apply notes |
| [OIDC_PILOT.md](OIDC_PILOT.md) | IdP wiring for shared pilot |

## Roadmaps / gates

| Document | Purpose |
|----------|---------|
| [PILOT_ROADMAP.md](PILOT_ROADMAP.md) | Phase 1–3 completion status |
| [PRODUCTION_CHECKLIST.md](PRODUCTION_CHECKLIST.md) | Staging/prod operator checklist |
| [clinical-product-roadmap.md](clinical-product-roadmap.md) | Safety boundary and org programs |
| [opd-ingest-roadmap.md](opd-ingest-roadmap.md) | OPD/FHIR change control |
| [data-privacy.md](data-privacy.md) | Patient vs care-team privacy notes |
| [CONSENT_AND_RIGHTS.md](CONSENT_AND_RIGHTS.md) | Consent records, DPDP/HIPAA rights mapping, erasure vs retention |

## Related root files

- [README.md](../README.md) — product overview
- [SECURITY.md](../SECURITY.md) — security reporting stance
- [CONTRIBUTING.md](../CONTRIBUTING.md) — contributor guide
- OpenAPI: `GET /docs` when the API is running
