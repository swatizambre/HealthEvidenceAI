# Criterion-level gold set

This is the **clinical-safety evaluation gate**. Until a dual-clinician reconciled set exists, CI runs an **engineering seed** (`criteria_cases.v1.json`, `status: engineering_seed`).

## Metrics (release gate)

| Metric | Meaning | Rules-path gate |
|--------|---------|-----------------|
| **false-SUPPORTED rate** | Predicted `SUPPORTED` when gold is not | `≤ 0.0` on seed |
| **MISSING recall** | Gold `MISSING` also predicted `MISSING` | `≥ 0.85` |
| **Citation precision** | Predicted `SUPPORTED` rows that have ≥1 citation | `≥ 0.95` |
| **Latency p50 / p95** | Per-criterion eval time | p95 ≤ 500 ms (seed) |

Run paths separately (`--path rules` today; `--path ai_clinical:ollama` later).

```bash
uv run python -m evaluation.run_gold
make eval-gold
```

## Path to clinician gold (≥200 judgements / ≥50 charts)

1. Sample charts across specialties and payers used in the pilot desk.
2. Two clinicians independently label each criterion: `SUPPORTED` / `NOT_SUPPORTED` / `MISSING` / `UNKNOWN`, plus the supporting span (offsets).
3. Reconcile disagreements; store `annotators`, `agreement: reconciled`.
4. Bump `status` to `clinician_gold` and raise `--min-cases` / keep false-SUPPORTED at 0 for release.

## Schema (per case)

- `id`, `path`, `tags`
- `notes[]`, `labs[]` — fixture chart fragments (or later: `patient_id` + snapshot id)
- `criterion` — code, description, rule object
- `expected_status`, `min_citations`
- optional `active: false` to park a case without deleting it
