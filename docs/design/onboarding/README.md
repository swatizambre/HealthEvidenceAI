# Onboarding designs (Lifelong Health)

Source files for the onboarding design canvas. Each `*.dc.html` is one screen; `canvas.json` is the board layout.
They are design references, not app code: they render inside the Claude design canvas (they load its `support.js`).

| Flow | Screens |
| --- | --- |
| Patient and family (phone) | `Main` welcome → `P2-Consent` → `P3-Import` (ABHA + paper scan) → `P4-Review` (check what AI read) → `P5-Emergency` (offline emergency card) → `P6-Family` |
| Doctor | `D1-Verify` (HPR / council check, passkey) → `D2-Scan` (patient QR) → `D3-Brief` (desktop patient brief with sources) |
| Hospital (desktop) | `H1-Setup` (HFR verify, connect FHIR / HL7 / exports) → `H2-Reception` (shared-today queue, QR standee, staff SSO) |

Rules the designs follow:

- Every AI line links to its source document; the brief ends with "Clinical judgement is yours." No diagnosis or prescribing.
- Patients choose what to share and for how long; every view lands in their access log.
- Touch targets at least 44 px; plain language; Hindi alongside English where patients see it.
- Names, IDs and lab values are placeholders (`[Patient name]`, `[HFR ID]`) or illustrative.
