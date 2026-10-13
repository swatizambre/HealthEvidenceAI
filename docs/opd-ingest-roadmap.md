# OPD patient-wise ingest roadmap

Planning aid only. **Not for clinical use.** Real OPD data requires privacy, consent, and accountable clinical programs (see [clinical-product-roadmap.md](clinical-product-roadmap.md)).

Today the app seeds a bulk Synthea sample. This roadmap moves toward **one patient at a time during an outpatient visit**.

## Goal

At OPD check-in or during the encounter, staff (or an EHR feed) supplies **one patient’s** packet → HealthEvidence indexes it → Authorization Review runs against that patient only.

```text
OPD desk / EHR
    → Patient packet (notes, labs, meds, procedure request)
    → Ingest API (patient-scoped)
    → Evidence store + RAG chunks
    → Authorization Review for that patient
    → Human reviewer reads citations
```

## What “patient-wise” means

| Rule | Detail |
|------|--------|
| Scope | One `patient_id` (or MRN mapping) per ingest request |
| Packet | Encounter note, active meds, recent labs, ordered procedure, optional imaging metadata |
| Isolation | Documents and chunks belong only to that patient |
| Audit | Who ingested, when, source system, consent flag |
| No bulk mix | Do not merge unrelated patients in one upload |

## Phased roadmap

### Phase 0 — Current (done)

- Bulk Synthea seed (`python -m app.cli.seed`)
- Review by seeded case (`PA-00xxxx`)
- Synthetic only; no live OPD intake

### Phase 1 — Manual OPD packet (prototype) — **API live**

**Ingest:** `POST /api/v1/opd/ingest` (implemented)

**Body (simple):**

- `external_patient_id`, `encounter_id`, optional `encounter_at`
- `note` (visit / OPD note text)
- `labs[]` (test name, value, unit, collected_at)
- `medications[]` (name, status)
- `procedure` (requested service)
- optional `policy_id` → creates authorization case
- optional `patient_id` to attach to an existing `PAT-xxxxxx`
- `source` (`opd_manual` | `opd_export`)
- `synthetic` (must be `true` in Phase 1) and `consent_attested` (must be `true`)

**Outcomes:**

- Create or reuse one patient (by `patient_id` or prior `external_patient_id`)
- Store note/lab documents + chunks for that patient only
- Idempotent on `encounter_id` (replay returns `created: false`)
- Optional authorization case for procedure + policy
- Audit event `opd_ingest`

**Still not clinical:** synthetic packets only until Phase 3 gates clear. UI workflow is Phase 2.


### Phase 2 — OPD workflow in the UI — **done (basic)**

1. Open **OPD ingest** in the UI
2. Paste today’s note + optional labs/meds
3. Select procedure + policy checklist
4. Ingest → index → continue to Authorization Review
5. Review statuses and citations for that patient/case

### Phase 3 — EHR / FHIR (controlled environments only)

- Subscribe to FHIR `Patient`, `Encounter`, `DocumentReference` / `DiagnosticReport`, `MedicationRequest`, `ServiceRequest`
- Map encounter → patient-wise ingest job
- OIDC + RBAC; PHI residency; retention and delete-on-request
- Change-controlled mapping; no silent overwrites of clinician-authored notes

Do not start Phase 3 without the items in [clinical-product-roadmap.md](clinical-product-roadmap.md).

## Change control (P2.6 — before any live EHR feed)

Repo gates already enforce synthetic/consent packets unless `ALLOW_PHI` + `PHI_PROGRAM_ATTESTED`. Operators still need an org change-control record before wiring FHIR:

| Gate | Owner | Done when |
|------|-------|-----------|
| Feed inventory | Integration | Source systems, resources, and refresh cadence listed |
| Mapping signed | Clinical informatics | Encounter → document → chart field map reviewed |
| No silent overwrite | Engineering | Clinician-authored notes never replaced without versioning |
| RBAC + org scope | Security | Care-team tokens scoped; audit on ingest |
| PHI attestation | Compliance | `ALLOW_PHI` / `PHI_PROGRAM_ATTESTED` only after program sign-off |
| Rollback | Ops | Disable feed flag + last-good restore drill documented |
| Pilot proof | QA | Idempotent re-ingest + patient isolation tests green on staging Postgres |

Until those are signed, keep `POST /api/v1/opd/ingest` on **synthetic** packets only.

## Suggested first API shape (Phase 1) — live

```http
POST /api/v1/opd/ingest
Content-Type: application/json

{
  "external_patient_id": "OPD-12345",
  "encounter_id": "ENC-2026-09-28-01",
  "note": "OPD visit note text...",
  "labs": [{"test_name": "...", "value": "...", "unit": "..."}],
  "medications": [{"name": "...", "status": "active"}],
  "procedure": "Medication reconciliation (procedure)",
  "policy_id": "POL-000001",
  "consent_attested": true,
  "synthetic": true
}
```

**Response:** `ingest_id`, `patient_id`, `document_ids[]`, `case_id`, `created` → then existing `POST /api/v1/authorization/review`.

## Success checks

- Ingesting patient A never surfaces patient B’s documents in review or search
- Every SUPPORTED criterion still cites a real chunk from that ingest
- Re-ingest same `encounter_id` is idempotent (update or version, not duplicate noise)
- Audit log records actor, patient, encounter, source

## Out of scope for this roadmap

- Approving or denying care
- Diagnosis or prescribing
- Unattended bulk scrapes of production EHRs
- Training models on OPD PHI without a separate data-governance program
