"""A2A, MONAI imaging, and authentication tests."""

from __future__ import annotations

import pytest
from app.a2a.handlers import consult_imaging_via_a2a, register_default_handlers
from app.a2a.protocol import new_message
from app.auth.oidc import mint_dev_jwt, validate_bearer_token
from app.core.config import Settings
from app.core.exceptions import AppError
from app.services.imaging import MonaiIsolatedAnalyzer, build_image_analyzer
from fastapi.testclient import TestClient


def test_a2a_capability_and_imaging_consult() -> None:
    bus = register_default_handlers()
    bus.clear()
    request = new_message(
        sender="Orchestrator",
        recipient="ImagingAgent",
        kind="capability_query",
        payload={},
    )
    reply = bus.send(request)
    assert reply.kind == "capability_response"
    assert "analyze_study_metadata" in reply.payload["capabilities"]
    result = consult_imaging_via_a2a(
        study_id="IMG-TEST",
        metadata={"modality": "MR", "body_part": "brain"},
    )
    assert result["human_review_required"] is True
    assert "No clinical diagnosis" in " ".join(result["observations"]) or result.get("disclaimer")


def test_monai_isolated_backend_without_package() -> None:
    settings = Settings(imaging_backend="monai")
    analyzer = build_image_analyzer(settings)
    assert isinstance(analyzer, MonaiIsolatedAnalyzer)
    result = analyzer.analyze("IMG-001", {"modality": "CT", "body_part": "chest"})
    assert result.human_review_required is True
    assert result.confidence == 0.0
    assert "diagnosis" in result.disclaimer.lower() or "Not for clinical use" in result.disclaimer
    assert result.backend in {"monai", "monai-numpy-bridge"}


def test_dev_jwt_roundtrip() -> None:
    settings = Settings(auth_mode="dev-jwt", oidc_audience="healthevidence-api")
    token = mint_dev_jwt(subject="alice", roles=["reviewer", "admin"])
    principal = validate_bearer_token(token, settings)
    assert principal.subject == "alice"
    assert "reviewer" in principal.roles


def test_dev_jwt_rejects_garbage() -> None:
    settings = Settings(auth_mode="dev-jwt")
    with pytest.raises(AppError) as err:
        validate_bearer_token("not-a-jwt", settings)
    assert err.value.error_code == "OIDC_UNAUTHORIZED"


def test_a2a_and_auth_http_endpoints(client: TestClient) -> None:
    caps = client.get("/api/v1/a2a/capabilities")
    assert caps.status_code == 200
    assert "ImagingAgent" in caps.json()["capabilities"]

    msg = client.post(
        "/api/v1/a2a/message",
        json={
            "sender": "Orchestrator",
            "recipient": "PolicyAgent",
            "kind": "capability_query",
            "payload": {},
        },
    )
    assert msg.status_code == 200
    assert msg.json()["reply"]["kind"] == "capability_response"

    token = client.post("/api/v1/auth/dev-token", json={"subject": "demo", "roles": ["reviewer"]})
    assert token.status_code == 200
    assert token.json()["access_token"]


def test_imaging_monai_mode_via_api(monkeypatch: pytest.MonkeyPatch) -> None:
    from tests.conftest import make_client

    monkeypatch.setenv("IMAGING_BACKEND", "monai")
    test_client = make_client(monkeypatch)
    with test_client as client:
        response = client.post(
            "/api/v1/imaging/analyze",
            json={"study_id": "IMG-000001", "modality": "DX", "body_part": "ankle"},
        )
        assert response.status_code == 200
        body = response.json()
        assert body["human_review_required"] is True
        assert body["backend"] in {"monai", "monai-numpy-bridge"}
        observations = body["observations"]
        disclaimer = body["disclaimer"]
        assert (
            any(
                "No clinical diagnosis" in item or "Not for clinical use" in disclaimer
                for item in observations
            )
            or "clinical" in disclaimer.lower()
        )
