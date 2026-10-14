"""Go-live check: pure check functions over Settings + CLI exit codes."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest
from app.cli import go_live_check as glc
from app.core.config import Settings


def _demo(**overrides: Any) -> Settings:
    values: dict[str, Any] = {
        "environment": "local",
        "auth_mode": "dev-jwt",
        "dev_jwt_secret": "d" * 40,
        "database_url": "sqlite://",
        "llm_provider": "local",
        "llm_fallback_providers": "local",
        "seed_on_startup": True,
        "allow_phi": False,
        "phi_program_attested": False,
    }
    values.update(overrides)
    return Settings(**values)


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
        "trial_ethics_approval_ref": "IEC/2026/HE-014",
        "dpo_contact": "dpo@hospital.example",
        "security_assessment_ref": "VAPT-2026-09-HE",
        "breach_runbook_url": "https://wiki.hospital.example/he/breach",
        "data_residency_region": "ap-south-1",
        "trial_site_org_code": "ORG-000001",
        "trial_end_date": "2999-12-31",
        "cors_origins": "https://he.hospital.example",
    }
    values.update(overrides)
    return Settings(**values)


def _at_head(_url: str) -> tuple[set[str], set[str]]:
    return {"0002"}, {"0002"}


def _discovery(_issuer: str) -> dict[str, str]:
    return {
        "issuer": "https://idp.hospital.example/realms/he",
        "jwks_url": "https://idp.hospital.example/realms/he/protocol/openid-connect/certs",
    }


def _gold(tmp_path: Path, *, passed: bool = True, status: str = "clinician_gold") -> Path:
    path = tmp_path / "gold.json"
    path.write_text(
        json.dumps(
            {
                "passed": passed,
                "dataset_status": status,
                "metrics": {"false_supported_rate": 0.0},
                "reasons": [] if passed else ["false_supported_rate=0.1"],
            }
        ),
        encoding="utf-8",
    )
    return path


def _by_name(results: list[glc.CheckResult]) -> dict[str, glc.CheckResult]:
    return {item.name: item for item in results}


# --- demo ---------------------------------------------------------------------------


def test_demo_mode_passes_with_good_settings(tmp_path: Path) -> None:
    results = glc.run_checks(
        _demo(), "demo", db_probe=lambda _u: None, oidc_fetcher=None, gold_result=_gold(tmp_path)
    )
    assert not glc.has_failures(results), glc.format_table(results)


def test_demo_rejects_non_local_env() -> None:
    assert glc.check_demo_environment(_demo(environment="pilot")).status == "FAIL"


def test_demo_rejects_phi() -> None:
    assert glc.check_demo_phi_off(_demo(allow_phi=True)).status == "FAIL"


def test_demo_requires_long_secret() -> None:
    assert glc.check_demo_jwt_secret(_demo(dev_jwt_secret="short")).status == "FAIL"
    assert glc.check_demo_jwt_secret(_demo(auth_mode="oidc")).status == "FAIL"


def test_demo_requires_seed() -> None:
    assert glc.check_demo_seed(_demo(seed_on_startup=False)).status == "FAIL"


# --- trial --------------------------------------------------------------------------


def test_trial_passes_when_fully_configured(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("PILOT_POSTGRES_TEST", raising=False)
    results = glc.run_checks(
        _trial(), "trial", db_probe=_at_head, oidc_fetcher=_discovery, gold_result=_gold(tmp_path)
    )
    failures = [r for r in results if r.status == "FAIL"]
    assert not failures, glc.format_table(results)


def test_trial_flags_config_validation_failure() -> None:
    result = glc.check_config_validation(_trial(dpo_contact=""))
    assert result.status == "FAIL"
    assert "DPO_CONTACT" in result.detail


def test_trial_requires_phi_flags() -> None:
    assert glc.check_phi_flags_for_trial(_trial(allow_phi=False)).status == "FAIL"
    assert glc.check_phi_flags_for_trial(_trial()).status == "PASS"


def test_trial_attestations_reported_before_flags_flip() -> None:
    result = glc.check_trial_attestations(_trial(allow_phi=False, trial_ethics_approval_ref=""))
    assert result.status == "FAIL"
    assert "TRIAL_ETHICS_APPROVAL_REF" in result.detail


def test_dev_token_must_be_disabled(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("PILOT_POSTGRES_TEST", raising=False)
    assert glc.check_dev_token_disabled(_trial()).status == "PASS"
    assert glc.check_dev_token_disabled(_demo()).status == "FAIL"
    monkeypatch.setenv("PILOT_POSTGRES_TEST", "1")
    assert glc.check_dev_token_disabled(_trial()).status == "FAIL"


def test_cloud_llm_blocked_without_attestation() -> None:
    settings = _trial(llm_provider="openai", openai_api_key="sk-test")
    assert glc.check_llm_egress(settings, "trial").status == "FAIL"
    attested = _trial(
        llm_provider="openai", openai_api_key="sk-test", llm_baa_attested=True, llm_phi_egress_allowed=True
    )
    assert glc.check_llm_egress(attested, "trial").status == "WARN"
    assert glc.check_llm_egress(_trial(), "trial").status == "PASS"
    assert glc.check_llm_egress(_demo(llm_provider="gemini"), "demo").status == "WARN"


def test_idp_localhost_warns_for_trial() -> None:
    local = _trial(oidc_issuer="http://127.0.0.1:8080/realms/healthevidence")
    assert glc.check_idp_not_dev(local, "trial").status == "WARN"
    in_compose = _trial(oidc_issuer="http://keycloak:8080/realms/healthevidence")
    assert glc.check_idp_not_dev(in_compose, "trial").status == "WARN"
    plain_http = _trial(oidc_issuer="http://idp.hospital.example/realms/he")
    assert glc.check_idp_not_dev(plain_http, "trial").status == "FAIL"
    assert glc.check_idp_not_dev(_trial(), "trial").status == "PASS"
    assert glc.check_idp_not_dev(_trial(auth_mode="dev-jwt"), "trial").status == "FAIL"
    assert glc.check_idp_not_dev(_trial(oidc_issuer=""), "trial").status == "FAIL"
    assert glc.check_idp_not_dev(_demo(), "demo").status == "PASS"


def test_synthetic_lifelong_must_be_off_for_trial() -> None:
    assert glc.check_synthetic_lifelong(_trial(), "trial").status == "PASS"
    forced = _trial(allow_phi=False, synthetic_lifelong=True)
    assert glc.check_synthetic_lifelong(forced, "trial").status == "FAIL"
    assert glc.check_synthetic_lifelong(_demo(), "demo").status == "PASS"


def test_stream_ticket_secret_checked() -> None:
    short = _trial(stream_ticket_secret="abc")
    good = _trial(stream_ticket_secret="s" * 40)
    assert glc.check_stream_ticket_secret(short, "trial").status == "FAIL"
    assert glc.check_stream_ticket_secret(short, "demo").status == "WARN"
    assert glc.check_stream_ticket_secret(good, "trial").status == "PASS"


def test_rate_limit_checked() -> None:
    off = _trial(rate_limit_enabled=False)
    on = _trial(rate_limit_enabled=True)
    default_on = _trial(rate_limit_enabled=None)  # unset → active outside ENVIRONMENT=test
    assert glc.check_rate_limiting(off, "trial").status == "FAIL"
    assert glc.check_rate_limiting(off, "demo").status == "WARN"
    assert glc.check_rate_limiting(on, "trial").status == "PASS"
    assert glc.check_rate_limiting(default_on, "trial").status == "PASS"


def test_hospital_keys_checked() -> None:
    key = "k" * 40
    per_org = _trial(hospital_interface_keys=f"ORG-000001:{key}")
    other_org = _trial(hospital_interface_keys=f"ORG-000009:{key}")
    prefix_only = _trial(hospital_interface_keys=f"ORG-0000011:{key}")
    none = _trial(hospital_interface_keys="")
    shared = _trial(hospital_interface_api_key="shared-secret", hospital_interface_keys="")
    assert glc.check_hospital_keys(per_org, "trial").status == "PASS"
    assert glc.check_hospital_keys(other_org, "trial").status == "WARN"
    assert glc.check_hospital_keys(prefix_only, "trial").status == "WARN"
    assert glc.check_hospital_keys(none, "trial").status == "PASS"
    assert glc.check_hospital_keys(shared, "trial").status == "FAIL"
    assert glc.check_hospital_keys(shared, "demo").status == "WARN"


def test_cors_localhost_warns_for_trial() -> None:
    assert glc.check_cors(_trial(cors_origins="http://localhost:3000"), "trial").status == "WARN"
    assert glc.check_cors(_trial(), "trial").status == "PASS"


# --- probes -------------------------------------------------------------------------


def test_database_probe_states() -> None:
    settings = _trial()
    assert glc.check_database(settings, _at_head).status == "PASS"
    assert glc.check_database(settings, lambda _u: None).status == "PASS"
    behind = glc.check_database(settings, lambda _u: ({"0001"}, {"0002"}))
    assert behind.status == "FAIL"
    assert "head" in behind.detail
    assert glc.check_database(settings, lambda _u: (set(), set())).status == "FAIL"

    def _boom(_url: str) -> tuple[set[str], set[str]] | None:
        raise ConnectionError("refused")

    down = glc.check_database(settings, _boom)
    assert down.status == "FAIL"
    assert "ConnectionError" in down.detail


def test_default_db_probe_on_sqlite() -> None:
    assert glc.default_db_probe("sqlite://") is None


def test_oidc_discovery_states() -> None:
    settings = _trial()
    assert glc.check_oidc_discovery(settings, _discovery).status == "PASS"
    assert glc.check_oidc_discovery(settings, None).status == "WARN"
    assert glc.check_oidc_discovery(_demo(), _discovery).status == "PASS"

    def _fails(_issuer: str) -> dict[str, str]:
        raise OSError("dns")

    assert glc.check_oidc_discovery(settings, _fails).status == "FAIL"
    mismatch = glc.check_oidc_discovery(settings, lambda _i: {"jwks_url": "https://other/certs"})
    assert mismatch.status == "WARN"
    assert glc.check_oidc_discovery(_trial(oidc_issuer=""), _discovery).status == "FAIL"


def test_gold_gate_states(tmp_path: Path) -> None:
    assert glc.check_gold_gate(tmp_path / "missing.json", "trial").status == "WARN"
    assert glc.check_gold_gate(_gold(tmp_path), "trial").status == "PASS"
    assert glc.check_gold_gate(_gold(tmp_path, status="engineering_seed"), "trial").status == "WARN"
    assert glc.check_gold_gate(_gold(tmp_path, status="engineering_seed"), "demo").status == "PASS"
    assert glc.check_gold_gate(_gold(tmp_path, passed=False), "trial").status == "FAIL"
    bad = tmp_path / "bad.json"
    bad.write_text("{not json", encoding="utf-8")
    assert glc.check_gold_gate(bad, "trial").status == "FAIL"
    listy = tmp_path / "list.json"
    listy.write_text("[]", encoding="utf-8")
    assert glc.check_gold_gate(listy, "trial").status == "FAIL"


def test_run_checks_skip_db_warns(tmp_path: Path) -> None:
    results = glc.run_checks(_demo(), "demo", db_probe=None, oidc_fetcher=None, gold_result=_gold(tmp_path))
    assert _by_name(results)["db.reachable_and_migrated"].status == "WARN"


def test_format_table_lists_every_check() -> None:
    rows = [glc.CheckResult("a.b", "PASS", "fine"), glc.CheckResult("long.check.name", "FAIL", "bad")]
    table = glc.format_table(rows)
    assert "STATUS" in table
    assert "long.check.name" in table
    assert "FAIL" in table


# --- CLI ----------------------------------------------------------------------------


def test_main_demo_exit_zero(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    code = glc.main(
        ["--mode", "demo", "--offline", "--gold-result", str(_gold(tmp_path))],
        settings=_demo(),
    )
    out = capsys.readouterr().out
    assert code == 0, out
    assert "mode=demo" in out
    assert "not clinical" in out


def test_main_trial_fails_on_demo_settings(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    code = glc.main(
        ["--mode", "trial", "--offline", "--skip-db", "--gold-result", str(_gold(tmp_path))],
        settings=_demo(),
    )
    captured = capsys.readouterr()
    assert code == 1
    assert "FAIL" in captured.out
    assert "GO-LIVE CHECK FAILED" in captured.err


def test_main_infers_trial_from_phi_flags(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    glc.main(["--offline", "--skip-db", "--gold-result", str(_gold(tmp_path))], settings=_trial())
    assert "mode=trial" in capsys.readouterr().out
