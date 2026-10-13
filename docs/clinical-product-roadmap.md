# Safety and compliance notes

This document is a planning aid. It does not certify HealthEvidence AI for clinical use.

**Design docs:** [INDEX.md](INDEX.md) · [HLD.md](HLD.md) · [SECURITY_DESIGN.md](SECURITY_DESIGN.md)

## Product boundary

HealthEvidence AI organizes evidence against explicit policy criteria. It does not approve treatment, deny treatment, diagnose, or prescribe.

**Not for clinical use. Not a medical device.**

## Clinical deployment requirements

Hospital or payer clinical use requires programs outside this repository, including:

1. Regulatory classification and pathway for the target jurisdiction
2. Clinical validation with licensed clinicians and defined outcomes
3. Privacy program for protected health information
4. Enterprise identity, SSO, RBAC, break-glass, and audit review
5. EHR / FHIR integration under change control
6. Liability, insurance, and vendor risk processes
7. High-availability operations, disaster recovery, and support SLAs
8. Independent security assessment and ongoing monitoring

Until those exist under an accountable organization, treat the system as an evidence-organization platform for synthetic or controlled non-clinical datasets.

Runtime gates in this repo: `ALLOW_PHI=false` by default; production/staging require OIDC + PostgreSQL; `ALLOW_PHI=true` additionally requires `PHI_PROGRAM_ATTESTED=true`. OPD/FHIR ingest stays synthetic unless those flags are set.

## OPD ingest direction

Bulk Synthea seed is the current path. The planned move to **patient-wise intake during an outpatient visit** is sketched in [opd-ingest-roadmap.md](opd-ingest-roadmap.md) (manual packet → UI workflow → FHIR, in that order).

## Stakeholder language

> HealthEvidence AI is an evidence-organization platform. It is not approved for clinical use and is not a substitute for licensed clinical or utilization-management judgment.
