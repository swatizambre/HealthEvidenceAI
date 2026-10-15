# Consent records and patient rights

Planning aid. **Not legal advice.** This page maps product controls to the Digital Personal Data Protection Act 2023 (India, "DPDP") and HIPAA (US). The facility's counsel and Data Protection / Grievance Officer must review it before a real-patient pilot.

## Data model

### `consent_records` (`ConsentRecord`, public code `CNS-######`)

| Column | Meaning |
|--------|---------|
| `patient_id` | FK to `patients.id` |
| `org_id` | Facility (Data Fiduciary) the consent was given to. A consent for one facility does not cover another. |
| `purpose` | `prior_auth_evidence`, `continuity_of_care`, or `research_trial` |
| `scope` | Free-text description shown to the patient (data categories, recipients) |
| `method` | `written`, `electronic`, or `verbal_witnessed` |
| `language` | Language the notice was given in (e.g. `hi`, `mr`, `en`) |
| `notice_version` | Version id of the privacy notice the patient saw |
| `granted_by_name` | Patient or lawful representative who gave consent |
| `recorded_by` | Signed-in staff subject who captured it |
| `granted_at` / `expires_at` | Validity window (`expires_at` is optional) |
| `revoked_at` / `revoked_reason` / `revoked_by` | Withdrawal. Rows are **never deleted**. |
| `evidence_ref` | Scanned signed-form document id or e-consent transaction reference |

A consent is **active** when it is not revoked, not expired, and `granted_at <= now`. `app.services.consent.active_consent(session, patient_id, purpose, org_id)` returns the newest active row.

### `data_subject_requests` (`DataSubjectRequest`, public code `DSR-######`)

`request_type` is `correction`, `erasure`, `grievance`, or `nominee`. `status` moves `open` → `in_review` → `resolved` / `rejected`. Other fields: `details`, `resolution_note`, `outcome` (erasure only), `handled_by`, `resolved_at`.

Migration: `alembic/versions/20261013_0003_consent_and_rights.py` (revision `20261013_0003`, revises `20261009_0002`).

## Consent on visit ingest

| Mode | Rule |
|------|------|
| **PHI mode** (`ALLOW_PHI` + `PHI_PROGRAM_ATTESTED`) | `POST /opd/ingest` and `/opd/ingest/fhir` (and the hospital pipeline) need `consent_id`: an **active** consent for this patient, with purpose `prior_auth_evidence` or `continuity_of_care`, from this facility. If this ingest creates the patient, the request can instead carry an inline `consent` object. The server stores it in the same transaction. Otherwise the API returns **403 `CONSENT_REQUIRED`**. |
| **Practice / synthetic** | The `consent_attested` checkbox still works. The server also stores (or reuses) a `ConsentRecord` with `method=electronic` and `notice_version=synthetic-practice`, so the trail exists. |

The ingest response and the note document metadata both carry `consent_id`. The `opd_ingest` audit row records `consent=CNS-…`. `GET /api/v1/auth/capabilities` returns `phi_live` and `consent_mode` (`stored_required` or `attestation`). The Visit note page uses these to show either the consent selector / form or the checkbox.

## Endpoints

| Endpoint | Who | Purpose |
|----------|-----|---------|
| `POST /api/v1/patients/{id}/consents` | staff, resident, senior (admin) | Record a consent |
| `GET /api/v1/patients/{id}/consents` | care team; patient (own record only) | List active and withdrawn consents |
| `POST /api/v1/patients/{id}/consents/{CNS}/revoke` | care team; patient (own record only) | Withdraw a consent |
| `GET /api/v1/me/access-log` | patient | Who accessed my record (paginated, newest first) |
| `GET /api/v1/me/export` | patient | JSON copy of own data |
| `POST /api/v1/me/requests` / `GET /api/v1/me/requests` | patient | Raise and list rights requests |
| `GET /api/v1/privacy/requests` | staff, admin (org-scoped) | Privacy / grievance desk queue |
| `POST /api/v1/privacy/requests/{DSR}/resolve` | staff, admin (org + break-glass gate) | Move a request to `in_review` / `resolved` / `rejected` |

All patient-scoped routes go through `enforce_patient_access`, so the org-scope and break-glass rules apply. Every action is audited (`consent_recorded`, `consent_revoked`, `consent_list`, `access_log_read`, `data_export`, `dsr_created`, `dsr_list`, `dsr_updated`). Audit rows never contain free-text scope or request details.

**Patient-facing views never expose staff personal identifiers.** In the access log, consent list, requests, and export, staff appear as "Care team member · ref xxxxxxxx", a stable SHA-256 prefix of their subject. Patients can quote this reference to the grievance officer, who can resolve it through the admin audit export.

## DPDP Act 2023 mapping

| DPDP | Product control |
|------|-----------------|
| s.5 Notice (itemised, in English or an Eighth-Schedule language) | `notice_version` + `language` stored on each consent. The notice text itself is facility-owned and versioned outside the app. |
| s.6(1) Free, specific, informed, unambiguous consent for a specified purpose | One row per `purpose`. Ingest accepts only purposes that cover storing visit records. `research_trial` never authorises ingest. |
| s.6(4) Withdrawal as easy as giving consent | Patient withdraws from My Record in one step (`/revoke`). Later ingest under that consent fails with `CONSENT_REQUIRED`. |
| s.6(7)-(9) Consent managers | Not integrated. `evidence_ref` can hold a consent-manager artefact id. |
| s.8(7) Erase when purpose is served, *unless retention is required by law* | Erasure is a request workflow. See retention below. |
| s.8(10) / s.13 Grievance redressal | `grievance` requests and the `/privacy/requests` desk |
| s.11 Right to access a summary of processing | `/me/access-log` (who / when / what, allowed or denied) and `/me/export` |
| s.12 Correction, completion, updating, erasure | `correction` / `erasure` requests with a documented resolution |
| s.14 Right to nominate | `nominee` request type (captured, actioned off-system) |

## HIPAA mapping (US pilot)

| HIPAA | Product control |
|-------|-----------------|
| 164.508 Authorization | `ConsentRecord` with method, signer, `evidence_ref` (signed form), and expiry. TPO uses may not need authorization. The facility decides. |
| 164.524 Right of access | `/me/export` (machine-readable copy) |
| 164.526 Right to amend | `correction` request. Resolution must be recorded (accept, or deny with reason). |
| 164.528 Accounting of disclosures | `/me/access-log`. This covers in-system access only, not disclosures made outside the app. |

## Retention caveat: why erasure is not a hard delete

Medical records are subject to statutory retention that overrides a general erasure request:

- **India.** The Indian Medical Council (Professional Conduct, Etiquette and Ethics) Regulations 2002, reg. 1.3.1, require indoor records to be kept for 3 years. State Clinical Establishments rules and medico-legal practice often require longer (e.g. MLC cases, minors). DPDP s.8(7) explicitly yields to retention "required for compliance with any law".
- **US.** HIPAA requires documentation to be kept for 6 years. State medical-record laws set clinical retention, commonly 7-10 years or until a minor reaches majority plus some years.

So the app **never hard-deletes** clinical rows in response to a request. A resolved erasure must state one of these outcomes:

- `retained_legal_hold`: kept under retention law. The note cites the basis and period.
- `restricted_processing`: kept but excluded from non-care purposes, such as research or analytics.
- `completed_outside_system`: deletion was carried out through the facility's controlled DB procedure after retention expired. The note references the change ticket.

Resolving any request requires a resolution note of at least 10 characters. Erasure also requires an `outcome`.

## Notice registry (in-repo)

Versioned markdown notices live under `docs/legal/` and are served by `GET /api/v1/legal/notices` and `GET /api/v1/legal/notices/{id}?lang=en|hi|mr`. Consent capture and Privacy rights UI load `privacy-notice.v1` before recording consent. Counsel must still review copy and appoint a named DPO / grievance officer (**Out-of-repo**).

## Not yet done

- Consent-manager (DPDP s.6(7)) and live ABDM consent-artefact integration (sandbox stubs only — see `docs/ABDM_SANDBOX.md`)
- Named DPO / grievance officer and facility-owned counsel sign-off on notice text
- Automated purpose-expiry review and a retention scheduler for real deletion after legal hold ends
- Accounting of disclosures made outside the system (fax, email, payer portals)
- Desk UI for `/privacy/requests` (API only today; staff can use the API or OpenAPI on local)
