# HealthEvidence AI

**Promise:** Your lifelong health record that keeps every doctor, anywhere, from giving you the wrong medicine.

**What it is for (product focus):** a **patient-owned lifelong health record** with an emergency card and a **doctor AI view** (brief, risk flags, medicines with sources). The **India cashless / TPA insurance desk** is a later hospital (B2B) module already present in this repo.

**Intended use:** Organises and shows records with sources. **Does not diagnose, prescribe, approve, or deny care.** Not a medical device.

It is a **safety-conscious prototype**, not a “perfect model.” Default evidence checking is **mostly deterministic rules** (keyword/lab matching, negation, units). Optional AI runs when configured; cloud models are blocked for real PHI without attestation. Desk copy labels **rule check** vs **AI check** honestly.

1. **Patients** own **My record**: timeline, emergency card, share-with-doctor, family/caregiver stubs, visit notes from any facility.
2. **Any clinician** opens a 30-second brief with sources, risk flags, and medicine reconciliation — continuity of care.
3. **Records / PA staff** (hospital module) prepare cashless / TPA evidence packets when needed.
4. **Seniors** final-acknowledge Reviews; residents may check evidence but not final-sign.
5. **Visit notes** tag hospital + department so new care joins the lifelong chart.

**It does not approve, deny, diagnose, or submit prior auth to a payer.** Clinical data arrives when staff type notes, paste FHIR, or use synthetic seed — there is no live EHR/HIS/ABDM feed yet (ABDM sandbox stubs only). See [docs/PRODUCT_ROADMAP.md](docs/PRODUCT_ROADMAP.md).

Designed for **clinic → multispecialty → super-specialty → government/teaching** facilities. Set Facility + Role in the top bar — small clinics may switch hats; teaching hospitals keep resident draft / senior sign-off.

**Multi-specialty digital file:** visit notes and chart filters cover hospital departments including cardiology, ortho, oncology, OB/GYN, neurology, urology, surgery, and supporting labs/imaging/pharmacy.

**Practice path (any facility):**

| Role | Correct path |
|------|----------------|
| **Records / PA staff** | Patients → sticky banner (age/sex/DOB) → essentials → Prepare packet → Visit note gaps → handoff. |
| **Senior clinician** | Today → Reviews → Check evidence → acknowledge or send back. Visit note only if they document it. |
| **Resident / junior doctor** | Chart → packet → visit notes → may check evidence; escalate HITL to senior. |
| **Patient** | My record → lifelong history → Add visit note from any hospital |

**RBAC:** JWT roles `patient`, `staff`, `resident`, `senior_clinician`, `admin`. HITL resume = senior/admin only. Visit note = patient/staff/resident/senior. Packet prepare = staff/resident/senior. Legacy `reviewer` → senior.

Prepare packet never auto-acks clinician HITL. Visit note requires synthetic/consent attestation. Review runs persist for pause/resume. Help chat refuses coverage/diagnosis language. Ops metric: packet cycle time on Today and `GET /api/v1/metrics/ops`.

**Not for clinical use or diagnosis. Not a medical device.** Synthetic / consent-gated demo data only. Live PHI requires `ALLOW_PHI` + `PHI_PROGRAM_ATTESTED` under an accountable program.

## Who this is for (sales)

Sell as **lifelong patient record + doctor continuity view** first — never as an approval engine or clinical AI. Hospital cashless / TPA desk is the later B2B add-on. Be explicit that default checklist scoring is rule-based.

| Buyer | Why they buy |
|-------|----------------|
| **Patients & caregivers** | One chart across PHC → city hospital; emergency card; share with any doctor |
| **Emergency / GP / specialists** | Seconds to history, allergy flags, medicine list with sources |
| Hospital / health-system **PA coordinators & RCM** (later module) | Cut chart chase time before cashless submission |
| Health systems preparing for **ABDM / CMS FHIR ePA** | Consent-linked record pull + evidence assembly |

Start with patient + doctor pilot; add TPA desk once verified packets matter to admissions.

## Architecture

```mermaid
flowchart TD
  UI[React_UI] --> API[FastAPI]
  API --> Auth[OIDC_JWT]
  API --> Orch[LangGraph]
  Orch --> Pol[PolicyAgent]
  Orch --> Clin[ClinicalEvidenceAgent]
  Orch --> Ver[EvidenceVerifier]
  Orch --> Img[ImagingAgent]
  Pol --> MCP[MCP_Client]
  Clin --> MCP
  Ver --> MCP
  Img --> A2A[A2A_Bus]
  A2A --> MONAI[MONAI_Imaging]
  MCP --> Tools[MCP_Server]
  Tools --> Perm[Permissions]
  Perm --> Dom[Domain_Services]
  Dom --> RAG[Hybrid_RAG]
  Dom --> DB[(PostgreSQL)]
  Orch --> LLM[LLM_Providers]
  Orch --> HITL[Human_Review]
  Orch --> Obs[Observability]
```

Source diagram: [docs/architecture.mmd](docs/architecture.mmd)

## Stack

- **API:** FastAPI, SQLAlchemy, PostgreSQL (SQLite for local development)
- **Agents:** LangGraph orchestration, MCP tools, A2A messaging
- **RAG:** Dense + lexical retrieval, RRF fusion, reranking, citation preservation
- **LLM:** OpenAI, Anthropic, Gemini (Google GenAI `generateContent`), or Ollama (`/api/chat`) via `LLM_PROVIDER` — each keeps its own model env var (`GEMINI_MODEL_NAME` / `OLLAMA_MODEL_NAME`)
- **Imaging:** MONAI-isolated analysis path (non-diagnostic)
- **Auth:** OIDC in production; development JWT for local environments
- **UI:** React, TypeScript, Vite
- **Ops:** Docker Compose, Kubernetes manifests, evaluation suites

## Quick start

```bash
uv sync
cp .env.example .env
# Configure LLM_PROVIDER (local | ollama | openai | anthropic | gemini) and credentials as needed
# local = always-on grounded phrasing (pipeline runnable without a cloud/daemon LLM)

uv run python -m uvicorn app.main:app --reload --host 127.0.0.1 --port 8010
```

```bash
cd frontend && npm ci && npm run dev -- --host 127.0.0.1 --port 5173
```

Open [http://127.0.0.1:5173](http://127.0.0.1:5173) (Vite proxies `/api` → `8010`).

```bash
# Local / demo (your .env DATABASE_URL)
docker compose up --build

# Sales demo on Postgres + synthetic seed (needs DEV_JWT_SECRET ≥32 chars)
export DEV_JWT_SECRET="$(openssl rand -hex 24)"
docker compose -f docker-compose.yml -f docker-compose.pilot.yml -f docker-compose.demo.yml up --build

make launch-check
make demo
make test
make eval-rag
make eval-agent
make eval-gold   # clinical-safety gate (false-SUPPORTED); see evaluation/gold/
```

Paths: **Demo** vs **Pilot** vs staging — see [docs/LAUNCH.md](docs/LAUNCH.md) and [docs/PILOT_ROADMAP.md](docs/PILOT_ROADMAP.md).

## Configuration

See [`.env.example`](.env.example). Production and staging require:

- `AUTH_MODE=oidc` with issuer and JWKS URL
- Live `LLM_PROVIDER` with reachable credentials or Ollama
- `IMAGING_BACKEND=monai`
- PostgreSQL (`DATABASE_URL` must not use SQLite)

## Safety

Outputs are decision-support drafts over configured datasets. The system does not approve care, deny care, diagnose, or prescribe. Human review is required when evidence is missing or contradictory.

## Documentation

**Start here:** [docs/INDEX.md](docs/INDEX.md)

### Design

- [High-level design (HLD)](docs/HLD.md)
- [Low-level design (LLD)](docs/LLD.md)
- [Sequence flows](docs/SEQUENCE_FLOWS.md)
- [API overview](docs/API_OVERVIEW.md)
- [Data model](docs/DATA_MODEL.md)
- [Security design](docs/SECURITY_DESIGN.md)
- [Deployment design](docs/DEPLOYMENT.md)
- [Web UI design](docs/WEB_UI.md)
- [Architecture diagram](docs/architecture.mmd)

### Run / launch

- [Launch (demo vs pilot)](docs/LAUNCH.md)
- [Operations](docs/operations.md)
- [Kubernetes](docs/kubernetes.md)
- [OIDC pilot IdP wiring](docs/OIDC_PILOT.md)

### Roadmaps / gates

- [Pilot → production → demo roadmap](docs/PILOT_ROADMAP.md)
- [AI scope (hybrid decision-support)](docs/AI_SCOPE.md)
- [Live-ready go-live runbook](docs/LIVE_READY.md)
- [Production checklist](docs/PRODUCTION_CHECKLIST.md)
- [Safety and compliance notes](docs/clinical-product-roadmap.md)
- [Patient data privacy](docs/data-privacy.md)
- [OPD patient-wise ingest roadmap](docs/opd-ingest-roadmap.md)
- [Contributing](CONTRIBUTING.md)
- [Security](SECURITY.md)

## License

MIT. See [LICENSE](LICENSE).
