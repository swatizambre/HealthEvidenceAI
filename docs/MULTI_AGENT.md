# Multi-agent AI upgrades

Competitor-inspired enhancements adapted into HealthEvidence’s **decision-support** stance (never approve/deny).

## What we adapted

| Competitor pattern | Our implementation | Safe boundary |
|--------------------|--------------------|---------------|
| Touchless PA + checkpoints | Critic + Pathway before HITL | Human still owns acknowledgment |
| Guided “optimal path” | `PathwayAgent` documentation pathway | Docs readiness only |
| Denial-trigger avoidance | `readiness_scorecard` blockers | Framed as **handoff** risk, not coverage |
| Cycle / desk benchmarks | Pace note vs ops median (when available) | Ops metric, not clinical KPI |
| Stronger retrieval | Multi-query RAG expansion | Still citation-grounded |

## Agent fleet (LangGraph)

```text
load_case → load_policy → retrieve_evidence → imaging_a2a
  → evaluate_criteria → verify_evidence → check_contradictions
  → critic_reflect → build_pathway → human_review → generate_report
```

New agents:

- **CriticAgent** — confidence calibration; rejects uncited “SUPPORTED”
- **PathwayAgent** — ordered next documentation steps + readiness scorecard

## Advanced techniques

1. **Multi-query retrieval** (`query_rewrite.expand_retrieval_queries`) into hybrid RAG  
2. **Self-reflection / critic pass** after contradiction checks  
3. **Confidence calibration** on each criterion  
4. **Pathway planning** (labs/diagnoses-first triage)  
5. **Handoff scorecard** composite (gaps + conflicts + weak citations)

## API surface

`POST /authorization/prepare` and `POST /authorization/review` responses now include:

- `critic_summary` / `critic_notes`
- `documentation_pathway` / `pathway_summary`
- `readiness_scorecard`
- per-criterion `confidence`

## UI

Patient chart packet panel shows handoff scorecard + guided pathway steps.

## Related

- [LLD.md](LLD.md) · [HLD.md](HLD.md) · [SEQUENCE_FLOWS.md](SEQUENCE_FLOWS.md)
