# Criterion-level gold set

This is the **clinical-safety evaluation gate**. Until a dual-clinician reconciled set exists, CI runs an **engineering seed** (`criteria_cases.v1.json`, `status: engineering_seed`, 98 cases).

Seed labels are what a careful clinician would conclude from the fixture text, **not** what the code currently outputs. When the code disagrees with a label, fix the code (or argue the label in review), never the label alone.

## Metrics (release gate)

| Metric | Meaning | Rules-path gate |
|--------|---------|-----------------|
| **false-SUPPORTED rate** | Predicted `SUPPORTED` ÷ cases whose gold is **not** `SUPPORTED` (the cases where a false claim is possible). `false_supported_count` is reported alongside. | `≤ 0.0` on seed |
| **SUPPORTED recall** | Gold `SUPPORTED` also predicted `SUPPORTED` (guards against "safe" over-negation) | `≥ 0.9` |
| **MISSING recall** | Gold `MISSING` also predicted `MISSING` | `≥ 0.85` |
| **Citation presence** | Predicted `SUPPORTED` rows that carry ≥1 citation. Presence only: it does **not** check that the cited text supports the claim. That is the job of the citation verifier in the agent path (`app/services/citation_check.py`, lexical today, entailment later). Formerly named `citation_precision`; `--min-citation-precision` is still accepted as an alias. | `≥ 0.95` |
| **Latency p50 / p95** | Per-criterion eval time | p95 ≤ 500 ms (seed) |
| **Confusion counts** | `confusion_expected_by_predicted[gold][predicted]` plus `gold_counts`, printed with every run | reported, not gated |

Every case must also match exactly (status and `min_citations`); any case failure fails the gate.

Run paths separately (`--path rules` today; `--path ai_clinical:ollama` later).

```bash
uv run python -m evaluation.run_gold
uv run python -m evaluation.run_gold --path rules --min-supported-recall 0.9
make eval-gold
```

## What the seed covers

| Area | Examples |
|------|----------|
| Negation | `denies`, `negative for`, `no history of`, `diabetes: none`, lists (`Denies fever, chills, or diabetes`) |
| Hedging | `possible`, `likely`, `unlikely`, `doubtful`, `not confirmed`, `to be ruled out`, `?diabetes`, `Diabetes (?)` |
| Experiencer | `Mother has diabetes.`, `FHx: diabetes (father).`, `Diabetes in mother`, `h/o diabetes in family` |
| No over-negation | `Type 2 diabetes, no complications.`, `Diabetes. No history of hypertension.`, `Mother reports patient has diabetes.` |
| Word boundaries | `Prediabetes` is not `diabetes`; `minimal` is not `MI` |
| NOT_SUPPORTED | Opposing phrase via `negation_any` (PT not attempted, current smoker, no conservative therapy); lab below threshold |
| UNKNOWN | Contradictions, `statement_clarity` uncertainty, unsupported rule type, lab without comparator |
| Labs | `%` ↔ `mmol/mol` (incl. the 53 mmol/mol = 7.0 % boundary), missing or incompatible unit, censored `<7.5`, pending / hemolyzed, stale or undated with `max_age_days`, latest result wins, presence-only |

Lab fixtures may set `collected_days_ago` so recency cases stay stable over time.

## Path to clinician gold (≥200 judgements / ≥50 charts)

1. Sample charts across specialties and payers used in the pilot desk.
2. Two clinicians independently label each criterion: `SUPPORTED` / `NOT_SUPPORTED` / `MISSING` / `UNKNOWN`, plus the supporting span (offsets).
3. Reconcile disagreements; store `annotators`, `agreement: reconciled`.
4. Bump `status` to `clinician_gold` and raise `--min-cases` / keep false-SUPPORTED at 0 for release.

## Schema (per case)

- `id`, `path`, `tags`
- `notes[]`, `labs[]` — fixture chart fragments (or later: `patient_id` + snapshot id). Lab fields: `test_name`, `content`, `value`, `unit`, optional `collected_days_ago`.
- `criterion` — code, description, rule object
- `expected_status`, `min_citations`
- optional `active: false` to park a case without deleting it
