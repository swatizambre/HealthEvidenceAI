# OIDC pilot IdP wiring (P1.9)

Point a real identity provider at HealthEvidence AI for shared pilot tenants. Local UAT may keep `AUTH_MODE=dev-jwt`.

## Quick path — local Keycloak

```bash
docker compose -f docker-compose.yml -f docker-compose.pilot.yml -f docker-compose.oidc.yml up --build
```

- Keycloak admin: http://127.0.0.1:8080 (admin / admin)
- Realm: `healthevidence` (imported from [`deploy/keycloak/realm-healthevidence.json`](../deploy/keycloak/realm-healthevidence.json))
- Dev users (password `change-me`): `staff`, `senior`, `resident`, `admin`, `patient1`

Discover JWKS from the issuer:

```bash
uv run python -m app.cli.oidc_discover http://127.0.0.1:8080/realms/healthevidence
```

Paste the printed `OIDC_ISSUER` / `OIDC_JWKS_URL` into `.env` (or rely on compose defaults for the API container).

Check readiness:

```bash
curl -s "http://127.0.0.1:8000/api/v1/auth/oidc/status?discover=true"
```

## Env vars (shared pilot)

| Variable | Purpose |
|----------|---------|
| `AUTH_MODE=oidc` | Require IdP JWTs (disables `/auth/dev-token`) |
| `OIDC_ISSUER` | Issuer URL from IdP |
| `OIDC_JWKS_URL` | JWKS endpoint (or discover from issuer) |
| `OIDC_AUDIENCE` | Default `healthevidence-api` |
| `OIDC_CLIENT_ID` | Used to read `resource_access.<client>.roles` |
| `OIDC_ROLES_CLAIM` | Default `roles` |
| `OIDC_REQUIRED_ROLES` | Product roles allowed into the API |

Template: [`.env.pilot.example`](../.env.pilot.example).

## Role mapping

IdP realm / app roles are normalized in [`app/auth/rbac.py`](../app/auth/rbac.py):

| IdP role | Product role |
|----------|--------------|
| staff, coordinator, records, nurse | staff |
| senior_clinician, reviewer, attending | senior_clinician |
| resident, junior_doctor | resident |
| admin | admin |
| patient | patient (+ `patient_id` claim for self chart) |

Claims accepted for patient link: `patient_id`, `healthevidence_patient_id`, `linked_patient_id`, or `sub` matching `PAT-######`.

### Organization / facility claims (P2.5)

When `ENFORCE_ORG_SCOPE=true`, care-team tokens must carry an org binding. Admin bypasses.

| Claim keys (any) | Maps to |
|------------------|---------|
| `org_id`, `organization_id`, `healthevidence_org_id` | `organizations.id` |
| `org_code`, `organization_code`, `facility_code`, `healthevidence_org_code` | `organizations.org_code` (e.g. `ORG-000001`) |

Local mint: `POST /api/v1/auth/dev-token` accepts `org_id` / `org_code`. `/api/v1/auth/me` echoes them.

## Entra ID / Auth0 / other IdPs

1. Create an API audience / app registration matching `OIDC_AUDIENCE`
2. Assign app roles matching the table above
3. Set issuer + JWKS from the IdP’s OpenID configuration:

```bash
uv run python -m app.cli.oidc_discover https://login.microsoftonline.com/<tenant>/v2.0
```

4. Set `ENVIRONMENT=pilot`, PostgreSQL `DATABASE_URL`, `AUTH_MODE=oidc`
5. Confirm `GET /api/v1/auth/oidc/status` shows `oidc_ready: true`

## Security notes

- Never commit client secrets; inject via secret manager
- Change Keycloak default passwords before any network exposure
- Staging/production already require OIDC + PostgreSQL ([`validate_live_configuration`](../app/core/config.py))
