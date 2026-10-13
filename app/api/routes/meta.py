"""Dashboard counts, clinician worklist, specialty catalog, and ops metrics."""

from fastapi import APIRouter, Depends, Request
from pydantic import BaseModel, ConfigDict
from sqlalchemy.orm import Session

from app.api.deps import get_db, get_principal, require_care_team
from app.auth.oidc import AuthPrincipal
from app.core.config import get_settings
from app.core.safety import DISCLAIMER
from app.schemas.api import (
    DeskInsightsResponse,
    OpsMetricsResponse,
    OrganizationListResponse,
    OrganizationOut,
    PacketCycleMetricsOut,
    StatsResponse,
    WorklistResponse,
)
from app.services.cycle_time import packet_ops_metrics
from app.services.india_desk import describe_india_desk, facility_catalog
from app.services.insights import desk_insights
from app.services.org_scope import care_team_org_filter_id
from app.services.organizations import list_organizations
from app.services.records import clinician_worklist, system_stats
from app.services.specialties import SPECIALTY_CATALOG

router = APIRouter(tags=["meta"])


class SpecialtyListResponse(BaseModel):
    model_config = ConfigDict(extra="ignore")
    specialties: list[str]


class FacilityTypeOut(BaseModel):
    model_config = ConfigDict(extra="ignore")
    id: str
    label: str
    tier: str
    hint: str


class FacilityCatalogResponse(BaseModel):
    model_config = ConfigDict(extra="ignore")
    market: str = "india"
    facilities: list[FacilityTypeOut]
    referral_ladder: list[str] = []
    payer_language: str = ""
    disclaimer: str = ""


def _org_filter(request: Request, db: Session) -> str | None:
    return care_team_org_filter_id(db, get_principal(request))


@router.get("/stats", response_model=StatsResponse)
def stats(
    request: Request,
    db: Session = Depends(get_db),
    _principal: AuthPrincipal = Depends(require_care_team()),
) -> StatsResponse:
    return system_stats(db, org_id=_org_filter(request, db))


@router.get("/worklist", response_model=WorklistResponse)
def worklist(
    request: Request,
    db: Session = Depends(get_db),
    _principal: AuthPrincipal = Depends(require_care_team()),
) -> WorklistResponse:
    """Today queue for clinicians: recent patients and open review cases."""
    principal = get_principal(request)
    subject = getattr(principal, "subject", None) if principal else None
    return clinician_worklist(
        db,
        org_id=_org_filter(request, db),
        assignee_subject=str(subject) if subject else None,
    )


@router.get("/insights", response_model=DeskInsightsResponse)
def insights(
    request: Request,
    db: Session = Depends(get_db),
    _principal: AuthPrincipal = Depends(require_care_team()),
) -> DeskInsightsResponse:
    """Proactive AI agent insights for the Today desk."""
    return desk_insights(db, org_id=_org_filter(request, db))


@router.get("/specialties", response_model=SpecialtyListResponse)
def specialties() -> SpecialtyListResponse:
    """Multi-specialty department catalog for encounter tagging and chart filters."""
    return SpecialtyListResponse(specialties=list(SPECIALTY_CATALOG))


@router.get("/facilities", response_model=FacilityCatalogResponse)
def facilities() -> FacilityCatalogResponse:
    """India rural→urban facility taxonomy for desk mode and referral ladder."""
    raw = describe_india_desk()
    return FacilityCatalogResponse(
        market=str(raw["market"]),
        facilities=[FacilityTypeOut.model_validate(item) for item in facility_catalog()],
        referral_ladder=list(raw.get("referral_ladder") or []),
        payer_language=str(raw.get("payer_language") or ""),
        disclaimer=str(raw.get("disclaimer") or DISCLAIMER),
    )


@router.get("/metrics/ops", response_model=OpsMetricsResponse)
def ops_metrics(
    request: Request,
    db: Session = Depends(get_db),
    _principal: AuthPrincipal = Depends(require_care_team()),
) -> OpsMetricsResponse:
    """PA desk ops metrics — packet cycle time (documentation readiness only)."""
    settings = get_settings()
    raw = packet_ops_metrics(db, org_id=_org_filter(request, db))
    orgs = list_organizations(db)
    return OpsMetricsResponse(
        packet_cycle=PacketCycleMetricsOut.model_validate(raw),
        organization_count=len(orgs),
        allow_phi=bool(settings.allow_phi),
        disclaimer=DISCLAIMER,
    )


@router.get("/organizations", response_model=OrganizationListResponse)
def organizations(
    db: Session = Depends(get_db),
    _principal: AuthPrincipal = Depends(require_care_team()),
) -> OrganizationListResponse:
    """List active tenant organizations (facility / health-system stubs)."""
    rows = list_organizations(db)
    return OrganizationListResponse(
        organizations=[
            OrganizationOut(
                org_id=row.id,
                org_code=row.org_code,
                name=row.name,
                facility_type=row.facility_type,
                active=bool(row.active),
            )
            for row in rows
        ]
    )

