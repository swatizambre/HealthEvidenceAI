# Low-level design (LLD)

Module-level design matching the current codebase under `app/` and `frontend/`.

## 1. Package map

| Path | Role |
|------|------|
| `app/main.py` | App factory: engine, seed, CORS, `AuthMiddleware`, routers |
| `app/core/` | Settings, exceptions, safety / decision-support guards |
| `app/api/routes/` | HTTP handlers by domain |
| `app/api/deps.py` | DB session, role deps, patient access helpers |
| `app/auth/` | OIDC/JWT principal, RBAC, patient scope |
| `app/agents/` | LangGraph graph, nodes, review entry, run persistence |
| `app/mcp/` | Tool implementations + optional stdio FastMCP server |
| `app/a2a/` | Agent-to-agent messaging bus (imaging) |
| `app/services/` | Domain logic (records, packet_prep, opd_ingest, rag, …) |
| `app/db/` | Engine, session, repository queries |
| `app/models/` | SQLAlchemy entities |
| `app/schemas/` | Pydantic API models |
| `frontend/src/` | React pages, role context, API client |

## 2. Request path

```text
HTTP → AuthMiddleware (Bearer → AuthPrincipal on request.state)
     → route Depends(require_any_role / require_care_team)
     → enforce_patient_access / enforce_patient_write (when chart-scoped)
     → service / agent
     → Session commit via get_db
```

Public (middleware) paths include `/health`, `/ready`, `/docs`, `/api/v1/auth/dev-token`, `/api/v1/auth/oidc/status`. Route handlers still apply RBAC where declared.

## 3. LangGraph authorization review

**Entry:** `app/agents/review.py` → `build_review_graph` (`app/agents/graph.py`).

**State:** `ReviewState` (`app/agents/state.py`); durable pause in `ReviewRun.state_json`.

**Node pipeline:**

| Node | Agent intent | Technique |
|------|--------------|-----------|
| `load_case` | Orchestrator | Case bind |
| `load_policy` | PolicyAgent | MCP policy tools |
| `retrieve_evidence` | ClinicalEvidenceAgent | Multi-query hybrid RAG |
| `imaging_a2a_consult` | ImagingAgent | A2A → MONAI |
| `evaluate_criteria` | Clinical scoring | Grounded evaluator |
| `verify_evidence` | EvidenceVerificationAgent | Citation checks |
| `check_contradictions` | EvidenceVerificationAgent | Conflict detect |
| `critic_reflect` | CriticAgent | Confidence + reject weak support |
| `build_pathway` | PathwayAgent | Guided docs path + handoff scorecard |
| `human_review` | AuthorizationAgent | HITL pause |
| `generate_report` | AuthorizationAgent | LLM report |

See [MULTI_AGENT.md](MULTI_AGENT.md).

**Packet prepare** (`app/services/packet_prep.py`) ensures/creates `AuthorizationCase`, stamps cycle-time, invokes the same review path with `auto_complete_human_review=False` (never auto-acks clinician HITL).

## 4. MCP tools

Implemented in `app/mcp/tools.py`; invoked in-process by `HealthcareMCPClient` or via stdio (`python -m app.mcp.server`).

| Tool | Purpose |
|------|---------|
| `get_patient_record` | Patient demographics / summary |
| `get_patient_timeline` | Chronological events |
| `get_policy` | Policy header |
| `get_policy_criteria` | Checklist criteria |
| `search_clinical_evidence` | Hybrid RAG search |
| `get_evidence_chunk` | Chunk by id |
| `create_human_review` | HITL marker |

HTTP mirror: `GET/POST /api/v1/tools/*`.

Permissions: `app/services/permissions.py` (`AGENT_PERMISSIONS` × permission codes).

## 5. A2A imaging

`app/a2a/` registers agents; imaging handler runs non-diagnostic analysis. Enabled when `A2A_ENABLED=true` and `IMAGING_BACKEND` is `monai` / `monai-isolated`.

## 6. Domain services (selected)

| Service | File | Notes |
|---------|------|-------|
| Records / worklist / stats | `services/records.py` | Org-filterable lists |
| Packet prep | `services/packet_prep.py` | Gaps, handoff, cycle time |
| OPD ingest | `services/opd_ingest.py` | Synthetic/consent gates; sets `org_id` |
| FHIR map | `services/fhir_opd.py` | Bundle → OPD request |
| Lifelong | `services/lifelong.py` | Summary for chart / my record |
| RAG | `services/rag/` | Dense + lexical + RRF |
| Org scope | `services/org_scope.py` | `ENFORCE_ORG_SCOPE` |
| Cycle time | `services/cycle_time.py` | Ops metrics |
| Insights | `services/insights.py` | Today desk cards |
| Audit | `services/audit.py` | Append-only events |

## 7. Frontend structure

| Area | Notes |
|------|-------|
| `roleContext.tsx` | Desk role + facility; mints `org_code` for care team |
| `api.ts` | Dev-token mint, friendly error mapping |
| Pages | Today, Patients, PatientDetail, Authorization (Reviews), MyRecord, OpdIngest, Help |

Full screen / IA doc: [WEB_UI.md](WEB_UI.md).

## 8. Criteria evaluation modes

`CRITERIA_EVAL_MODE` (settings): AI-primary with rules fallback paths. Labels exposed to UI via scoring helpers — never raw enum noise on clinician surfaces.

## 9. Related

- [SEQUENCE_FLOWS.md](SEQUENCE_FLOWS.md)
- [API_OVERVIEW.md](API_OVERVIEW.md)
- [DATA_MODEL.md](DATA_MODEL.md)
- Source of truth for entities: `app/models/entities.py`
