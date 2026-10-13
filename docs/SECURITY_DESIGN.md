# Security design

Enforcement as implemented in code. Planning notes for privacy programs: [data-privacy.md](data-privacy.md). Reporting stance: [SECURITY.md](../SECURITY.md).

## 1. Goals

- Keep decision-support drafts from becoming autonomous clinical or coverage actions
- Isolate patient self-access from care-team desks
- Optionally isolate facilities via org claims
- Audit sensitive actions without logging clinical note bodies into security exports

## 2. Authentication modes

| `AUTH_MODE` | Behavior |
|-------------|----------|
| `dev-jwt` | HS256 tokens; `POST /auth/dev-token` (local / UAT) |
| `oidc` | RS256/ES256 via JWKS; required for staging/production |
| `none` | No principal; **only** allowed when `ENVIRONMENT=test` |

Principal (`AuthPrincipal`): `subject`, `email`, `roles`, optional `patient_id`, `org_id`, `org_code`.

OIDC setup: [OIDC_PILOT.md](OIDC_PILOT.md).

## 3. Product RBAC

Normalized roles (`app/auth/rbac.py`):

| Role | Capabilities (API-level) |
|------|---------------------------|
| `patient` | Own chart only (linked `patient_id`) |
| `staff` | Care team: prepare, review, write notes; no HITL resume |
| `resident` | Same as staff for prep/review/write; no HITL resume |
| `senior_clinician` | Care team + HITL resume |
| `admin` | All care-team + audit export + break-glass; org scope bypass |

Legacy `reviewer` maps to senior. Many IdP aliases normalize into the five roles.

Role sets on routes: chart read/write, packet prep, evidence check, HITL, care-team (meta desk).

## 4. Patient record scope

`app/auth/patient_scope.py`:

- **Patient-only:** may read/write only linked `PAT-######`
- **Care team:** may access any patient **unless** org scope forbids
- List endpoint collapses to self for patients

## 5. Organization scope

When `ENFORCE_ORG_SCOPE=true`:

- Care-team tokens need `org_id` or `org_code` (admin exempt)
- Patient lists, worklist, cases, stats, ops metrics filter by patient org
- Chart open + writes call `ensure_org_patient_access`
- OPD ingest stamps `org_id` from token org or default org
- Prepare / review / resume enforce patient access (includes org check)

UI mints `ORG-000001` for care-team `dev-jwt` tokens (`frontend/src/api.ts`).

## 6. Agent / MCP permissions

Separate from user JWT. Named agents (`PolicyAgent`, `ClinicalEvidenceAgent`, …) may only call tools granted in `AGENT_PERMISSIONS`. HTTP `/tools/invoke` uses the same gate.

## 7. Safety rails

- `enforce_decision_support` on review outputs — reject approve/deny/diagnose language
- Help desk refuses coverage/diagnosis coaching
- OPD: `synthetic` + `consent_attested` required unless PHI program attested
- Production/staging/pilot validate Postgres + OIDC (as configured) + PHI attestation pairing

## 8. Break-glass & audit

| Mechanism | Detail |
|-----------|--------|
| `POST /security/break-glass` | Admin declares emergency chart access + reason |
| `GET /audit/events` | Admin filterable export |
| Typical actions | `opd_ingest`, `authorization_review`, `break_glass`, patient scope denials |

## 9. Secrets

- Never commit `.env` or IdP client secrets
- Templates: `.env.example`, `.env.pilot.example`
- `/auth/oidc/status` reports presence, not secret values

## Related

- [HLD.md](HLD.md) trust boundaries
- [SEQUENCE_FLOWS.md](SEQUENCE_FLOWS.md)
- [PRODUCTION_CHECKLIST.md](PRODUCTION_CHECKLIST.md)
