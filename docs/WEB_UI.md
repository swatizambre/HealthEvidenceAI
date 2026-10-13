# Web UI design

React 18 + TypeScript + Vite SPA under `frontend/`. Talks to the FastAPI backend via `/api` (Vite proxy in dev; same-origin in Docker nginx).

Companion docs: [HLD.md](HLD.md) · [API_OVERVIEW.md](API_OVERVIEW.md) · [LAUNCH.md](LAUNCH.md) · [SECURITY_DESIGN.md](SECURITY_DESIGN.md)

## 1. Purpose

Clinician and patient **desk** for:

1. Prior-auth **evidence packet** prep and senior review (decision support only)
2. **Lifelong chart** across facilities (synthetic / consent-gated)
3. **Visit notes** / OPD ingest into the chart

The UI never presents approve/deny coverage language as a clinical action.

## 2. Stack

| Piece | Choice |
|-------|--------|
| Framework | React 18 + React Router |
| Language | TypeScript |
| Build | Vite |
| Auth (local) | `POST /api/v1/auth/dev-token` from `api.ts` |
| Role state | `roleContext.tsx` (localStorage) |
| Styling | `frontend/src` CSS (app shell, pages) |

Dev:

```bash
cd frontend && npm ci && npm run dev -- --host 127.0.0.1 --port 5173
```

Docker UI: port **3000** (see [DEPLOYMENT.md](DEPLOYMENT.md)).

## 3. Information architecture

### Routes

| Path | Page | Audience |
|------|------|----------|
| `/` | Today (`Dashboard`) | Care team |
| `/patients` | Patient list | Care team |
| `/patients/:patientId` | Chart + prepare packet | Care team / patient (own id) |
| `/reviews` | Authorization Reviews | Clinicians (HITL for senior) |
| `/visit` | Visit note / OPD ingest (+ FHIR tab) | Care team / patient |
| `/my-record` | Lifelong / my record | Patient primary; care team can open lifelong view |
| `/encounter`, `/opd` | Redirect → `/visit` | Compat |
| `/authorization` | Redirect → `/reviews` | Compat |

Patient role nav: **My record** · **Add note** · **Full chart** (linked `myPatientId` only).

Care-team nav: **Today** · **Lifelong record** · **Reviews** · **Patients** · **Visit note**.

### Chrome

- Brand: HealthEvidence AI + value strip
- Facility select (clinic → teaching) — presentation; care-team tokens still mint `ORG-000001` for org scope demos
- Role select — remints JWT roles (+ `patient_id` / `org_code` as needed)
- Footer disclaimer (not a medical device)
- Floating **Help** chat (`HelpChat`) — workflow help; refuses diagnosis/coverage decisions

## 4. Desk roles (UI)

| UI role | JWT roles | Can prepare | Can review | HITL resume | Write notes |
|---------|-----------|-------------|------------|-------------|-------------|
| Patient | `patient` | No | No | No | Own chart |
| Records / PA staff | `staff` | Yes | Check only | No | Yes |
| Resident | `resident` | Yes | Check only | No | Yes |
| Senior clinician | `senior_clinician` | Yes | Yes | Yes | Yes |
| Facility admin | `admin` | Yes | Yes | Yes | Yes |

Capabilities from `roleContext.tsx` (`canPrepare`, `canAdjudicate`, …). Server RBAC is authoritative; UI hides/disables actions for clarity.

## 5. Screen briefs

### Today (`Dashboard.tsx`)

- Care insights (agent-labeled in plain language)
- Worklist lanes: review / docs / queued
- Ops pulse: packet cycle median when available
- Jump-to-patient by id/name

### Patients (`Patients.tsx`)

- Search by PAT-ID, name, condition
- Opens chart; patient tokens see self-only list

### Patient chart (`PatientDetail.tsx`)

- Sticky essentials (age/sex/DOB)
- Lifelong history, timeline, documents
- **Prepare packet** → readiness gaps + handoff
- Visit note deep-links with prepare query params

### Reviews (`Authorization.tsx`)

- Case queue by lifecycle status
- Interactive review; senior resume (acknowledge / needs documentation)
- Progress copy: plain language (not pipeline jargon)
- Agent trace + supporting excerpts disclosure

### Visit note (`OpdIngest.tsx`)

- Manual HIS-style packet + optional FHIR R4 import tab
- Requires synthetic + consent attestation flags in payload
- Links onward to chart / review

### My record (`MyRecord.tsx`)

- Patient-bound lifelong view; set linked PAT-ID when role is patient

## 6. API client (`api.ts`)

- Caches `dev-jwt` access token; remints on role / patient / org change
- Care-team mints include `org_code` (default `ORG-000001`) so `ENFORCE_ORG_SCOPE` demos work
- Maps `RBAC_*`, `OIDC_*`, `ORG_SCOPE_*` to clinician-friendly messages
- Shared types for worklist, insights, packet, review payloads

## 7. Accessibility & UX rules

- Skip link to `#main-content`
- Role/facility selects have `aria-label` / `sr-only` labels
- Prefer plain-language labels (`labels.ts`) over raw agent/enum codes
- Error banners show friendly text; never dump raw “have=/need=” RBAC strings

## 8. Build & gate

```bash
cd frontend && npm run build
# or
make launch-check   # pytest + frontend build
```

Stakeholder demo path: [LAUNCH.md](LAUNCH.md) · `make demo-up && make demo-gate`.

## 9. Non-goals (UI)

- Not a full EHR / CPOE
- Not production SSO chrome (role switcher is **demo/pilot** impersonation; production uses OIDC without local role mint)
- Not payer submission UI

## Related source

| File | Role |
|------|------|
| `frontend/src/App.tsx` | Shell + routes |
| `frontend/src/roleContext.tsx` | Desk identity |
| `frontend/src/api.ts` | HTTP + token |
| `frontend/src/pages/*` | Screens |
| `frontend/src/components/*` | Help, agent trace |
| `frontend/src/labels.ts` | Display names |
