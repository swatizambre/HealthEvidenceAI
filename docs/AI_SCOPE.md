# AI scope in HealthEvidence

HealthEvidence is **hybrid decision-support**, not fully AI-driven care.

## Where AI is used

| Capability | Role | Fallback |
|------------|------|----------|
| Criteria scoring | LLM over retrieved chart (`CRITERIA_EVAL_MODE=ai_primary`) | Deterministic rules + safety net |
| Hybrid RAG | Dense + lexical retrieval with citations | Lexical search |
| Report phrasing | Grounded `complete_report` | Local grounded phrasing |
| Gap drafts | Short visit-note coaching from chart cues | Template + chart cue |
| Critic / pathway | Confidence + ordered next-doc steps | Deterministic scorecard |
| Imaging assist | MONAI non-diagnostic features | Skip imaging node |
| Help phrasing | Rephrase FAQ from fixed contexts | Static FAQ |

## Where AI must not decide

- Approve / deny coverage or prior auth
- Diagnose, prescribe, or recommend treatment
- Submit payer PAS / claims
- Replace senior HITL acknowledgment
- Autonomously “decide” hospital feeds (HIS/FHIR = ingest + optional prepare)

## Config

```bash
CRITERIA_EVAL_MODE=ai_primary   # or rules
AI_GAP_DRAFTS=true              # unset follows criteria mode
LLM_PROVIDER=ollama|openai|anthropic|gemini|local
LLM_FALLBACK_PROVIDERS=local
```

## APIs

- `GET /api/v1/ai/scope` — public scope map
- `POST /api/v1/ai/gap-draft` — on-demand coaching draft (care-team)
- `GET /api/v1/auth/capabilities` → `ai` object
- Prepare / hospital status responses include `ai_assist` / `ai`

## Product rule

AI organizes evidence and coaches documentation. Humans own the final review.
