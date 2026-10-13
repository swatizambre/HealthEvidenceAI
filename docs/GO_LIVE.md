# Go-live runbooks: synthetic DEMO and real-data TRIAL

There are two ways to put HealthEvidence AI in front of people:

| | **DEMO** | **REAL-DATA TRIAL** |
|---|---|---|
| Data | Synthetic only (seeded Synthea-style patients) | Real patient data at **one** hospital (`TRIAL_SITE_ORG_CODE`) |
| Who | Stakeholders, sales, training | Named staff at the trial site, under an approved protocol |
| Auth | `dev-jwt` (role switcher in the top bar) | Hospital / production OIDC IdP only |
| Banner | `DEMO — synthetic data` | `REAL-DATA TRIAL — <site> until <date>` |
| Gate | `make go-live-check MODE=demo` | `make go-live-check MODE=trial` + the signed checklist below |
| Compose | `docker-compose.demo.yml` | `docker-compose.trial.yml` |

> **Green CI and a green go-live check are not approval.** They show that the software is
> configured the way this document describes. They are not clinical validation, ethics
> approval, legal sign-off under the DPDP Act 2023, or a security assessment. Those come
> from the people and documents listed below. The product is documentation decision
> support: it does not diagnose, approve, or deny care.

---

## 1. DEMO runbook (synthetic data)

### 1.1 Bring up

```bash
export DEV_JWT_SECRET="$(openssl rand -hex 24)"     # ≥32 chars, new per demo host
make demo-up                                        # compose: base + pilot + demo overlays
# = docker compose -f docker-compose.yml -f docker-compose.pilot.yml -f docker-compose.demo.yml up --build -d
```

The demo overlay sets `ENVIRONMENT=local`, `AUTH_MODE=dev-jwt`, `ALLOW_PHI=false`,
`PHI_PROGRAM_ATTESTED=false`, `SEED_ON_STARTUP=true`, `LLM_PROVIDER=local`.

### 1.2 Gate (before every stakeholder session)

```bash
DEMO="docker compose -f docker-compose.yml -f docker-compose.pilot.yml -f docker-compose.demo.yml"
# Run the gate inside the backend container so it sees the real runtime env + database:
$DEMO exec backend python -m evaluation.run_gold --path rules --out data/gold_gate_result.json
$DEMO exec backend python -m app.cli.go_live_check --mode demo --offline
make demo-gate                           # unit tests + ten personas + web/API smoke
curl -s http://127.0.0.1:8000/ready | jq '{status, mode, banner}'
# expect: "status":"ok", "mode":"demo", "banner":"DEMO — synthetic data"
```

### 1.3 What to show (about 15 minutes)

1. The **DEMO — synthetic data** banner. Say it out loud: no real patients.
2. **Records / TPA desk clerk** → Patients → open a chart → Lifelong history → **Prepare evidence pack**.
3. Close a gap with **Visit note** → re-check readiness → copy the handoff.
4. **Consultant / senior MO** → Reviews → check evidence → acknowledge or send back.
   There is no approve or deny button, by design.
5. Switch facility to the PHC tenant to show that another org's queue is empty.
6. Sample cases: `PA-000001` (complete), `PA-000002` (gaps, needs human review).

Do not type real patient details into a demo, even "just to try". The demo host has no
DPDP controls, no IdP, and anyone with the URL can mint a token.

### 1.4 Reset and teardown

```bash
# Reset to fresh synthetic data (keeps containers):
docker compose -f docker-compose.yml -f docker-compose.pilot.yml -f docker-compose.demo.yml \
  exec backend python -m app.cli.seed
# Full teardown including the database volume:
docker compose -f docker-compose.yml -f docker-compose.pilot.yml -f docker-compose.demo.yml down -v
unset DEV_JWT_SECRET
```

---

## 2. REAL-DATA TRIAL runbook (one hospital, India first)

Scope: one hospital (`TRIAL_SITE_ORG_CODE`), a fixed end date (`TRIAL_END_DATE`), and a
small named user group. The trial measures documentation time saved. It is not a test of
clinical outcomes. ABDM / ABHA integration is out of scope for the first trial.

### 2.1 Non-code prerequisites (all signed before `ALLOW_PHI=true`)

Each item needs an owner and a document reference. Keep the sign-off sheet with the IEC file.

| # | Item | Evidence / owner | Setting it feeds |
|---|------|------------------|------------------|
| 1 | **Institutional Ethics Committee (IEC) approval** of the trial protocol (ICMR National Ethical Guidelines), including the data flow, the consent approach, and stop criteria | IEC approval letter + number | `TRIAL_ETHICS_APPROVAL_REF` |
| 2 | **DPDP notice + consent forms** in English and the local languages patients use at the site (for example Hindi, Marathi). Must state purpose, data categories, retention, how to withdraw consent, and how to complain to the Data Protection Board | Approved notice and consent text, translation certificates | `ConsentRecord` rows (consent workstream) |
| 3 | **Data Protection Officer / grievance officer** named and published to patients | Appointment letter, contact on notice | `DPO_CONTACT` |
| 4 | **Data processing agreement** with the hosting provider (and with any LLM vendor if cloud LLM is used — default is no), covering India residency, sub-processors, breach notice and deletion | Signed DPA | `DATA_RESIDENCY_REGION`, `LLM_BAA_ATTESTED` |
| 5 | **VAPT / security assessment** of the deployed stack by a CERT-In empanelled auditor, with high and critical findings closed | Report id + retest letter | `SECURITY_ASSESSMENT_REF` |
| 6 | **Clinician sign-off on the gold set**: at least 2 clinicians independently label criteria for the site's top policies, then reconcile. Rules-path false-SUPPORTED rate must be 0 on that set | Signed gold file; `dataset_status: clinician_gold` | `make eval-gold-report` |
| 7 | **Staff training**: every user completes a session on what the tool is not (no approvals, no diagnosis), how to report a wrong SUPPORTED, and break-glass rules | Attendance sheet | IdP group membership |
| 8 | **Incident and breach response runbook**: who decides, who calls whom, with timelines (see 2.6) | Runbook URL, on-call roster | `BREACH_RUNBOOK_URL` |
| 9 | **Retention schedule** aligned to medical-records rules (IMC Regulations 2002: at least 3 years for in-patient records; follow state rules and hospital policy where longer). Also decides what happens to trial data at exit | Hospital records officer sign-off | Exit plan (2.9) |
| 10 | **Regulatory classification** reviewed (decision support, not SaMD under the Medical Devices Rules 2017, for the claims made). Confirm with counsel | Counsel memo | — |
| 11 | **Hospital IT change control** for any HIS/FHIR feed ([opd-ingest-roadmap.md](opd-ingest-roadmap.md#change-control-p26--before-any-live-ehr-feed)) | Signed change record | `HOSPITAL_INTERFACE_KEYS` |

These are references to signed documents. The application checks that they are recorded,
not that they are valid. Do not enter placeholder values to get past the boot gate.

### 2.2 Infrastructure

- **Database:** managed PostgreSQL in the attested region (for example AWS `ap-south-1` or Azure `centralindia`),
  with encryption at rest, TLS (`sslmode=require`), point-in-time recovery, and a restore drill
  done before go-live. No public endpoint. Never publish port 5432 (the trial overlay removes it).
- **TLS:** HTTPS only, via a reverse proxy or ingress. The trial overlay binds the API and UI to `127.0.0.1`.
- **Identity:** production Keycloak or the hospital IdP (Entra ID and others), never `start-dev`
  with `admin/admin` or the `change-me` realm users from `docker-compose.oidc.yml`. MFA for
  admin and senior roles. Tokens must carry `org_code` = `TRIAL_SITE_ORG_CODE`. See the
  [production Keycloak checklist](OIDC_PILOT.md#production-keycloak-checklist).
- **Secrets:** a secrets manager or Kubernetes Secrets (`DATABASE_URL`, `OIDC_CLIENT_SECRET`,
  `STREAM_TICKET_SECRET`, `STAFF_PSEUDONYM_SECRET`, `HOSPITAL_INTERFACE_KEYS`, `DPO_CONTACT`). Never commit them to git, put them in the image, or set them in a ConfigMap.
- **LLM:** `LLM_PROVIDER=local` or on-host `ollama`. Cloud providers are blocked under PHI
  unless `LLM_BAA_ATTESTED` and `LLM_PHI_EGRESS_ALLOWED` are both true and covered by item 4.
- **Logs and backups** stay in the same region. Application logs carry no note text, but they do carry IDs.

### 2.3 Configuration

`docker-compose.trial.yml` refuses to start until each of these is set. In Kubernetes,
`deploy/kubernetes/configmap.yaml` and `secret.example.yaml` hold them.

| Variable | Trial value |
|---|---|
| `ENVIRONMENT` | `pilot` (or `staging` / `production` / `kubernetes`). Never `local` / `test` with real data |
| `AUTH_MODE` | `oidc`, with `OIDC_ISSUER` (https) and `OIDC_JWKS_URL` |
| `DATABASE_URL` | PostgreSQL |
| `ALLOW_PHI`, `PHI_PROGRAM_ATTESTED` | `true` only after 2.1 is signed (overlay default is `false`) |
| `ENFORCE_ORG_SCOPE` | `true` |
| `SEED_ON_STARTUP` | `false` |
| `SYNTHETIC_LIFELONG` | `false` |
| `HOSPITAL_ALLOW_SIMULATE` | `false` |
| `LLM_PROVIDER` / `LLM_FALLBACK_PROVIDERS` | `local` (or `ollama`) |
| `TRIAL_ETHICS_APPROVAL_REF` | IEC approval id |
| `DPO_CONTACT` | DPO / grievance officer contact |
| `SECURITY_ASSESSMENT_REF` | VAPT report id |
| `BREACH_RUNBOOK_URL` | Incident runbook location |
| `DATA_RESIDENCY_REGION` | Concrete region, not `global` |
| `TRIAL_SITE_ORG_CODE` | Single org in the trial, for example `ORG-000001` |
| `TRIAL_END_DATE` | `YYYY-MM-DD`. Boot fails once it has passed |
| `HOSPITAL_INTERFACE_KEYS` | Per-org HIS keys, if a machine feed is used (interface-keys workstream) |
| `STREAM_TICKET_SECRET` | ≥32 chars, for SSE stream tickets |
| `STAFF_PSEUDONYM_SECRET` | ≥32 chars, different from `STREAM_TICKET_SECRET`; keys the "Care team member · ref …" pseudonyms in patient access logs so staff identities cannot be recovered by hashing guessed emails |
| `RATE_LIMIT_ENABLED` | `true` (default when unset outside tests). Limits are **per replica** and per client/principal; all traffic from one hospital interface key shares one bucket (`RATE_LIMIT_INGEST_PER_MINUTE`, default 120/min) — raise it for busy HIS feeds before go-live |
| `CORS_ORIGINS` | The trial UI's https origin only |
| `POSTGRES_PASSWORD` | Required if using the bundled Postgres container (no default) |

When `ALLOW_PHI` and `PHI_PROGRAM_ATTESTED` are both true, `Settings.validate_live_configuration`
enforces the environment, OIDC, PostgreSQL, org scope, seed-off, no-synthetic-lifelong and
attestation rules in **any** environment. It lists every missing item in one
`LIVE_CONFIG_INVALID` error.

### 2.4 Go-live day

1. Freeze the release: tag the commit and record the image digest in the change record.
2. Run the gold gate against the clinician-signed gold file. Expect `passed: true`:
   `python -m evaluation.run_gold --path rules --cases <signed.json> --out data/gold_gate_result.json`.
3. Run `make go-live-check MODE=trial` with the trial env loaded (or
   `docker compose ... exec backend python -m app.cli.go_live_check --mode trial`). Before the PHI
   flags flip, it reports `trial.phi_flags` as the only expected FAIL. Every other FAIL must be
   fixed. Each WARN needs a written owner decision.
4. Run `alembic upgrade head` (the API also upgrades at boot and fails closed in pilot or shared live).
5. Start with `ALLOW_PHI=false` and smoke test with IdP accounts: sign in as each role, check that
   `/ready` shows `mode` = `practice`, and confirm that a wrong-org token sees nothing.
6. Flip `ALLOW_PHI=true` and `PHI_PROGRAM_ATTESTED=true`, then restart. Confirm `/ready` shows `"mode":"trial"`,
   the `trial_site_org_code`, the `trial_end_date`, and the red **REAL-DATA TRIAL** banner in the UI.
7. `GET /api/v1/auth/oidc/status?discover=true` → `oidc_ready: true`.
8. `POST /api/v1/auth/dev-token` must be refused.
9. First real packet: one consented patient, with the DPO or trial lead watching. Check the audit row
   (`GET /api/v1/audit/events?action=opd_ingest`) and the patient-rights endpoints
   (`/api/v1/me/access-log`, `/me/export`, `/me/requests`) for that patient.
10. Announce go-live to the user group, with the false-SUPPORTED reporting route.

### 2.5 Daily monitoring (trial lead + on-call, 15 minutes)

- **False-SUPPORTED reports** from reviewers. Each one is triaged the same day: was it
  shown to a payer? (If yes, see stop criteria.) Add the case to the gold set.
- **Audit review:** `GET /api/v1/audit/events` filtered by `break_glass`,
  `patient_scope_denied`, `tool_permission_denied`, `pack_export`. Every break-glass has a reason
  that the lead accepts.
- **Access-denied spikes:** a jump in `patient_scope_denied` / `ORG_SCOPE_FORBIDDEN` means either
  misconfigured IdP claims or someone probing. Investigate the same day.
- `/metrics`: `healthevidence_audit_durable_write_failures_total` must stay at 0. Any increase
  means audit rows are being lost and must be investigated the same day.
- `/ready` stays 200. Backups completed. Disk and DB growth look normal.
- Days to `TRIAL_END_DATE`: the API refuses to boot after that date, so extend through IEC first.

### 2.6 Incidents and breach timelines

| Event | Clock | Action |
|---|---|---|
| Cyber security incident (CERT-In Directions, April 2022) | **6 hours** from noticing | Report to CERT-In (`incident@cert-in.org.in`) via the hospital CISO |
| Personal data breach (DPDP Act 2023 + DPDP Rules) | **Without delay**, with a detailed report within **72 hours** | Notify the Data Protection Board and affected patients, through the DPO |
| Breach involving the hosting provider | Per DPA (typically ≤24h to the hospital) | Provider notifies the hospital DPO |
| Internal escalation | Immediately | On-call → trial lead → DPO → hospital CISO / medical superintendent |

Keep a log from the first minute (who noticed, when, what was touched). Preserve the audit
table and logs. Do not delete data during an incident. Confirm the exact timelines and forms with counsel.

### 2.7 Stop criteria (pause the trial: set `ALLOW_PHI=false` and restart)

Stop immediately on any of:

- Any **PHI leak**: chart data visible to the wrong org or user, exposed in logs or exports outside
  the site, or sent to an unattested LLM.
- A **false-SUPPORTED that reached a payer**: an evidence pack claimed a criterion was documented
  when it was not, and it was submitted.
- **Unauthorized access**: a user or token outside the trial group read a chart, or break-glass
  was used without an accepted reason.
- Audit rows being lost (the durable-failure counter is non-zero and unexplained).
- The IEC, DPO or hospital asks for a stop.

### 2.8 Rollback

1. Set `ALLOW_PHI=false` (the API returns to practice mode and rejects real-data ingest). If you
   cannot trust the instance, scale the API to zero instead.
2. Disable HIS feeds: remove the site's `HOSPITAL_INTERFACE_KEYS` entry.
3. Revoke sessions at the IdP for affected users.
4. If code is at fault, redeploy the previous tagged image. Migrations are additive, but take a PITR
   restore point before any downgrade.
5. Write up the root cause. The IEC decides whether to resume.

### 2.9 Weekly review and exit

Weekly (trial lead, a clinician reviewer, DPO, engineering):

- **Minutes saved per packet:** desk time with the tool vs a baseline measured before go-live
  (`/api/v1/metrics/ops` cycle fields plus time-and-motion samples).
- **Packet completeness:** share of packets with no open checklist items at handoff, and payer
  queries per packet.
- **Reviewer override rate:** how often seniors send back or edit the assistant's evidence.
  A rising rate is a quality signal, not a training problem.
- False-SUPPORTED count (target: 0), access-denied trends, consent withdrawals, patient
  requests answered in time.

**Exit criteria** (agreed with the IEC up front): a fixed number of packets or weeks, zero
stop events, and pre-registered thresholds for minutes saved and override rate. At exit,
set `ALLOW_PHI=false`. Then export or return data per the retention schedule and DPA. Then delete or
archive per item 9. Then record the deletion certificate.

---

## Related

- [LAUNCH.md](LAUNCH.md): demo and pilot quick paths
- [PRODUCTION_CHECKLIST.md](PRODUCTION_CHECKLIST.md): shared-live platform gates
- [LIVE_READY.md](LIVE_READY.md): hospital desk platform readiness
- [OIDC_PILOT.md](OIDC_PILOT.md): IdP wiring and the production Keycloak checklist
- [data-privacy.md](data-privacy.md): product privacy rules
