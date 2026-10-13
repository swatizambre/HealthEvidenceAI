"""Production-style OIDC JWT validation and role checks."""

from __future__ import annotations

import time
from dataclasses import dataclass
from typing import Any

import httpx
import jwt
from jwt import PyJWKClient

from app.core.config import Settings
from app.core.exceptions import AppError


@dataclass(frozen=True)
class AuthPrincipal:
    subject: str
    email: str
    roles: tuple[str, ...]
    raw_claims: dict[str, Any]
    patient_id: str | None = None
    org_id: str | None = None
    org_code: str | None = None


_JWKS_CLIENTS: dict[str, PyJWKClient] = {}


def _patient_id_from_claims(claims: dict[str, Any]) -> str | None:
    import re

    pattern = re.compile(r"^PAT-\d{6}$")
    for key in ("patient_id", "healthevidence_patient_id", "linked_patient_id"):
        raw = claims.get(key)
        if isinstance(raw, str) and pattern.fullmatch(raw.strip().upper()):
            return raw.strip().upper()
    sub = str(claims.get("sub") or "")
    if pattern.fullmatch(sub.strip().upper()):
        return sub.strip().upper()
    return None


def _org_from_claims(claims: dict[str, Any]) -> tuple[str | None, str | None]:
    """Return (org_id, org_code) from common IdP claim shapes."""
    import re

    org_code_pat = re.compile(r"^ORG-\d{6}$", re.I)
    org_id = None
    org_code = None
    for key in ("org_id", "organization_id", "healthevidence_org_id"):
        raw = claims.get(key)
        if isinstance(raw, str) and raw.strip():
            org_id = raw.strip()
            break
    for key in ("org_code", "organization_code", "facility_code", "healthevidence_org_code"):
        raw = claims.get(key)
        if isinstance(raw, str) and raw.strip():
            value = raw.strip().upper()
            org_code = value if org_code_pat.fullmatch(value) or value.startswith("ORG-") else value
            break
    return org_id, org_code


def _jwks_client(settings: Settings) -> PyJWKClient:
    url = settings.oidc_jwks_url.strip()
    if not url:
        raise AppError("OIDC_MISCONFIGURED", "OIDC_JWKS_URL is required when AUTH_MODE=oidc.", 503)
    client = _JWKS_CLIENTS.get(url)
    if client is None:
        client = PyJWKClient(url, cache_keys=True)
        _JWKS_CLIENTS[url] = client
    return client


def extract_roles(claims: dict[str, Any], settings: Settings) -> tuple[str, ...]:
    """Collect IdP role strings from common claim shapes (Keycloak, Entra, Auth0)."""
    roles: list[str] = []
    claim = settings.oidc_roles_claim
    raw = claims.get(claim)
    if isinstance(raw, list):
        roles.extend(str(item) for item in raw)
    elif isinstance(raw, str) and raw.strip():
        roles.extend(part.strip() for part in raw.split(",") if part.strip())
    # Keycloak realm roles
    realm = claims.get("realm_access")
    if isinstance(realm, dict):
        realm_roles = realm.get("roles")
        if isinstance(realm_roles, list):
            roles.extend(str(item) for item in realm_roles)
    # Keycloak / some IdPs: resource_access.<client>.roles
    resource = claims.get("resource_access")
    if isinstance(resource, dict):
        client_id = (settings.oidc_client_id or "").strip()
        clients = [client_id] if client_id else []
        clients.extend(str(key) for key in resource.keys() if str(key) not in clients)
        for client in clients:
            block = resource.get(client)
            if isinstance(block, dict):
                client_roles = block.get("roles")
                if isinstance(client_roles, list):
                    roles.extend(str(item) for item in client_roles)
    # Azure AD app roles
    app_roles = claims.get("roles")
    if isinstance(app_roles, list) and claim != "roles":
        roles.extend(str(item) for item in app_roles)
    return tuple(sorted(set(roles)))


def validate_bearer_token(token: str, settings: Settings) -> AuthPrincipal:
    if settings.auth_mode.strip().lower() == "dev-jwt":
        return _validate_dev_jwt(token, settings)
    return _validate_oidc_jwt(token, settings)


def _validate_oidc_jwt(token: str, settings: Settings) -> AuthPrincipal:
    try:
        signing_key = _jwks_client(settings).get_signing_key_from_jwt(token)
        claims = jwt.decode(
            token,
            signing_key.key,
            algorithms=["RS256", "ES256"],
            audience=settings.oidc_audience or None,
            issuer=settings.oidc_issuer or None,
            options={
                "verify_aud": bool(settings.oidc_audience),
                "verify_iss": bool(settings.oidc_issuer),
            },
        )
    except AppError:
        raise
    except Exception as exc:
        raise AppError("OIDC_UNAUTHORIZED", f"Invalid bearer token: {exc}", 401) from exc
    subject = str(claims.get("sub") or "")
    if not subject:
        raise AppError("OIDC_UNAUTHORIZED", "Token is missing subject.", 401)
    org_id, org_code = _org_from_claims(claims)
    return AuthPrincipal(
        subject=subject,
        email=str(claims.get("email") or ""),
        roles=extract_roles(claims, settings),
        raw_claims=dict(claims),
        patient_id=_patient_id_from_claims(claims),
        org_id=org_id,
        org_code=org_code,
    )


def _validate_dev_jwt(token: str, settings: Settings) -> AuthPrincipal:
    """HS256 local tokens for demos without an IdP (AUTH_MODE=dev-jwt)."""
    try:
        claims = jwt.decode(
            token,
            settings.require_dev_jwt_secret(),
            algorithms=["HS256"],
            audience=settings.oidc_audience or "healthevidence-api",
            options={"verify_aud": True},
        )
    except Exception as exc:
        raise AppError("OIDC_UNAUTHORIZED", f"Invalid development JWT: {exc}", 401) from exc
    subject = str(claims.get("sub") or "dev-user")
    org_id, org_code = _org_from_claims(claims)
    return AuthPrincipal(
        subject=subject,
        email=str(claims.get("email") or "dev@example.com"),
        roles=extract_roles(claims, settings) or ("reviewer",),
        raw_claims=dict(claims),
        patient_id=_patient_id_from_claims(claims),
        org_id=org_id,
        org_code=org_code,
    )


def mint_dev_jwt(
    *,
    subject: str = "dev-user",
    roles: list[str] | None = None,
    audience: str = "healthevidence-api",
    secret: str | None = None,
    ttl_seconds: int = 3600,
    patient_id: str | None = None,
    org_id: str | None = None,
    org_code: str | None = None,
) -> str:
    now = int(time.time())
    payload: dict[str, Any] = {
        "sub": subject,
        "email": f"{subject}@example.com",
        "roles": roles or ["reviewer"],
        "aud": audience,
        "iat": now,
        "exp": now + ttl_seconds,
    }
    if patient_id:
        code = patient_id.strip().upper()
        payload["patient_id"] = code
    if org_id:
        payload["org_id"] = org_id.strip()
    if org_code:
        payload["org_code"] = org_code.strip().upper()
    from app.core.config import get_settings

    signing = (secret or "").strip() or get_settings().require_dev_jwt_secret()
    return jwt.encode(payload, signing, algorithm="HS256")


def require_role(principal: AuthPrincipal, allowed: set[str]) -> None:
    if not allowed:
        return
    have = set(principal.roles)
    # Accept product aliases so legacy "reviewer" config does not block staff/senior desks.
    from app.auth.rbac import normalize_roles

    if allowed.intersection(have):
        return
    if normalize_roles(tuple(allowed)).intersection(normalize_roles(principal.roles)):
        return
    raise AppError(
        "OIDC_FORBIDDEN",
        "This signed-in role cannot access that action.",
        403,
    )


def fetch_openid_configuration(issuer: str) -> dict[str, Any]:
    url = issuer.rstrip("/") + "/.well-known/openid-configuration"
    response = httpx.get(url, timeout=10.0)
    response.raise_for_status()
    payload = response.json()
    if not isinstance(payload, dict):
        raise AppError("OIDC_MISCONFIGURED", "Invalid OpenID configuration document.", 503)
    return payload


def discover_oidc_endpoints(issuer: str) -> dict[str, str]:
    """Resolve issuer → JWKS URL (and token endpoint) from OpenID discovery."""
    doc = fetch_openid_configuration(issuer)
    jwks = str(doc.get("jwks_uri") or "").strip()
    if not jwks:
        raise AppError(
            "OIDC_MISCONFIGURED",
            "OpenID configuration is missing jwks_uri.",
            503,
        )
    return {
        "issuer": str(doc.get("issuer") or issuer).rstrip("/"),
        "jwks_url": jwks,
        "token_endpoint": str(doc.get("token_endpoint") or ""),
        "authorization_endpoint": str(doc.get("authorization_endpoint") or ""),
    }


def oidc_configuration_status(
    settings: Settings,
    *,
    discover: bool = False,
) -> dict[str, Any]:
    """Pilot/ops snapshot — optionally probe IdP discovery when issuer is set."""
    mode = settings.auth_mode.strip().lower()
    issuer = settings.oidc_issuer.strip()
    jwks = settings.oidc_jwks_url.strip()
    ready = False
    detail = ""
    discovery: dict[str, str] = {}
    if mode == "dev-jwt":
        ready = True
        detail = "Local development JWT minting enabled."
    elif mode == "oidc":
        if issuer and jwks:
            ready = True
            detail = "OIDC issuer and JWKS URL configured."
        elif issuer and discover:
            try:
                discovery = discover_oidc_endpoints(issuer)
                jwks = discovery["jwks_url"]
                ready = True
                detail = "JWKS resolved via OpenID discovery."
            except Exception as exc:  # noqa: BLE001 — surface IdP reachability to ops
                detail = f"Discovery failed: {exc}"
        else:
            detail = "Set OIDC_ISSUER and OIDC_JWKS_URL for AUTH_MODE=oidc."
    else:
        detail = f"AUTH_MODE={mode or 'none'}"
    return {
        "auth_mode": mode or "none",
        "oidc_ready": ready and mode == "oidc",
        "issuer_configured": bool(issuer),
        "jwks_configured": bool(jwks or settings.oidc_jwks_url.strip()),
        "audience": settings.oidc_audience or "",
        "roles_claim": settings.oidc_roles_claim or "roles",
        "client_id_configured": bool(settings.oidc_client_id.strip()),
        "detail": detail,
        "discovered_jwks_url": discovery.get("jwks_url", ""),
        "discovered_issuer": discovery.get("issuer", ""),
    }
