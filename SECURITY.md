# Security

HealthEvidence AI is not a medical device and is not intended for clinical diagnosis.

Do not load uncontrolled real patient data, credentials, or secrets into this repository.

Configure `AUTH_MODE=oidc` for shared and production environments. Treat development JWT mode as local-only.

Design detail: [docs/SECURITY_DESIGN.md](docs/SECURITY_DESIGN.md).  
Pilot checklist: [docs/PILOT_ROADMAP.md](docs/PILOT_ROADMAP.md). Keep secrets out of git; use `.env.example` / `.env.pilot.example` as templates only.

Report issues that would leak data or turn an evidence review into an autonomous clinical action. Do not include real protected health information in a report.
