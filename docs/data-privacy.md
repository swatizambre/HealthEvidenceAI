# Patient data security & privacy

Planning aid — **not legal advice** and **not a certification**. Aligns product controls with common healthcare privacy expectations (HIPAA-style minimum necessary, GDPR-style purpose limitation / right of access, Indian DPDP-style consent & purpose).

## Product rules (enforced in code)

| Actor | What they can access |
|-------|----------------------|
| **Patient** | Only the chart bound to JWT `patient_id` (own lifelong record, own visit notes) |
| **Staff / resident / senior / admin** | Care-team chart access for PA desk and clinical continuity (need-to-know) |
| **Anonymous** | Nothing when `AUTH_MODE=dev-jwt` or `oidc` |

Cross-patient reads by a patient role return `403 PATIENT_SCOPE_FORBIDDEN`. Chart opens and denials are **audit-logged** (action, actor, patient id — never full note text).

## Practical controls shipped

1. **Identity binding** — Patient tokens must include `patient_id` (`PAT-######`). Frontend mints with the signed-in patient’s ID; API trusts the claim, not the URL alone.
2. **Self-scope on all chart APIs** — detail, essentials, timeline, lifelong, documents, evidence search, OPD write.
3. **Directory lock** — Patient list returns only self; worklist / cases / ops metrics are care-team only.
4. **UI hard stops** — Patient cannot open `/patients` directory, other chart URLs, or pick another MRN on Visit note.
5. **PHI gate** — Live non-synthetic ingest still requires `ALLOW_PHI` + `PHI_PROGRAM_ATTESTED` (see clinical roadmap).
6. **Stored consent** — Every OPD/FHIR ingest is linked to a `ConsentRecord` (`CNS-######`). In PHI mode an active consent for the patient + purpose is mandatory (`403 CONSENT_REQUIRED`); withdrawal blocks further ingest. See [CONSENT_AND_RIGHTS.md](CONSENT_AND_RIGHTS.md).
7. **Patient rights self-service** — Access log (who opened my record), JSON export, and correction / erasure / grievance / nominee requests with an org-scoped privacy desk. Staff personal identifiers are masked in patient views.

## Legal / compliance aspects (program outside pure code)

| Topic | Expectation |
|-------|-------------|
| **Confidentiality** | Treat charts as confidential health information; access only for care / PA documentation readiness / patient self-access |
| **Minimum necessary** | Care-team open chart is acceptable for this demo desk; production should add panel, encounter, or facility assignment |
| **Right of access** | Patient sees *own* lifelong record; not other patients |
| **Consent / purpose** | Stored, purpose-specific consent records (notice version, method, signer, expiry, withdrawal); PHI ingest requires an active consent; practice mode records a `synthetic-practice` consent |
| **Data-subject rights** | Access log, export, correction / erasure / grievance / nominee requests; erasure is a documented workflow because medical-record retention law applies |
| **Auditability** | Retain access and denial logs for investigations and accountability |
| **Breach readiness** | Encryption in transit (TLS), at rest (DB/volume), IdP SSO, retention & delete-on-request policies |
| **Cross-border** | `DATA_RESIDENCY_REGION` + org contracts before multi-country PHI |
| **Not a medical device** | Isolation does not make outputs diagnostic or coverage decisions |

## Production checklist (before real PHI)

- [ ] OIDC IdP maps `patient_id` (or MRN→PAT map) from verified identity — never client-editable alone
- [ ] TLS everywhere; secrets out of repo; PostgreSQL; `AUTH_MODE=oidc`
- [ ] Care-team scoped by facility / panel (narrow beyond “any staff sees any chart”)
- [ ] BAA / DPA with processors; workforce training; break-glass with extra audit
- [x] Stored consent records with purpose, notice version, withdrawal; consent enforced on PHI ingest
- [x] Patient access log (accounting of access), self-service export, and rights-request workflow
- [x] Erasure as a documented request workflow (no hard delete; legal-hold outcome recorded)
- [ ] Retention scheduler for deletion after legal hold expires; facility retention policy sign-off
- [ ] Consent-manager / ABDM consent-artefact integration; notice-version registry
- [ ] Independent security assessment

## Demo caveat

Local `AUTH_MODE=dev-jwt` proves isolation with mintable roles. `AUTH_MODE=none` (tests) disables RBAC — never use in shared or production environments.
