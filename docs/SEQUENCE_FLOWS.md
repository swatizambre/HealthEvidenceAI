# Sequence flows

Runtime sequences as implemented. Mermaid diagrams are illustrative; OpenAPI and code are authoritative.

## 1. Packet prepare (staff / resident / senior)

```mermaid
sequenceDiagram
  participant UI as React UI
  participant API as FastAPI
  participant Auth as Auth + RBAC
  participant Prep as packet_prep
  participant Graph as LangGraph review
  participant MCP as MCP tools
  participant DB as Database

  UI->>API: POST /authorization/prepare
  API->>Auth: require ROLES_PACKET_PREP
  API->>Auth: enforce_patient_access (+ org if enforced)
  API->>Prep: prepare_evidence_packet
  Prep->>DB: ensure AuthorizationCase + stamp prep_started
  Prep->>Graph: review_authorization (no auto HITL ack)
  Graph->>MCP: patient / policy / search tools
  MCP->>DB: scoped reads
  Graph-->>Prep: criteria + gaps
  Prep-->>API: PacketPrepareResponse
  API-->>UI: readiness %, next actions, handoff
```

## 2. Interactive review + HITL resume

```mermaid
sequenceDiagram
  participant Senior as Senior clinician
  participant API as FastAPI
  participant Graph as LangGraph
  participant Runs as ReviewRun store

  Senior->>API: POST /authorization/review (interactive=true)
  API->>API: enforce_patient_access
  API->>Graph: run until human_review pause
  Graph->>Runs: save_run(state)
  API-->>Senior: awaiting_human_review + run_id

  Senior->>API: POST /authorization/review/{run_id}/resume
  Note over API: ROLES_HITL only (senior/admin)
  API->>Runs: load_run → patient_id
  API->>API: enforce_patient_access
  API->>Graph: human_review_gate → generate_report
  API-->>Senior: final draft (not an approval)
```

Staff/resident resume → `403` (RBAC).

## 3. Evidence search

```mermaid
sequenceDiagram
  participant Client
  participant API
  participant RAG as Hybrid RAG
  participant DB

  Client->>API: POST /evidence/search
  API->>API: care-team / chart scope as required
  API->>RAG: dense + lexical + RRF (+ filters)
  RAG->>DB: DocumentChunk embeddings
  API-->>Client: citations with chunk / document refs
```

## 4. OPD / visit note ingest

```mermaid
sequenceDiagram
  participant UI
  participant API
  participant Scope as patient + org scope
  participant Ingest as opd_ingest
  participant DB

  UI->>API: POST /opd/ingest (synthetic + consent)
  API->>Scope: enforce_patient_write
  API->>Ingest: ingest_opd_packet(org_id from token)
  Ingest->>DB: Patient (org_id), Documents, chunks, optional Case
  Ingest->>DB: AuditEvent opd_ingest
  API-->>UI: patient_id, document_ids, case_id
```

FHIR path: `POST /opd/ingest/fhir` → map bundle → same ingest.

## 5. Patient self-scope

```mermaid
sequenceDiagram
  participant Patient
  participant API
  participant Scope

  Patient->>API: GET /patients/PAT-000002 (token linked to PAT-000001)
  API->>Scope: ensure_patient_record_access
  Scope-->>API: PATIENT_SCOPE_FORBIDDEN
  API-->>Patient: 403
```

## 6. Org scope (when ENFORCE_ORG_SCOPE=true)

Care-team tokens must carry `org_id` or `org_code`. List/worklist/stats/ops/cases filter by patient org; chart open and writes call `ensure_org_patient_access`. Admin bypasses.

## 7. MCP tool invoke (HTTP)

```mermaid
sequenceDiagram
  participant Client
  participant API as /tools/invoke
  participant Perm as permissions
  participant Tools as mcp.tools
  participant DB

  Client->>API: POST tool + args + agent name
  API->>Perm: require_permission(agent, permission)
  Perm-->>API: allow / deny
  API->>Tools: execute
  Tools->>DB: read/write allowed surface
  API-->>Client: tool result
```

## 8. Break-glass (admin)

```text
POST /security/break-glass { patient_id, reason }
  → require admin
  → AuditEvent action=break_glass (no clinical note body)
  → exportable via GET /audit/events
```

## Related

- [LLD.md](LLD.md) — node and service names
- [SECURITY_DESIGN.md](SECURITY_DESIGN.md) — role matrices
- [API_OVERVIEW.md](API_OVERVIEW.md) — path catalog
