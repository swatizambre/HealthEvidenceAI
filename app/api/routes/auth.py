"""Authentication helper routes."""

from fastapi import APIRouter, Request

from app.auth.oidc import mint_dev_jwt, oidc_configuration_status
from app.auth.patient_scope import linked_patient_id
from app.auth.rbac import ROLE_PATIENT, normalize_roles, principal_roles
from app.core.exceptions import AppError
from app.schemas.api import AuthMeResponse, DevTokenRequest, DevTokenResponse, OidcStatusResponse

router = APIRouter(prefix="/auth", tags=["auth"])


@router.post("/dev-token", response_model=DevTokenResponse)
def issue_dev_token(payload: DevTokenRequest, request: Request) -> DevTokenResponse:
    settings = request.app.state.settings
    # Laptop UAT only — never OIDC, staging, or production (see Settings.dev_token_allowed).
    if not settings.dev_token_allowed():
        raise AppError(
            "AUTH_DEV_TOKEN_DISABLED",
            "Development token minting is disabled for this environment or auth mode.",
            403,
        )
    roles = sorted(normalize_roles(payload.roles)) or ["staff"]
    patient_id = payload.patient_id
    if ROLE_PATIENT in roles and not patient_id:
        raise AppError(
            "PATIENT_LINK_REQUIRED",
            "Patient role tokens must include patient_id (e.g. PAT-000001).",
            400,
        )
    if patient_id and ROLE_PATIENT not in roles:
        # Care-team tokens may omit patient binding; strip accidental claim.
        patient_id = None
    token = mint_dev_jwt(
        subject=payload.subject if ROLE_PATIENT not in roles else (patient_id or payload.subject),
        roles=roles,
        audience=settings.oidc_audience or "healthevidence-api",
        secret=settings.require_dev_jwt_secret(),
        patient_id=patient_id,
        org_id=payload.org_id,
        org_code=payload.org_code,
    )
    return DevTokenResponse(
        access_token=token,
        auth_mode="dev-jwt",
        roles=roles,
        patient_id=patient_id,
        org_id=payload.org_id,
        org_code=(payload.org_code.strip().upper() if payload.org_code else None),
    )


@router.get("/me", response_model=AuthMeResponse)
def auth_me(request: Request) -> AuthMeResponse:
    settings = request.app.state.settings
    principal = getattr(request.state, "principal", None)
    mode = settings.auth_mode.strip().lower()
    demo = settings.dev_token_allowed()
    scope_on = settings.org_scope_enforced()
    if principal is None:
        return AuthMeResponse(
            subject="anonymous",
            email="",
            roles=[],
            product_roles=[],
            auth_mode=mode or "none",
            patient_id=None,
            org_id=None,
            org_code=None,
            demo_signin_allowed=demo,
            enforce_org_scope=scope_on,
        )
    product = sorted(principal_roles(principal))
    return AuthMeResponse(
        subject=principal.subject,
        email=principal.email,
        roles=list(principal.roles),
        product_roles=product,
        auth_mode=mode,
        patient_id=linked_patient_id(principal),
        org_id=principal.org_id,
        org_code=principal.org_code,
        demo_signin_allowed=demo,
        enforce_org_scope=scope_on,
    )


@router.get("/capabilities")
def auth_capabilities(request: Request) -> dict[str, object]:
    """Public desk chrome flags — no bearer required."""
    from app.services.ai_scope import describe_ai_scope

    settings = request.app.state.settings
    return {
        "auth_mode": settings.auth_mode.strip().lower(),
        "demo_signin_allowed": settings.dev_token_allowed(),
        "enforce_org_scope": settings.org_scope_enforced(),
        "docs_exposed": settings.docs_exposed(),
        "ai": describe_ai_scope(settings),
    }


@router.get("/oidc/status", response_model=OidcStatusResponse)
def oidc_status(request: Request, discover: bool = False) -> OidcStatusResponse:
    """Pilot health: whether OIDC / auth mode is configured (no secrets returned).

    Pass discover=true to resolve JWKS from OIDC_ISSUER via OpenID discovery.
    """
    status = oidc_configuration_status(request.app.state.settings, discover=discover)
    return OidcStatusResponse(**status)
