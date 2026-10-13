"""Hospital interface pipeline: inbound visit → chart → optional evidence pack → desk push.



Synthetic / practice feeds only until PHI program gates are attested.

Runs are persisted so status survives process restart.

"""



from __future__ import annotations

import time
from dataclasses import asdict, dataclass, field
from datetime import UTC, datetime
from threading import Lock
from typing import Any, Literal
from uuid import uuid4

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.safety import DISCLAIMER
from app.models import HospitalPipelineRunRow
from app.schemas.api import OpdFhirIngestRequest, OpdIngestRequest, PacketPrepareRequest
from app.services.fhir_opd import fhir_bundle_to_opd_request
from app.services.opd_ingest import ingest_opd_packet
from app.services.packet_prep import prepare_evidence_packet
from app.services.realtime import publish_desk_event


@dataclass

class PipelineRun:

    run_id: str

    status: Literal["ok", "error"]

    source: str

    patient_id: str | None = None

    case_id: str | None = None

    encounter_id: str | None = None

    ingest_id: str | None = None

    readiness_percent: int | None = None

    gap_count: int | None = None

    auto_prepared: bool = False

    detail: str = ""

    ts: float = field(default_factory=time.time)

    org_id: str | None = None

    actor: str = ""



    def as_dict(self) -> dict[str, Any]:

        return asdict(self)





_LOCK = Lock()

_RUNS: list[PipelineRun] = []

_MAX_RUNS = 50





def _remember_memory(run: PipelineRun) -> None:

    with _LOCK:

        _RUNS.insert(0, run)

        del _RUNS[_MAX_RUNS:]





def _persist(session: Session, run: PipelineRun) -> None:

    row = HospitalPipelineRunRow(

        run_id=run.run_id,

        status=run.status,

        source=run.source,

        patient_id=run.patient_id,

        case_id=run.case_id,

        encounter_id=run.encounter_id,

        ingest_id=run.ingest_id,

        readiness_percent=run.readiness_percent,

        gap_count=run.gap_count,

        auto_prepared=run.auto_prepared,

        detail=(run.detail or "")[:500],

        org_id=run.org_id,

        actor=(run.actor or "")[:120],

    )

    session.add(row)

    session.flush()

    _remember_memory(run)





def _row_to_run(row: HospitalPipelineRunRow) -> PipelineRun:

    ts = row.created_at.timestamp() if row.created_at else time.time()

    return PipelineRun(

        run_id=row.run_id,

        status="ok" if row.status == "ok" else "error",

        source=row.source or "",

        patient_id=row.patient_id,

        case_id=row.case_id,

        encounter_id=row.encounter_id,

        ingest_id=row.ingest_id,

        readiness_percent=row.readiness_percent,

        gap_count=row.gap_count,

        auto_prepared=bool(row.auto_prepared),

        detail=row.detail or "",

        ts=ts,

        org_id=row.org_id,

        actor=row.actor or "",

    )





def recent_runs(session: Session | None = None, limit: int = 20) -> list[PipelineRun]:

    limit = max(1, min(limit, _MAX_RUNS))

    if session is not None:

        rows = list(

            session.scalars(

                select(HospitalPipelineRunRow)

                .order_by(HospitalPipelineRunRow.created_at.desc())

                .limit(limit)

            ).all()

        )

        if rows:

            return [_row_to_run(row) for row in rows]

    with _LOCK:

        return list(_RUNS[:limit])





def pipeline_status(session: Session | None = None) -> dict[str, Any]:

    from app.core.config import get_settings
    from app.services.ai_scope import describe_ai_scope



    settings = get_settings()

    practice = settings.hospital_practice_mode()

    runs = recent_runs(session, 10)

    ok = sum(1 for item in runs if item.status == "ok")

    return {

        "pipeline": "hospital_interface",

        "mode": "synthetic_practice" if practice else "production_phi",

        "realtime": True,

        "auto_prepare_supported": True,

        "simulate_allowed": settings.hospital_simulate_allowed(),

        "phi_live": not practice,

        "ai": describe_ai_scope(settings),

        "recent_ok": ok,

        "recent_total": len(runs),

        "runs": [item.as_dict() for item in runs],

        "disclaimer": DISCLAIMER,

    }





def run_his_visit(

    session: Session,

    payload: OpdIngestRequest,

    *,

    org_id: str | None = None,

    actor: str = "hospital-interface",

    auto_prepare: bool = True,

) -> dict[str, Any]:

    """Ingest a HIS/OPD visit packet and optionally prepare the evidence pack."""

    run_id = str(uuid4())

    try:

        ingest = ingest_opd_packet(session, payload, org_id=org_id, actor=actor)

        readiness: int | None = None

        gaps: int | None = None

        prepared = False

        case_id = ingest.case_id

        if auto_prepare and payload.policy_id:

            packet = prepare_evidence_packet(

                session,

                PacketPrepareRequest(

                    patient_id=ingest.patient_id,

                    policy_id=payload.policy_id,

                    procedure=payload.procedure,

                    case_id=ingest.case_id,

                ),

            )

            readiness = packet.readiness_percent

            gaps = packet.gap_count

            case_id = packet.case_id

            prepared = True

            publish_desk_event(

                "evidence_pack_prepare",

                org_id=org_id,

                case_id=case_id,

                patient_id=ingest.patient_id,

                actor=actor,

                readiness_percent=readiness,

                via="hospital_pipeline",

            )

        publish_desk_event(

            "hospital_visit_received",

            org_id=org_id,

            case_id=case_id,

            patient_id=ingest.patient_id,

            actor=actor,

            encounter_id=ingest.encounter_id,

            source=ingest.source,

            auto_prepared=prepared,

        )

        run = PipelineRun(

            run_id=run_id,

            status="ok",

            source=ingest.source,

            patient_id=ingest.patient_id,

            case_id=case_id,

            encounter_id=ingest.encounter_id,

            ingest_id=ingest.ingest_id,

            readiness_percent=readiness,

            gap_count=gaps,

            auto_prepared=prepared,

            detail="Visit landed on chart" + (" · evidence pack refreshed" if prepared else ""),

            org_id=org_id,

            actor=actor,

        )

        _persist(session, run)

        return {

            **run.as_dict(),

            "document_ids": ingest.document_ids,

            "created": ingest.created,

            "disclaimer": DISCLAIMER,

        }

    except Exception as exc:

        run = PipelineRun(

            run_id=run_id,

            status="error",

            source=str(getattr(payload, "source", None) or "his_export"),

            detail=str(exc)[:300],

            org_id=org_id,

            actor=actor,

        )

        try:

            _persist(session, run)

        except Exception:

            _remember_memory(run)

        raise





def run_fhir_visit(

    session: Session,

    payload: OpdFhirIngestRequest,

    *,

    org_id: str | None = None,

    actor: str = "hospital-interface",

    auto_prepare: bool = True,

) -> dict[str, Any]:

    mapped = fhir_bundle_to_opd_request(payload)

    return run_his_visit(

        session,

        mapped,

        org_id=org_id,

        actor=actor,

        auto_prepare=auto_prepare,

    )





def simulate_visit(

    session: Session,

    *,

    patient_id: str = "PAT-000001",

    policy_id: str = "POL-000001",

    org_id: str | None = None,

    actor: str = "hospital-simulator",

) -> dict[str, Any]:

    """Deterministic practice feed for verifying the live desk pipeline."""

    from app.core.config import get_settings
    from app.core.exceptions import AppError



    settings = get_settings()

    if not settings.hospital_simulate_allowed():

        raise AppError(

            "HOSPITAL_SIMULATE_DISABLED",

            "Hospital visit simulator is disabled in this environment. "

            "Use HIS/FHIR webhooks, or enable HOSPITAL_ALLOW_SIMULATE only on practice desks.",

            403,

        )

    stamp = datetime.now(UTC).strftime("%Y%m%d%H%M%S")

    payload = OpdIngestRequest.model_validate(

        {

            "external_patient_id": f"UHID-SIM-{stamp[-6:]}",

            "encounter_id": f"OPD-SIM-{stamp}",

            "patient_id": patient_id,

            "facility_name": "OPD — Krishna Multispecialty Hospital",

            "department": "General medicine",

            "attending_provider": "Dr Interface",

            "chief_complaint": "Follow-up hypertension",

            "note": (

                "Hospital interface simulator visit. "

                "Blood pressure controlled on amlodipine. Continue current therapy."

            ),

            "labs": [{"test_name": "HbA1c", "value": "6.7", "unit": "%"}],

            "medications": [{"name": "Amlodipine 5mg", "status": "active"}],

            "procedure": "Evidence pack documentation",

            "policy_id": policy_id,

            "source": "his_export",

            "synthetic": True,

            "consent_attested": True,

        }

    )

    return run_his_visit(

        session,

        payload,

        org_id=org_id,

        actor=actor,

        auto_prepare=True,

    )


