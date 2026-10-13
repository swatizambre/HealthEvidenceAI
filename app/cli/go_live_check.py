"""Go-live gate: PASS / FAIL / WARN table for a demo or a real-data trial.

Usage:
  uv run python -m app.cli.go_live_check --mode demo
  uv run python -m app.cli.go_live_check --mode trial
  uv run python -m app.cli.go_live_check --mode trial --offline   # skip IdP network probe

Exits non-zero when any check FAILs. Every check is a pure function of a Settings
object (plus injected probes for DB / IdP) so it can be unit tested.

A green table means the *configuration* matches docs/GO_LIVE.md. It is not clinical,
ethical, legal or security approval — those are signed by people, outside this repo.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from collections.abc import Callable, Iterable
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Literal
from urllib.parse import urlparse

from app.core.config import Settings, get_settings
from app.core.exceptions import AppError

Status = Literal["PASS", "FAIL", "WARN"]
Mode = Literal["demo", "trial"]

CLOUD_LLM_PROVIDERS = frozenset({"openai", "anthropic", "gemini"})
LOCAL_HOSTS = frozenset({"localhost", "127.0.0.1", "0.0.0.0", "::1", "keycloak", "host.docker.internal"})
DEFAULT_GOLD_RESULT = Path("data/gold_gate_result.json")
MIN_SECRET_LENGTH = 32

# probe(database_url) -> (current revisions, head revisions); None when Alembic is not used.
DbProbe = Callable[[str], tuple[set[str], set[str]] | None]
OidcFetcher = Callable[[str], dict[str, str]]


@dataclass(frozen=True)
class CheckResult:
    name: str
    status: Status
    detail: str


def _ok(name: str, detail: str) -> CheckResult:
    return CheckResult(name, "PASS", detail)


def _fail(name: str, detail: str) -> CheckResult:
    return CheckResult(name, "FAIL", detail)


def _warn(name: str, detail: str) -> CheckResult:
    return CheckResult(name, "WARN", detail)


# --- configuration -------------------------------------------------------------------


def check_config_validation(settings: Settings) -> CheckResult:
    name = "config.validate_live_configuration"
    try:
        settings.validate_live_configuration()
    except AppError as exc:
        return _fail(name, f"{exc.error_code}: {exc.message}")
    return _ok(name, f"ENVIRONMENT={settings.env_name()} accepted")


def check_phi_flags_for_trial(settings: Settings) -> CheckResult:
    name = "trial.phi_flags"
    if settings.real_data_mode():
        return _ok(name, "ALLOW_PHI=true and PHI_PROGRAM_ATTESTED=true")
    return _fail(
        name,
        "Real-data trial needs ALLOW_PHI=true and PHI_PROGRAM_ATTESTED=true "
        "(set only after the non-code checklist in docs/GO_LIVE.md is signed)",
    )


def check_trial_attestations(settings: Settings) -> CheckResult:
    """Report every trial requirement, even before the PHI flags are flipped."""
    name = "trial.attestations"
    as_trial = settings.model_copy(update={"allow_phi": True, "phi_program_attested": True})
    problems = as_trial.real_data_trial_problems()
    if problems:
        return _fail(name, "missing: " + "; ".join(problems))
    return _ok(
        name,
        f"site={settings.trial_site_org_code.strip()} until={settings.trial_end_date.strip()} "
        f"region={settings.data_residency_region.strip()}",
    )


def check_dev_token_disabled(settings: Settings) -> CheckResult:
    name = "auth.dev_token_disabled"
    if settings.dev_token_allowed():
        return _fail(name, "/auth/dev-token minting is enabled; real data requires IdP-only sign-in")
    if (os.environ.get("PILOT_POSTGRES_TEST") or "").strip():
        return _fail(name, "PILOT_POSTGRES_TEST is set (CI harness only) — unset it")
    return _ok(name, f"AUTH_MODE={settings.auth_mode.strip().lower()}; dev tokens disabled")


def check_llm_egress(settings: Settings, mode: Mode) -> CheckResult:
    name = "llm.phi_egress"
    cloud = [p for p in settings.llm_provider_chain() if p in CLOUD_LLM_PROVIDERS]
    if not cloud:
        return _ok(name, f"providers={','.join(settings.llm_provider_chain())} (no cloud egress)")
    if mode == "demo":
        return _warn(name, f"cloud providers {','.join(cloud)} — fine for synthetic demo; needs network")
    if not (settings.llm_baa_attested and settings.llm_phi_egress_allowed):
        return _fail(
            name,
            f"cloud providers {','.join(cloud)} without LLM_BAA_ATTESTED + LLM_PHI_EGRESS_ALLOWED",
        )
    return _warn(
        name,
        f"cloud providers {','.join(cloud)} attested — confirm the DPA covers "
        f"{settings.data_residency_region.strip() or 'the data residency region'}",
    )


def check_hospital_keys(settings: Settings, mode: Mode) -> CheckResult:
    name = "hospital.interface_keys"
    if not hasattr(settings, "hospital_interface_keys"):
        return _warn(name, "HOSPITAL_INTERFACE_KEYS not available in this build")
    per_org = str(getattr(settings, "hospital_interface_keys", "") or "").strip()
    shared = settings.hospital_interface_api_key.strip()
    if per_org:
        site = settings.trial_site_org_code.strip().upper()
        if mode == "trial" and site and site not in per_org.upper():
            return _warn(name, f"per-org keys set but none mention TRIAL_SITE_ORG_CODE={site}")
        return _ok(name, "per-org HOSPITAL_INTERFACE_KEYS configured")
    if shared:
        if mode == "trial":
            return _fail(
                name,
                "only the shared HOSPITAL_INTERFACE_API_KEY is set; use per-org "
                "HOSPITAL_INTERFACE_KEYS for real feeds",
            )
        return _warn(name, "shared HOSPITAL_INTERFACE_API_KEY only (acceptable for demo)")
    return _ok(name, "no machine feed configured (manual OPD entry only)")


def check_stream_ticket_secret(settings: Settings, mode: Mode) -> CheckResult:
    name = "realtime.stream_ticket_secret"
    if not hasattr(settings, "stream_ticket_secret"):
        return _warn(name, "STREAM_TICKET_SECRET not available in this build")
    secret = str(getattr(settings, "stream_ticket_secret", "") or "").strip()
    if len(secret) >= MIN_SECRET_LENGTH:
        return _ok(name, "set (length ok)")
    detail = "unset" if not secret else f"shorter than {MIN_SECRET_LENGTH} characters"
    if mode == "trial":
        return _fail(name, f"STREAM_TICKET_SECRET {detail}")
    return _warn(name, f"STREAM_TICKET_SECRET {detail}")


def check_rate_limiting(settings: Settings, mode: Mode) -> CheckResult:
    name = "api.rate_limiting"
    if not hasattr(settings, "rate_limit_enabled"):
        return _warn(name, "RATE_LIMIT_ENABLED not available in this build")
    if bool(getattr(settings, "rate_limit_enabled", False)):
        return _ok(name, "RATE_LIMIT_ENABLED=true")
    if mode == "trial":
        return _fail(name, "RATE_LIMIT_ENABLED is false")
    return _warn(name, "RATE_LIMIT_ENABLED is false")


def check_idp_not_dev(settings: Settings, mode: Mode) -> CheckResult:
    name = "auth.idp_production"
    if settings.auth_mode.strip().lower() != "oidc":
        if mode == "trial":
            return _fail(name, "AUTH_MODE is not oidc")
        return _ok(name, "dev-jwt demo sign-in (no IdP)")
    issuer = settings.oidc_issuer.strip()
    parsed = urlparse(issuer)
    host = (parsed.hostname or "").lower()
    if not issuer:
        return _fail(name, "OIDC_ISSUER is empty")
    if host in LOCAL_HOSTS:
        return _warn(
            name,
            f"OIDC issuer host {host!r} looks like the local start-dev Keycloak "
            "(admin/admin, change-me users) — use the production IdP for a trial",
        )
    if mode == "trial" and parsed.scheme != "https":
        return _fail(name, f"OIDC_ISSUER must use https (got {parsed.scheme or 'no scheme'})")
    return _ok(name, f"issuer host {host}")


def check_synthetic_lifelong(settings: Settings, mode: Mode) -> CheckResult:
    name = "data.synthetic_lifelong"
    enabled = settings.synthetic_lifelong_enabled()
    if mode == "trial":
        if enabled or settings.synthetic_lifelong is True:
            return _fail(name, "invented lifelong biography must be off with real data")
        return _ok(name, "disabled")
    return _ok(name, "enabled (synthetic demo)" if enabled else "disabled")


def check_cors(settings: Settings, mode: Mode) -> CheckResult:
    name = "api.cors_origins"
    origins = settings.origin_list()
    local = [o for o in origins if (urlparse(o).hostname or "").lower() in LOCAL_HOSTS]
    if mode == "trial" and local:
        return _warn(name, f"localhost origins allowed: {', '.join(local)}")
    return _ok(name, ", ".join(origins) or "(none)")


def check_gold_gate(path: Path, mode: Mode) -> CheckResult:
    name = "eval.gold_gate"
    if not path.is_file():
        return _warn(name, f"no result at {path} (run: make eval-gold-report)")
    try:
        payload: Any = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        return _fail(name, f"unreadable result {path}: {type(exc).__name__}")
    if not isinstance(payload, dict):
        return _fail(name, f"unexpected result format in {path}")
    if payload.get("passed") is not True:
        reasons = payload.get("reasons") or []
        return _fail(name, f"gold gate failed: {reasons}")
    metrics = payload.get("metrics") or {}
    rate = metrics.get("false_supported_rate") if isinstance(metrics, dict) else None
    status = str(payload.get("dataset_status") or "")
    detail = f"passed false_supported_rate={rate} dataset_status={status or 'unknown'}"
    if mode == "trial" and status != "clinician_gold":
        return _warn(name, detail + " — clinician sign-off on the gold set is still required")
    return _ok(name, detail)


# --- demo-only -----------------------------------------------------------------------


def check_demo_environment(settings: Settings) -> CheckResult:
    name = "demo.environment"
    if settings.env_name() == "local":
        return _ok(name, "ENVIRONMENT=local")
    return _fail(name, f"demo expects ENVIRONMENT=local (got {settings.env_name()!r})")


def check_demo_phi_off(settings: Settings) -> CheckResult:
    name = "demo.phi_off"
    if settings.allow_phi or settings.phi_program_attested:
        return _fail(name, "ALLOW_PHI / PHI_PROGRAM_ATTESTED must be false for the synthetic demo")
    return _ok(name, "synthetic data only")


def check_demo_jwt_secret(settings: Settings) -> CheckResult:
    name = "demo.dev_jwt_secret"
    if settings.auth_mode.strip().lower() != "dev-jwt":
        return _fail(name, f"demo expects AUTH_MODE=dev-jwt (got {settings.auth_mode!r})")
    if len(settings.dev_jwt_secret.strip()) < MIN_SECRET_LENGTH:
        return _fail(name, f"DEV_JWT_SECRET must be at least {MIN_SECRET_LENGTH} characters")
    return _ok(name, "DEV_JWT_SECRET set")


def check_demo_seed(settings: Settings) -> CheckResult:
    name = "demo.seed_on_startup"
    if settings.seed_on_startup:
        return _ok(name, "SEED_ON_STARTUP=true (synthetic patients load)")
    return _fail(name, "SEED_ON_STARTUP=false — demo desk would start empty")


# --- probes --------------------------------------------------------------------------


def default_db_probe(database_url: str) -> tuple[set[str], set[str]] | None:
    from app.db.session import (
        alembic_revision_status,
        check_connection,
        create_db_engine,
        prepare_sqlite_path,
    )

    prepare_sqlite_path(database_url)
    engine = create_db_engine(database_url)
    try:
        check_connection(engine)
        if database_url.startswith("sqlite"):
            return None
        return alembic_revision_status(engine)
    finally:
        engine.dispose()


def check_database(settings: Settings, probe: DbProbe) -> CheckResult:
    name = "db.reachable_and_migrated"
    try:
        status = probe(settings.database_url)
    except Exception as exc:  # noqa: BLE001 — report any driver/network failure
        return _fail(name, f"database unreachable: {type(exc).__name__}")
    if status is None:
        return _ok(name, "reachable (SQLite — schema via create_all, Alembic not used)")
    current, heads = status
    if not heads:
        return _fail(name, "no Alembic head revisions found")
    if current == heads:
        return _ok(name, f"reachable; Alembic at head {','.join(sorted(heads))}")
    return _fail(
        name,
        f"Alembic not at head (db={','.join(sorted(current)) or 'none'} "
        f"head={','.join(sorted(heads))}); run alembic upgrade head",
    )


def default_oidc_fetcher(issuer: str) -> dict[str, str]:
    from app.auth.oidc import discover_oidc_endpoints

    return discover_oidc_endpoints(issuer)


def check_oidc_discovery(settings: Settings, fetcher: OidcFetcher | None) -> CheckResult:
    name = "auth.oidc_discovery"
    if settings.auth_mode.strip().lower() != "oidc":
        return _ok(name, "not using OIDC")
    if fetcher is None:
        return _warn(name, "skipped (--offline)")
    issuer = settings.oidc_issuer.strip()
    if not issuer:
        return _fail(name, "OIDC_ISSUER is empty")
    try:
        endpoints = fetcher(issuer)
    except Exception as exc:  # noqa: BLE001 — any network / TLS / JSON failure
        return _fail(name, f"discovery failed: {type(exc).__name__}")
    discovered = str(endpoints.get("jwks_url") or "").rstrip("/")
    configured = settings.oidc_jwks_url.strip().rstrip("/")
    if configured and discovered and configured != discovered:
        return _warn(name, f"OIDC_JWKS_URL differs from discovered jwks_uri {discovered}")
    return _ok(name, "issuer discovery ok")


# --- orchestration -------------------------------------------------------------------


def run_checks(
    settings: Settings,
    mode: Mode,
    *,
    db_probe: DbProbe | None = default_db_probe,
    oidc_fetcher: OidcFetcher | None = default_oidc_fetcher,
    gold_result: Path = DEFAULT_GOLD_RESULT,
) -> list[CheckResult]:
    """Run every check for a mode. Pass db_probe=None to skip the database check."""
    results: list[CheckResult] = [check_config_validation(settings)]
    if mode == "demo":
        results += [
            check_demo_environment(settings),
            check_demo_phi_off(settings),
            check_demo_jwt_secret(settings),
            check_demo_seed(settings),
        ]
    else:
        results += [
            check_phi_flags_for_trial(settings),
            check_trial_attestations(settings),
            check_dev_token_disabled(settings),
        ]
    if db_probe is not None:
        results.append(check_database(settings, db_probe))
    else:
        results.append(_warn("db.reachable_and_migrated", "skipped (--skip-db)"))
    results += [
        check_oidc_discovery(settings, oidc_fetcher),
        check_idp_not_dev(settings, mode),
        check_llm_egress(settings, mode),
        check_hospital_keys(settings, mode),
        check_stream_ticket_secret(settings, mode),
        check_rate_limiting(settings, mode),
        check_synthetic_lifelong(settings, mode),
        check_cors(settings, mode),
        check_gold_gate(gold_result, mode),
    ]
    return results


def has_failures(results: Iterable[CheckResult]) -> bool:
    return any(item.status == "FAIL" for item in results)


def format_table(results: list[CheckResult]) -> str:
    width = max([len("CHECK"), *(len(item.name) for item in results)])
    lines = [f"{'CHECK'.ljust(width)}  STATUS  DETAIL", f"{'-' * width}  ------  ------"]
    for item in results:
        lines.append(f"{item.name.ljust(width)}  {item.status.ljust(6)}  {item.detail}")
    return "\n".join(lines)


def main(argv: list[str] | None = None, *, settings: Settings | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="go-live-check",
        description="Configuration gate for a synthetic demo or a real-data hospital trial",
    )
    parser.add_argument("--mode", choices=["demo", "trial"], default=None)
    parser.add_argument("--offline", action="store_true", help="Skip the OIDC discovery network probe")
    parser.add_argument("--skip-db", action="store_true", help="Skip the database / Alembic probe")
    parser.add_argument("--gold-result", type=Path, default=DEFAULT_GOLD_RESULT)
    args = parser.parse_args(argv)

    cfg = settings or get_settings()
    mode: Mode
    if args.mode == "trial" or (args.mode is None and cfg.real_data_mode()):
        mode = "trial"
    else:
        mode = "demo"
    results = run_checks(
        cfg,
        mode,
        db_probe=None if args.skip_db else default_db_probe,
        oidc_fetcher=None if args.offline else default_oidc_fetcher,
        gold_result=args.gold_result,
    )
    print(f"HealthEvidence AI go-live check — mode={mode} environment={cfg.env_name()}")
    print(format_table(results))
    counts = {status: sum(1 for r in results if r.status == status) for status in ("PASS", "WARN", "FAIL")}
    print(f"\n{counts['PASS']} pass, {counts['WARN']} warn, {counts['FAIL']} fail")
    print(
        "Green here means configuration only. It is not clinical, ethical, legal, or security "
        "approval — see docs/GO_LIVE.md."
    )
    if has_failures(results):
        print("GO-LIVE CHECK FAILED", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
