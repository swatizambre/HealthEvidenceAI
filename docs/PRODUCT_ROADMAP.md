# HealthEvidence AI — product roadmap tracker

**Promise:** Your lifelong health record that keeps every doctor, anywhere, from giving you the wrong medicine.

**Focus:** Patient-owned lifelong health record + doctor AI view first. India TPA / cashless insurance desk is a **later hospital (B2B) module**.

**Intended use:** Organises and shows health records with sources. Does **not** diagnose, prescribe, approve, or deny care. Not a medical device until counsel says otherwise.

Statuses: `Done` (in repo) · `In-repo` (this unblock) · `Out-of-repo` (people, legal, partners).

Default git branch: **`master`**. Phase 0 housekeeping: India TPA desk merged (PR #9), #7 closed, `ui-review/*` branches deleted.

| # | Item | Phase | Status | Owner | Target |
|---|------|-------|--------|-------|--------|
| — | Lifelong record, consent, patient rights, audit, rate limits | — | Done | eng | — |
| — | Evidence engine (citations, negation, family hx, gold gate) | — | Done | eng | — |
| — | India TPA desk + go-live gate + CI screenshots | — | Done | eng | later B2B |
| 1 | Confirm patient-first focus (TPA later) | 0 | Done | product | w0 |
| 2 | Product name + one-line promise | 0 | Done | product | w0 |
| 3 | Merge #9, close #7, delete ui-review/*, master vs main | 0 | Done | eng | w0 |
| 4 | Company, roles, advisors (doctor, pharmacologist, genetic counsellor, privacy lawyer) | 0 | Out-of-repo | founders | w0–2 |
| 5 | 12-month budget / funding plan | 0 | Out-of-repo | founders | w0–2 |
| 6 | Interview 15–20 patients/caregivers | 1 | Out-of-repo | research | w1–5 |
| 7 | Interview 8–10 doctors | 1 | Out-of-repo | research | w1–5 |
| 8 | Clickable patient + doctor design (in-app prototype) | 1 | In-repo | eng/design | w1–5 |
| 9 | Formal Figma / 8–10 usability tests | 1 | Out-of-repo | design | w1–5 |
| 10 | Product brief + success metrics | 1 | In-repo | product | w1–5 |
| 11 | DPDP notices EN/HI/MR + consent screens (templates) | 2 | In-repo | eng/legal | parallel |
| 11b | Named DPO + grievance officer; counsel review | 2 | Out-of-repo | legal | parallel |
| 12 | ABDM sandbox registration + ABHA stubs | 2 | In-repo (stub) | eng | parallel |
| 12b | ABDM certification + live HIP consent | 2 | Out-of-repo | eng/ops | 2026–27 |
| 13 | AI intended-use statement (in-repo); CDSCO lawyer opinion | 2 | In-repo / Out-of-repo | eng / counsel | parallel |
| 14 | Genetic data policy template | 2 | In-repo | eng/legal | parallel |
| 15 | Terms, emergency-access policy, cyber insurance | 2 | Out-of-repo | legal | parallel |
| 16 | India data residency + abroad viewing rules | 2 | Out-of-repo | legal | parallel |
| 17 | VAPT before launch; ISO 27001 later | 2 | Out-of-repo | security | pre-launch |
| 18 | Patient account owner + family / caregiver access | 3 | In-repo (demo) | eng | w4–14 |
| 19 | FHIR-aligned data model room for genetics | 3 | Partial / Done base | eng | w4–14 |
| 20 | Phone OTP + ABHA + 2FA + device trust | 3 | Out-of-repo / later | eng | w4–14 |
| 21 | Encrypted India-region file store + virus scan | 3 | Out-of-repo / later | eng | w4–14 |
| 22–26 | OCR / extract / patient confirm loop | 3 | Partial (extract exists) | eng | w4–14 |
| 27 | Lifelong timeline filters | 3 | Partial / Done | eng | w4–14 |
| 28 | Emergency card (QR, offline, open notify) | 3 | In-repo (demo) | eng | w4–14 |
| 29 | IPS emergency summary export | 3 | Out-of-repo / later | eng | w4–14 |
| 30 | Share with doctor (time-limited, revoke, view log) | 3 | In-repo (demo) | eng | w4–14 |
| 31 | Lab trends | 3 | Out-of-repo / later | eng | w4–14 |
| 32 | HI/MR/EN + low-end phones | 3 | Partial (EN/HI shell) | eng | w4–14 |
| 33–37 | Doctor brief, risk flags, meds, ask-with-sources, second-opinion pack | 3 | In-repo (demo) | eng | w4–14 |
| 38–42 | Model choice, gold set 100+, prompt injection, load/DR, Android | 3–4 | Partial / Out-of-repo | eng | w4–22 |
| 43–48 | Pilot hospital/lab, ethics, NPS | 4 | Out-of-repo | ops | w14–22 |
| 49–51 | Public launch, stores, pricing, ABDM push | 5 | Out-of-repo | gtm | post-pilot |
| 52–60 | Precision medicine (PGx, counsellor, wearables, trials) | 6 | Out-of-repo | clinical | later |
| 61–64 | Hospital module: TPA reuse, verified packet, NHCX, HIS | 7 | Desk Done; NHCX Out-of-repo | eng | later B2B |

## Success metrics (brief)

| Metric | Definition |
|--------|------------|
| Time to history | Seconds for a doctor to open brief + risk flags |
| Repeat tests avoided | Self-reported / pilot chart review |
| Allergies caught | Emergency card + risk flag hits vs gold set recall |
| MAU | Monthly active patient accounts (pilot) |

## Unblockers

Ship first: **#8** (clickable design), **#11–#13** (DPDP notices, ABDM stubs, AI intended-use). Everything else either extends those or is Out-of-repo.
