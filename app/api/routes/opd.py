"""Hospital-compatible OPD ingest (manual HIS form + FHIR R4)."""

from fastapi import APIRouter, Depends, Request, Response, status
from sqlalchemy.orm import Session

from app.api.deps import enforce_patient_write, get_db, get_principal, require_any_role
from app.auth.oidc import AuthPrincipal
from app.auth.rbac import ROLES_CHART_WRITE
from app.schemas.api import OpdFhirIngestRequest, OpdIngestRequest, OpdIngestResponse
from app.services.fhir_opd import fhir_bundle_to_opd_request
from app.services.opd_ingest import ingest_opd_packet
from app.services.org_scope import resolve_org_id
from app.services.realtime import publish_desk_event

router = APIRouter(prefix="/opd", tags=["opd"])


def _ingest_org_id(request: Request, db: Session) -> str | None:
    principal = get_principal(request)
    if principal is None:
        return None
    return resolve_org_id(db, principal)


@router.post("/ingest", response_model=OpdIngestResponse)
def create_opd_ingest(
    payload: OpdIngestRequest,
    request: Request,
    response: Response,
    db: Session = Depends(get_db),
    _principal: AuthPrincipal = Depends(require_any_role(*ROLES_CHART_WRITE)),
) -> OpdIngestResponse:
    """Ingest one outpatient visit-note packet (HIS-compatible fields)."""
    scoped = enforce_patient_write(request, payload.patient_id, db)
    if scoped and scoped != payload.patient_id:
        payload = payload.model_copy(update={"patient_id": scoped})
    elif scoped and not payload.patient_id:
        payload = payload.model_copy(update={"patient_id": scoped})
    org_id = _ingest_org_id(request, db)
    result = ingest_opd_packet(db, payload, org_id=org_id)
    response.status_code = status.HTTP_201_CREATED if result.created else status.HTTP_200_OK
    principal = get_principal(request)
    actor = getattr(principal, "subject", None) if principal else "care-team"
    publish_desk_event(
        "visit_note_saved",
        org_id=org_id,
        case_id=result.case_id,
        patient_id=result.patient_id,
        actor=str(actor or "care-team"),
        created=result.created,
    )
    return result


@router.post("/ingest/fhir", response_model=OpdIngestResponse)
def create_opd_ingest_fhir(
    payload: OpdFhirIngestRequest,
    request: Request,
    response: Response,
    db: Session = Depends(get_db),
    _principal: AuthPrincipal = Depends(require_any_role(*ROLES_CHART_WRITE)),
) -> OpdIngestResponse:
    """Ingest a FHIR R4 Bundle mapped from hospital EHR export or interface engine."""
    mapped = fhir_bundle_to_opd_request(payload)
    scoped = enforce_patient_write(request, mapped.patient_id, db)
    if scoped:
        mapped = mapped.model_copy(update={"patient_id": scoped})
    org_id = _ingest_org_id(request, db)
    result = ingest_opd_packet(db, mapped, org_id=org_id)
    response.status_code = status.HTTP_201_CREATED if result.created else status.HTTP_200_OK
    actor = getattr(get_principal(request), "subject", None) if get_principal(request) else "care-team"
    publish_desk_event(
        "visit_note_saved",
        org_id=org_id,
        case_id=result.case_id,
        patient_id=getattr(result, "patient_id", None) or mapped.patient_id,
        actor=str(actor or "care-team"),
        created=result.created,
        source="fhir",
    )
    return result

