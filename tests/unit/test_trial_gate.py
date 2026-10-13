"""Real-data trial gate: ALLOW_PHI + PHI_PROGRAM_ATTESTED needs the full attestation set."""

from __future__ import annotations

from datetime import date
from typing import Any

import pytest
from app.core.config import Settings
from app.core.exceptions import AppError

TODAY = date(2026, 10, 13)


def _trial(**overrides: Any) -> Settings:
    values: dict[str, Any] = {
        "environment": "pilot",
        "auth_mode": "oidc",
        "oidc_issuer": "https://idp.hospital.example/realms/he",
        "oidc_jwks_url": "https://idp.hospital.example/realms/he/protocol/openid-connect/certs",
        "database_url": "postgresql+psycopg://u:p@db.internal/he",
        "llm_provider": "local",
        "llm_fallback_providers": "local",
        "seed_on_startup": False,
        "enforce_org_scope": True,
        "hospital_allow_simulate": False,
        "allow_phi": True,
        "phi_program_attested": True,
        "stream_ticket_secret": "s" * 40,
        "staff_pseudonym_secret": "p" * 40,
        "synthetic_lifelong": None,
        "trial_ethics_approval_ref": "IEC/2026/HE-014",
        "dpo_contact": "dpo@hospital.example",
        "security_assessment_ref": "VAPT-2026-09-HE",
        "breach_runbook_url": "https://wiki.hospital.example/he/breach",
        "data_residency_region": "ap-south-1",
        "trial_site_org_code": "ORG-000001",
        "trial_end_date": "2999-12-31",
    }
    values.update(overrides)
    return Settings(**values)


def _problems(**overrides: Any) -> list[str]:
    return _trial(**overrides).real_data_trial_problems(TODAY)


def test_fully_attested_trial_passes() -> None:
    settings = _trial()
    assert settings.real_data_trial_problems(TODAY) == []
    settings.validate_real_data_trial(TODAY)
    assert settings.deployment_mode() == "trial"


def test_trial_gate_inactive_without_phi() -> None:
    settings = _trial(allow_phi=False, trial_ethics_approval_ref="", environment="local")
    assert settings.real_data_trial_problems(TODAY) == []
    assert settings.deployment_mode() == "demo"


def test_trial_gate_needs_both_phi_flags() -> None:
    assert _trial(phi_program_attested=False, dpo_contact="").real_data_trial_problems(TODAY) == []


@pytest.mark.parametrize("env", ["local", "test", "docker"])
def test_real_data_never_on_local_or_test(env: str) -> None:
    problems = _problems(environment=env)
    assert any("ENVIRONMENT" in item for item in problems)


@pytest.mark.parametrize("env", ["pilot", "staging", "production", "prod", "kubernetes"])
def test_real_data_allowed_environments(env: str) -> None:
    assert _problems(environment=env) == []


def test_real_data_requires_oidc() -> None:
    assert "AUTH_MODE=oidc" in _problems(auth_mode="dev-jwt")


def test_real_data_requires_postgres() -> None:
    assert "DATABASE_URL must be PostgreSQL" in _problems(database_url="sqlite:///./x.db")


def test_real_data_requires_org_scope() -> None:
    assert "ENFORCE_ORG_SCOPE=true" in _problems(enforce_org_scope=False)


def test_real_data_requires_seed_off() -> None:
    assert "SEED_ON_STARTUP=false" in _problems(seed_on_startup=True)


def test_real_data_rejects_synthetic_lifelong() -> None:
    assert any("SYNTHETIC_LIFELONG" in item for item in _problems(synthetic_lifelong=True))


@pytest.mark.parametrize(
    ("field", "env_var"),
    [
        ("trial_ethics_approval_ref", "TRIAL_ETHICS_APPROVAL_REF"),
        ("dpo_contact", "DPO_CONTACT"),
        ("security_assessment_ref", "SECURITY_ASSESSMENT_REF"),
        ("breach_runbook_url", "BREACH_RUNBOOK_URL"),
        ("trial_site_org_code", "TRIAL_SITE_ORG_CODE"),
    ],
)
def test_each_attestation_is_required(field: str, env_var: str) -> None:
    assert env_var in _problems(**{field: "  "})


@pytest.mark.parametrize("region", ["", "global"])
def test_data_residency_region_must_be_concrete(region: str) -> None:
    assert any("DATA_RESIDENCY_REGION" in item for item in _problems(data_residency_region=region))


def test_trial_end_date_required() -> None:
    assert any("TRIAL_END_DATE" in item for item in _problems(trial_end_date=""))


def test_trial_end_date_must_be_iso() -> None:
    problems = _problems(trial_end_date="31/12/2026")
    assert any("ISO date" in item for item in problems)


def test_trial_end_date_in_past_fails() -> None:
    problems = _problems(trial_end_date="2026-10-12")
    assert any("in the past" in item for item in problems)


def test_trial_end_date_today_is_still_valid() -> None:
    assert _problems(trial_end_date=TODAY.isoformat()) == []


def test_all_missing_items_reported_in_one_message() -> None:
    settings = _trial(
        trial_ethics_approval_ref="",
        dpo_contact="",
        security_assessment_ref="",
        breach_runbook_url="",
        trial_site_org_code="",
        data_residency_region="global",
        trial_end_date="",
    )
    with pytest.raises(AppError) as exc:
        settings.validate_live_configuration()
    assert exc.value.error_code == "LIVE_CONFIG_INVALID"
    message = exc.value.message
    for needle in (
        "TRIAL_ETHICS_APPROVAL_REF",
        "DPO_CONTACT",
        "SECURITY_ASSESSMENT_REF",
        "BREACH_RUNBOOK_URL",
        "TRIAL_SITE_ORG_CODE",
        "DATA_RESIDENCY_REGION",
        "TRIAL_END_DATE",
    ):
        assert needle in message


def test_validate_live_configuration_rejects_real_data_on_local() -> None:
    settings = _trial(environment="local", auth_mode="dev-jwt", dev_jwt_secret="x" * 40)
    with pytest.raises(AppError) as exc:
        settings.validate_live_configuration()
    assert exc.value.error_code == "LIVE_CONFIG_INVALID"
    assert "ENVIRONMENT" in exc.value.message
    assert "AUTH_MODE=oidc" in exc.value.message


def test_validate_live_configuration_accepts_full_trial_in_production() -> None:
    _trial(environment="production", trial_end_date="2999-01-01").validate_live_configuration()


def test_trial_end_parsing() -> None:
    assert _trial(trial_end_date="2026-12-31").trial_end() == date(2026, 12, 31)
    assert _trial(trial_end_date="soon").trial_end() is None
    assert _trial(trial_end_date="").trial_end() is None


def test_deployment_mode_practice_for_shared_synthetic() -> None:
    assert _trial(allow_phi=False, environment="staging").deployment_mode() == "practice"


def test_staff_pseudonym_secret_required_and_distinct() -> None:
    missing = _trial(staff_pseudonym_secret="")
    assert any("STAFF_PSEUDONYM_SECRET" in p for p in missing.real_data_trial_problems())
    reused = _trial(staff_pseudonym_secret="s" * 40, stream_ticket_secret="s" * 40)
    assert any("must differ" in p for p in reused.real_data_trial_problems())
    assert _trial().real_data_trial_problems() == []


def test_trial_expired_is_checked_at_runtime() -> None:
    settings = _trial(trial_end_date="2026-10-31")
    assert settings.trial_expired(today=date(2026, 10, 31)) is False
    assert settings.trial_expired(today=date(2026, 11, 1)) is True
    assert _trial(allow_phi=False).trial_expired(today=date(2999, 1, 1)) is False
