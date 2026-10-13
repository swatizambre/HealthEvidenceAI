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

## Legal / compliance aspects (program outside pure code)

| Topic | Expectation |
|-------|-------------|
| **Confidentiality** | Treat charts as confidential health information; access only for care / PA documentation readiness / patient self-access |
| **Minimum necessary** | Care-team open chart is acceptable for this demo desk; production should add panel, encounter, or facility assignment |
| **Right of access** | Patient sees *own* lifelong record; not other patients |
| **Consent / purpose** | Visit notes require consent attestation; synthetic default until PHI program attested |
| **Auditability** | Retain access and denial logs for investigations and accountability |
| **Breach readiness** | Encryption in transit (TLS), at rest (DB/volume), IdP SSO, retention & delete-on-request policies |
| **Cross-border** | `DATA_RESIDENCY_REGION` + org contracts before multi-country PHI |
| **Not a medical device** | Isolation does not make outputs diagnostic or coverage decisions |

## Production checklist (before real PHI)

- [ ] OIDC IdP maps `patient_id` (or MRN→PAT map) from verified identity — never client-editable alone
- [ ] TLS everywhere; secrets out of repo; PostgreSQL; `AUTH_MODE=oidc`
- [ ] Care-team scoped by facility / panel (narrow beyond “any staff sees any chart”)
- [ ] BAA / DPA with processors; workforce training; break-glass with extra audit
- [ ] Retention, export, and erasure workflows
- [ ] Independent security assessment

## Demo caveat

Local `AUTH_MODE=dev-jwt` proves isolation with mintable roles. `AUTH_MODE=none` (tests) disables RBAC — never use in shared or production environments.
