# AI scope in HealthEvidence

HealthEvidence is **hybrid decision-support for prior-auth paperwork**, not clinical AI and not fully AI-driven care.

In the default setup (`LLM_PROVIDER=local`), checklist scoring is **almost entirely rule-based**: keyword/lab matching, negation, and unit rules. The “local” provider does **not** run a model — it relabels rule results and echoes chart text. Real models (Ollama, OpenAI, Anthropic, Gemini) only run when you configure them; cloud models are blocked when real PHI is on without BAA/egress attestation.

## What actually runs

| Capability | Default (local) | Optional real AI |
|------------|-----------------|------------------|
| Criteria scoring | Deterministic rules → labeled **Rule check** (`rule_check:local` / `rules`) | LLM status + chart excerpt → **AI check** (`ai_clinical:ollama|gemini|…`) |
| Hybrid RAG | Word hashing + lexical overlap | Dense embeddings when configured |
| Report phrasing | Grounded template over rule outcomes | `complete_report` from a model |
| Gap drafts | Template + chart cue (`ai:local` = rule-assisted wording) | LLM coaching when a real provider is on |
| Critic / pathway | Fixed confidence bands + ordered next-doc steps | Same deterministic scorecard |
| Imaging assist | Non-diagnostic stub / random features unless MONAI is wired | Skip when unavailable |
| Help phrasing | Static FAQ | LLM rephrase from fixed contexts |

Desk and packet copy must say **rule check** vs **AI check** accordingly. Do not call rule output “AI”.

## Where AI must not decide

- Approve / deny coverage or prior auth
- Diagnose, prescribe, or recommend treatment
- Submit payer PAS / claims
- Replace senior HITL acknowledgment
- Autonomously “decide” hospital feeds (HIS/FHIR = ingest + optional prepare)

## Config

```bash
CRITERIA_EVAL_MODE=ai_primary   # or rules — with LLM_PROVIDER=local this is still rule check
AI_GAP_DRAFTS=true              # unset follows criteria mode
LLM_PROVIDER=ollama|openai|anthropic|gemini|local
LLM_FALLBACK_PROVIDERS=local
```

## APIs

- `GET /api/v1/ai/scope` — public scope map
- `POST /api/v1/ai/gap-draft` — on-demand coaching draft (care-team)
- `GET /api/v1/auth/capabilities` → `ai` object
- Prepare / hospital status responses include `ai_assist` / `ai` and `scoring_path`

## Product rule

Rules organize evidence predictably; optional AI may assist wording or status when a real model is configured. Humans own the final review. This is not a clinical device.
