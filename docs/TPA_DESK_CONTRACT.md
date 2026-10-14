# India TPA desk — API contract (v1)

Shared contract between the backend and the desk UI for the cashless pre-authorization
workflow. All routes are under `/api/v1`, org- and patient-scoped like existing routes,
and audited. Times are ISO-8601 UTC; the UI renders them in the browser's time zone (IST
on site). Nothing here approves, denies or submits to an insurer: the desk prepares
documents, a senior clinician confirms, staff send through the insurer/TPA portal and
record what happened.

## Real-world flow modelled

1. Admission / planned procedure → **case** opened (`stage=draft`).
2. Desk assembles the **pre-auth request** (IRDAI standard cashless request form fields
   + supporting documents). Readiness = share of required items supported.
3. Senior clinician confirms (`stage=ready_to_send` after acknowledgment).
4. Staff send via portal → record `sent_at` (`stage=sent`). Insurer decision clock
   (IRDAI: 1 hour for pre-auth) starts only when the request is **complete**.
5. Insurer/TPA **query** → `stage=query`; hospital response due (desk default 24 h).
6. Approved amount recorded (`stage=approved`); **enhancement** if costs rise.
7. Discharge: **consistency check** (discharge summary vs pre-auth vs bill), then
   discharge request sent (`stage=discharge_sent`; IRDAI: 3 hours for final approval).
8. `stage=closed`.

## Case fields (added to authorization case)

| field | type | notes |
|---|---|---|
| `payer_type` | `"insurer" \| "tpa" \| "pmjay" \| "cghs" \| "self_pay"` | |
| `insurer_name` | str | e.g. "Star Health" (free text) |
| `tpa_name` | str | e.g. "Medi Assist" (free text, optional) |
| `policy_number` | str | masked in lists (last 4) |
| `admission_type` | `"planned" \| "emergency"` | |
| `admitted_at` | datetime? | |
| `expected_discharge_at` | datetime? | |
| `treating_doctor` | str | |
| `provisional_diagnosis` | str | |
| `icd10_code` | str | optional |
| `proposed_treatment` | str | procedure / line of treatment |
| `estimated_cost_inr` | int? | |
| `approved_amount_inr` | int? | |
| `stage` | `draft, ready_to_send, sent, query, approved, enhancement, discharge_pending, discharge_sent, closed` | |
| `sent_at`, `decision_due_at`, `approved_at`, `discharge_requested_at`, `final_due_at` | datetime? | `decision_due_at = sent_at + 1h`; `final_due_at = discharge_requested_at + 3h` |

## Endpoints

### `GET /desk/worklist?stage=&q=&limit=&offset=`
Sorted by urgency: overdue first, then smallest `minutes_left`, then oldest.
```json
{"items": [{
  "case_id": "PA-000001", "patient_id": "PAT-000001", "patient_name": "…",
  "mrn": "…", "age": 62, "sex": "male",
  "payer_type": "tpa", "insurer_name": "…", "tpa_name": "…", "policy_last4": "1234",
  "proposed_treatment": "…", "estimated_cost_inr": 85000,
  "stage": "query", "stage_label": "TPA query",
  "readiness_percent": 80, "open_items": 1,
  "clock": {"kind": "query_response|insurer_decision|final_approval|prep|none",
            "label": "Reply to TPA query", "due_at": "…", "minutes_left": 312,
            "overdue": false},
  "assigned_to": "…", "updated_at": "…"}],
 "total": 12,
 "counts": {"draft": 3, "ready_to_send": 1, "sent": 2, "query": 2, "approved": 2,
            "enhancement": 0, "discharge_pending": 1, "discharge_sent": 1, "overdue": 1}}
```

### `GET /desk/cases/{case_id}`
Case workspace. **One readiness number** for the whole product (same as worklist and
Reviews): `readiness_percent = supported / required` over the case checklist.
```json
{"case": {…all case fields…, "stage_label": "…", "clock": {…}},
 "patient": {"patient_id": "…", "name": "…", "mrn": "…", "age": 62, "sex": "…"},
 "readiness": {"percent": 80, "required": 10, "supported": 8, "missing": 1,
               "unknown": 1, "not_supported": 0, "label": "1 item missing"},
 "checklist": [{"item_id": "…", "group": "form|clinical|documents",
                "label": "Provisional diagnosis with ICD-10",
                "status": "SUPPORTED|MISSING|UNKNOWN|NOT_SUPPORTED",
                "required": true, "reason": "…", "fix_hint": "…",
                "citations": [{"document_id": "…", "chunk_id": "…",
                               "source": "clinical_note|lab_result|…",
                               "excerpt": "…≤280 chars…", "date": "…"}]}],
 "queries": [{"query_id": "Q-000001", "raised_at": "…", "text": "…",
              "response_due_at": "…", "responded_at": null, "response": ""}],
 "timeline": [{"at": "…", "event": "…", "actor_label": "…"}],
 "review": {"state": "not_started|awaiting_senior|acknowledged|needs_documentation",
            "by_label": "…", "at": "…", "notes": "…"},
 "disclaimer": "…"}
```

### `PATCH /desk/cases/{case_id}`
Update editable case fields above (not stage/clock fields). Returns the workspace.

### `POST /desk/cases` 
Create a case: `{patient_id, policy_id?, payer_type, insurer_name, tpa_name?, policy_number?,
admission_type, admitted_at?, proposed_treatment, provisional_diagnosis?, icd10_code?,
estimated_cost_inr?, treating_doctor?}`. Returns the workspace.

### `POST /desk/cases/{case_id}/stage`
`{"action": "mark_sent|record_query|answer_query|record_approval|request_enhancement|start_discharge|mark_discharge_sent|close", ...}`
- `mark_sent`: requires `review.state == acknowledged` → `stage=sent`, sets clocks.
- `record_query`: `{text, response_due_hours?=24}`.
- `answer_query`: `{query_id, response}`.
- `record_approval`: `{approved_amount_inr}`.
- `request_enhancement`: `{revised_estimate_inr, reason}`.
- `start_discharge`: → `discharge_pending`.
- `mark_discharge_sent`: requires a discharge check with no `blocker` findings, or `{override_reason}`.
Invalid transitions → 409 `STAGE_TRANSITION_INVALID`. Returns the workspace.

### `GET /desk/cases/{case_id}/preauth-form`
IRDAI standard cashless request form — hospital section, pre-filled from case + chart.
```json
{"form_version": "IRDAI cashless request (hospital section) — illustrative field set",
 "sections": [{"title": "Patient & policy", "fields": [
   {"key": "patient_name", "label": "Name of the patient", "value": "…",
    "source": "chart|case|missing", "required": true}]}],
 "missing_required": ["…"],
 "attachments": [{"label": "Investigation reports supporting diagnosis", "status": "SUPPORTED|MISSING", "citations": [...]}]}
```
Sections: Patient & policy; Treating doctor & diagnosis (nature of illness, duration,
provisional diagnosis + ICD-10, proposed line of treatment, investigation/medical
management details, route of drug administration, surgery name + ICD-10 PCS if surgical,
injury/accident: date, police report/MLC, maternity: G/P/L/A, expected delivery date);
Admission (date/time, emergency/planned, expected days, room type); Past history
(chronic illnesses with duration — diabetes, hypertension, heart disease, etc.);
Cost estimate (room, ICU, OT, professional fees, medicines & consumables, investigations,
implants, total). Field list is an illustrative mapping, labelled as such in the UI.

### `GET /desk/cases/{case_id}/discharge-check`
```json
{"status": "ok|warnings|blockers",
 "findings": [{"severity": "blocker|warning|info", "code": "DIAGNOSIS_MISMATCH",
               "message": "Discharge diagnosis differs from pre-auth diagnosis",
               "expected": "…", "found": "…", "citations": [...]}]}
```
Checks: discharge summary present; discharge diagnosis/ICD vs pre-auth; procedure done vs
approved; final bill vs approved amount (+enhancements); length of stay vs expected;
required discharge documents (discharge summary, final bill, investigation reports,
implant invoice/sticker if implant).

### `GET /desk/stats`
`{"overdue": 1, "due_within_60m": 2, "queries_open": 2, "ready_to_send": 1,
  "awaiting_senior": 2, "median_prep_minutes": 34}`

## Checklists (seeded, illustrative)
India TPA checklists for common cases, each with `form`, `clinical`, `documents`
groups: cataract surgery, total knee replacement, laparoscopic appendectomy, LSCS,
coronary angioplasty (PTCA), acute febrile illness (medical management), road traffic
injury (with MLC/police intimation). Labelled "Illustrative — confirm with each
insurer/TPA". Never call them Medicare or US payer policies.

## Display rules for the UI
- One readiness number per case everywhere.
- Money in ₹ with Indian grouping (₹1,25,000).
- Clocks: overdue = danger, <60 min = warning, otherwise neutral; always show the
  absolute due time on hover/secondary text.
- Policy numbers masked except last 4.
- Synthetic Synthea social findings (e.g. "Received higher education", "Full-time
  employment", "(finding)" social items) are not clinical conditions and must not show
  as conditions.

## Backend additions (v1.1 — additive only)

Nothing above was renamed or removed. Extra fields the backend returns / accepts:

- Desk cases are cases with `payer_type` set; `/desk/worklist` lists only those.
  `stage` filter also accepts `overdue`; unknown stage → 422.
- Worklist item: `approved_amount_inr`, `readiness_label`, `open_queries`.
  `counts` also has `closed`.
- Workspace `case`: `policy_id` (checklist), `checklist_title`, `procedure`,
  `policy_last4`, `revised_estimate_inr`, `enhancement_reason`,
  `enhancement_requested_at`, `enhancement_count`, `discharge_override_reason`,
  `closed_at`, `cost_breakdown_inr` (`room`, `icu`, `ot`, `professional_fees`,
  `medicines_consumables`, `investigations`, `implants`), `form_extra` (free-form
  pre-auth fields: `room_type`, `illness_duration`, `nature_of_illness`,
  `route_of_drug_administration`, `surgery_icd10_pcs`, `injury_date`, `injury_cause`,
  `mlc_number`, `police_report`, `alcohol_involved`, `gpla`, `expected_delivery_date`,
  `expected_days`, `investigations`), `assigned_to`, `last_run_id`, `created_at`,
  `updated_at`. Workspace also has `payer_label`.
- `review.run_id`: the review run a senior resumes with
  `POST /authorization/review/{run_id}/resume` (senior-only; acknowledgment there moves
  `draft → ready_to_send`, a fresh pause / send-back moves `ready_to_send → draft`).
- `queries[]`: `raised_by`, `responded_by`.
- `PATCH` / `POST /desk/cases` accept `cost_breakdown_inr` and `form_extra` (merged;
  a `null` value removes a key). `POST /desk/cases` without `policy_id` picks the
  illustrative checklist matching `proposed_treatment`. Returns 201.
- Stage body extras: `raised_by` (record_query). Errors: invalid transition **and**
  `mark_sent` without senior acknowledgment → 409 `STAGE_TRANSITION_INVALID`;
  `mark_discharge_sent` with blocker findings and no `override_reason` → 409
  `DISCHARGE_CHECK_BLOCKED`; missing action fields → 422 `VALIDATION_ERROR`.
  After the last open query is answered the case returns to the stage it was in
  (`sent` / `enhancement` / `discharge_sent`) and that insurer clock restarts.
- Clocks: `prep` for `draft`/`ready_to_send` = prep start + `PACKET_SLA_MINUTES`;
  `discharge_pending` uses `prep` with `expected_discharge_at`.
- Pre-auth form: `case_id`, `disclaimer`; attachments carry `required`.
- Stats: `total_cases`.

## Backend additions (v1.2 — additive only)

- Pre-auth form field: `warning` (string or `null`) flags a value whose supporting
  document is missing — e.g. `cost_implants` without an implant quotation/invoice on
  file ("Supporting document missing: Implant quotation (make, model, MRP)"). `hint`
  (string or `null`) is reviewer guidance; chart-derived `investigations` carry
  `"Confirm before printing"`.
- Pre-auth form: `checklist_open` — required clinical/document checklist items that are
  not yet supported (`[{item_id, label, group, status}]`). The UI banner reflects both
  `missing_required` (form fields) and `checklist_open`.
- `investigations` (when not set in `form_extra`) lists only chart entries relevant to the
  case: documents/labs cited by the case checklist, or entries mentioning the case's
  diagnosis/procedure keywords. Synthea metadata placeholders are excluded; at most 5
  entries, each ≤160 characters cut on a word boundary, joined with `"; "`.
- Citation excerpts (checklist, attachments, discharge check) are cut on a word boundary
  and end with `…` when shortened (still ≤280 characters). Checklist citation `source`
  is the cited document's `document_type` (e.g. `radiology_report`).
- Documents-group criteria may set `rule.document_types` (substring match on
  `document_type`). Only documents of an accepted type satisfy the item: a mention in a
  clinical note is not an X-ray report. A supported item whose citations are all from
  other types becomes `MISSING` unless an accepted document is on file. Seeded imaging
  reports use `radiology_report`.
- `POST /documents` also accepts patient document types `radiology_report`,
  `investigation_report`, `implant_quote`, `implant_invoice`, `anc_card`, `mlc_copy`,
  `discharge_summary`, `final_bill` (`patient_id` required).
- SUPPORTED checklist rows drop the evaluator's boilerplate reason (the pill already
  says it); informative reasons are kept.
- Wording: the senior action is "Confirm" everywhere in labels and timeline events
  ("Senior confirmed checklist"). API values (`acknowledged`) are unchanged.
