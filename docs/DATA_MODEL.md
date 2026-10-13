# Data model

Persistence is SQLAlchemy (`app/models/entities.py`). Same models run on **SQLite** (local/test) and **PostgreSQL** (Docker, pilot, staging, production).

Short legacy stub: [schema.md](schema.md) (points here).

## 1. Entity overview

```text
Organization 1──* Patient
Organization 1──* AuthorizationCase
Patient 1──* Document 1──* DocumentChunk
Patient 1──* ClinicalNote | LabResult | Medication | Procedure | ImagingStudy | Claim
InsurancePolicy 1──* PolicyCriterion
Patient + InsurancePolicy ──* AuthorizationCase
ReviewRun (run_id PK, state_json)     # HITL pause/resume
AuditEvent                            # append-only
```

## 2. Public codes

| Prefix | Entity | Example |
|--------|--------|---------|
| `ORG-` | Organization.org_code | `ORG-000001` |
| `PAT-` | Patient.patient_code | `PAT-000001` |
| `POL-` | InsurancePolicy.policy_code | `POL-000001` |
| `PA-` | AuthorizationCase.case_code | `PA-000001` |
| `DOC-` | Document.document_code | `DOC-000001` |

Internal primary keys are UUIDs (`IdentityMixin`).

## 3. Core tables

### Organization

Tenant / facility stub: `org_code`, `name`, `facility_type`, `active`.

### Patient

Demographics (`synthetic_name`, `birth_date`, `sex`, `conditions` JSON) + optional `org_id`.  
Seed and OPD ingest assign org (default `DEFAULT_ORG_CODE`).

### Document / DocumentChunk

Chart text store. Chunks hold hybrid embedding JSON (`sparse`, `dense`, `model`). Metadata may include specialty, encounter, case linkage.

### Clinical facts

`ClinicalNote`, `LabResult`, `Medication`, `Procedure`, `ImagingStudy`, `Claim` — structured companions to documents for lifelong / timeline views.

### InsurancePolicy / PolicyCriterion

Payer checklist: policy header + ordered criteria used by the review graph.

### AuthorizationCase

Lifecycle for documentation readiness (not coverage decision):

| Field | Role |
|-------|------|
| `status` | e.g. `queued`, `needs_documentation`, `ready_for_human`, `closed_as_draft` |
| `procedure` | Requested service label |
| `last_run_id` | Latest review run |
| `lifecycle_note` | Short gap / coaching text |
| `prep_started_at` / `review_ready_at` | Packet cycle-time |
| `org_id` | Tenant (usually mirrors patient org) |

### ReviewRun

`run_id` + `state_json` for LangGraph HITL pause/resume.

### AuditEvent

`action`, `actor`, `resource_type`, `resource_id`, `status`, `detail` — no clinical note bodies in security/break-glass exports.

## 4. Embeddings

Controlled by `EMBEDDING_MODEL` / indexing pipeline. Stored on chunks as JSON hybrid payloads for dense + lexical retrieval ([`app/services/rag/`](../app/services/rag/)).

## 5. Soft migrations

SQLite path may `ALTER TABLE` to add `org_id` / cycle-time columns for older files (`app/db/session.py`). Prefer Postgres for pilot+.

## 6. Seeding

`SEED_ON_STARTUP` / `python -m app.cli.seed` loads synthetic catalog (Synthea-style). See [data/synthetic/README.md](../data/synthetic/README.md).

## Related

- [DATA_MODEL.md](DATA_MODEL.md) (this file)
- [LLD.md](LLD.md)
- [SECURITY_DESIGN.md](SECURITY_DESIGN.md) — org and patient scoping rules
