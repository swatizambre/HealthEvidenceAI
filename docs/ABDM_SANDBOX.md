# ABDM / ABHA sandbox checklist

**Status:** Documentation + API stubs only. No live ABDM HIP/HIU integration.

## Goal

Register HealthEvidence AI as a **Personal Health Record (PHR)** style app in the ABDM sandbox, link **ABHA**, and support consent-based record pull — then certify.

## Regulatory dates (planning)

| Milestone | Date (indicative) |
|-----------|-------------------|
| Consent-manager rules | 12 Nov 2026 |
| Fuller DPDP obligations | 13 May 2027 |

Confirm with counsel; dates may change.

## In-repo stubs

- Patient field `abha_id` (nullable).
- `GET /api/v1/abdm/status` → sandbox configuration state.
- `POST /api/v1/abdm/link` → returns `not_configured` until credentials exist.
- UI: “Link ABHA (sandbox)” disabled when status is not ready.

## Out-of-repo steps

1. Create ABDM sandbox account and register as PHR / HIU as appropriate.
2. Obtain client credentials; store in secrets manager (never commit).
3. Implement ABHA OTP linking and consent artefact exchange.
4. Map FHIR resources to lifelong chart events.
5. Pass certification before production.

## Product rule

Until certified, never claim ABDM interoperability in marketing. Synthetic demos use local charts only.
