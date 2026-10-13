"""HTTP contracts for health, patients, documents, retrieval, and errors."""

from __future__ import annotations

from datetime import date
from uuid import uuid4

import pytest
from app.api.deps import get_db
from app.core.config import get_settings
from app.core.safety import DISCLAIMER, PROTOTYPE_BANNER
from app.models import Patient
from app.services.synthetic import SEEDED_AT
from fastapi.testclient import TestClient
from sqlalchemy.exc import SQLAlchemyError
from tests.conftest import make_client


def test_health_and_docs(client: TestClient) -> None:
    health = client.get("/health")
    assert health.status_code == 200
    assert health.json() == {"status": "ok"}
    docs = client.get("/docs")
    assert docs.status_code == 200
    assert "text/html" in docs.headers["content-type"]
    spec = client.get("/openapi.json")
    assert spec.status_code == 200
    paths = spec.json()["paths"]
    assert "/health" in paths
    assert "/api/v1/patients" in paths
    assert "/api/v1/authorization/review" in paths
    root = client.get("/")
    assert PROTOTYPE_BANNER in root.json()["disclaimer"]
    missing = client.get("/not-a-route")
    assert missing.status_code == 404
    assert missing.json()["error_code"] == "NOT_FOUND"


def test_patient_list_and_detail(client: TestClient) -> None:
    listing = client.get("/api/v1/patients")
    assert listing.status_code == 200
    body = listing.json()
    assert body["total"] == 100
    assert len(body["patients"]) == 20
    assert body["patients"][0]["patient_id"] == "PAT-000001"
    detail = client.get("/api/v1/patients/PAT-000001")
    assert detail.status_code == 200
    payload = detail.json()
    assert payload["patient_id"] == "PAT-000001"
    assert payload["demographics"]["synthetic_name"].startswith("Synthetic Patient")
    assert payload["conditions"]
    assert all("(finding)" not in c and "(situation)" not in c for c in payload["conditions"])
    assert payload["medications"]
    assert payload["labs"]
    assert payload["labs"][0]["test_name"]
    # Procedures may be empty when the seed only has admin noise (e.g. med reconciliation).
    assert isinstance(payload["procedures"], list)
    assert payload["imaging"]
    assert payload["clinical_notes"]
    assert "SYNTHEA_RECORD_PAT_000001" in payload["clinical_notes"][0]["content"]
    assert "Synthea sample CSV" in payload["clinical_notes"][0]["content"]

def test_patient_creation_round_trip(client: TestClient) -> None:
    session = client.app.state.session_factory()
    try:
        session.add(
            Patient(
                id=str(uuid4()),
                patient_code="PAT-000999",
                synthetic_name="Synthetic Patient 000999",
                birth_date=date(1980, 1, 1),
                sex="unknown",
                conditions=["Synthetic condition alpha"],
                created_at=SEEDED_AT,
                updated_at=SEEDED_AT,
            )
        )
        session.commit()
    finally:
        session.close()
    response = client.get("/api/v1/patients/PAT-000999")
    assert response.status_code == 200
    assert response.json()["demographics"]["synthetic_name"] == "Synthetic Patient 000999"


def test_timeline_is_ordered_facts(client: TestClient) -> None:
    response = client.get("/api/v1/patients/PAT-000001/timeline")
    assert response.status_code == 200
    events = response.json()["events"]
    stamps = [event["timestamp"] for event in events]
    assert stamps == sorted(stamps, reverse=True)
    assert events
    assert all(event["classification"] == "FACT" for event in events)
    assert all(event.get("specialty") for event in events)


def test_invalid_and_unknown_patient(client: TestClient) -> None:
    invalid = client.get("/api/v1/patients/nope")
    assert invalid.status_code == 422
    assert invalid.json()["error_code"] == "VALIDATION_ERROR"
    assert "Traceback" not in invalid.text
    missing = client.get("/api/v1/patients/PAT-999999")
    assert missing.status_code == 404
    assert missing.json()["error_code"] == "PATIENT_NOT_FOUND"
    assert missing.json()["request_id"]


def test_policy_retrieval(client: TestClient) -> None:
    listing = client.get("/api/v1/policies")
    assert listing.status_code == 200
    assert listing.json()["total"] == 20
    detail = client.get("/api/v1/policies/POL-000001")
    assert detail.status_code == 200
    from tests.helpers import json_dict

    body = json_dict(detail)
    assert body["policy_id"] == "POL-000001"
    assert "POLICY_MARKER_DYNAMIC_REVIEW" in body["content"]
    criteria = body["criteria"]
    assert isinstance(criteria, list)
    codes = [
        item["criterion_id"] for item in criteria if isinstance(item, dict)
    ]
    assert codes == [
        "CRIT-DYN-01",
        "CRIT-DYN-02",
        "CRIT-DYN-03",
        "CRIT-DYN-04",
        "CRIT-DYN-05",
    ]
    missing = client.get("/api/v1/policies/POL-999999")
    assert missing.status_code == 404
    assert missing.json()["error_code"] == "POLICY_NOT_FOUND"


def test_document_ingestion_links_the_patient(client: TestClient) -> None:
    created = client.post(
        "/api/v1/documents",
        json={
            "document_type": "clinical_note",
            "patient_id": "PAT-000010",
            "source": "api",
            "content": "Unique ingestion marker SYN_INGEST_ALPHA is present in this synthetic note.",
            "metadata": {"origin": "unit-test"},
        },
    )
    assert created.status_code == 201
    body = created.json()
    assert body["patient_id"] == "PAT-000010"
    assert body["chunk_count"] >= 1
    fetched = client.get(f"/api/v1/documents/{body['document_id']}")
    assert fetched.status_code == 200
    assert "SYN_INGEST_ALPHA" in fetched.json()["content"]
    listed = client.get("/api/v1/patients/PAT-000010/documents")
    assert any(item["document_id"] == body["document_id"] for item in listed.json()["documents"])
    detail = client.get("/api/v1/patients/PAT-000010")
    assert any("SYN_INGEST_ALPHA" in note["content"] for note in detail.json()["clinical_notes"])
    search = client.post(
        "/api/v1/evidence/search",
        json={"query": "SYN_INGEST_ALPHA", "patient_id": "PAT-000010"},
    )
    assert search.status_code == 200
    assert search.json()["sources"][0]["document_id"] == body["document_id"]
    assert search.json()["sources"][0]["chunk_id"]


def test_policy_document_can_be_stored(client: TestClient) -> None:
    response = client.post(
        "/api/v1/documents",
        json={
            "document_type": "policy",
            "source": "api",
            "content": "Synthetic uploaded policy marker SYN_POLICY_UPLOAD.",
        },
    )
    assert response.status_code == 201
    assert response.json()["patient_id"] is None
    assert response.json()["document_type"] == "policy"


def test_rag_returns_the_lumbar_policy_source(client: TestClient) -> None:
    policy = client.get("/api/v1/policies/POL-000001").json()
    response = client.post(
        "/api/v1/evidence/search",
        json={
            "query": "POLICY_MARKER_DYNAMIC_REVIEW Dynamic catalog evidence review",
            "document_type": "policy",
            "limit": 3,
        },
    )
    assert response.status_code == 200
    body = response.json()
    assert body["sources"]
    assert body["sources"][0]["document_id"] == policy["document_id"]
    assert body["sources"][0]["chunk_id"].startswith(policy["document_id"])
    assert body["answer"]
    assert "Retrieved evidence states:" in body["answer"]


def test_retrieval_does_not_cross_patients(client: TestClient) -> None:
    own = client.post(
        "/api/v1/evidence/search",
        json={"query": "SYNTHEA_RECORD_PAT_000001", "patient_id": "PAT-000001"},
    ).json()
    other = client.post(
        "/api/v1/evidence/search",
        json={"query": "SYNTHEA_RECORD_PAT_000001", "patient_id": "PAT-000050"},
    ).json()
    assert own["sources"]
    assert other["sources"] == []
    assert "No matching synthetic documents" in other["answer"]


def test_unknown_query_has_no_fabricated_source(client: TestClient) -> None:
    response = client.post("/api/v1/evidence/search", json={"query": "zzzzqqqplugh"})
    body = response.json()
    assert body["sources"] == []
    assert "No matching" in body["answer"]


def test_database_error_is_structured(client: TestClient) -> None:
    def bad_db() -> object:
        raise SQLAlchemyError("sensitive-sql")
        yield

    client.app.dependency_overrides[get_db] = bad_db
    response = client.get("/api/v1/patients")
    client.app.dependency_overrides.clear()
    assert response.status_code == 503
    assert response.json()["error_code"] == "DATABASE_ERROR"
    assert "sensitive-sql" not in response.text
    assert "Traceback" not in response.text


def test_unexpected_error_hides_internals(monkeypatch: pytest.MonkeyPatch) -> None:
    def boom(*args: object, **kwargs: object) -> object:
        raise RuntimeError("SECRET_STACK_TOKEN")

    test_client = make_client(monkeypatch, raise_server_exceptions=False)
    with test_client as client:
        monkeypatch.setattr("app.api.routes.patients.list_patient_summaries", boom)
        response = client.get("/api/v1/patients")
    get_settings.cache_clear()
    assert response.status_code == 500
    assert response.json()["error_code"] == "INTERNAL_ERROR"
    assert "SECRET_STACK_TOKEN" not in response.text
    assert "Traceback" not in response.text


def test_llm_unavailable(monkeypatch: pytest.MonkeyPatch) -> None:
    from app.core.exceptions import LLMUnavailable

    test_client = make_client(monkeypatch, LLM_PROVIDER="openai")

    def boom(settings: object) -> object:
        del settings
        raise LLMUnavailable("OPENAI_API_KEY is required for LLM_PROVIDER=openai.")

    monkeypatch.setattr("app.api.routes.evidence.build_llm", boom)
    with test_client:
        response = test_client.post(
            "/api/v1/evidence/search",
            json={"query": "POLICY_MARKER_DYNAMIC_REVIEW"},
        )
    get_settings.cache_clear()
    assert response.status_code == 503
    assert response.json()["error_code"] == "LLM_UNAVAILABLE"
    assert "sk-" not in response.text


def test_retrieval_failure(client: TestClient, monkeypatch: pytest.MonkeyPatch) -> None:
    def boom(*args: object, **kwargs: object) -> list[object]:
        raise RuntimeError("index offline")

    monkeypatch.setattr("app.api.routes.evidence.hybrid_search", boom)
    response = client.post("/api/v1/evidence/search", json={"query": "dynamic catalog evidence review"})
    assert response.status_code == 503
    assert response.json()["error_code"] == "RETRIEVAL_FAILED"
    assert "index offline" not in response.text


def test_stats(client: TestClient) -> None:
    response = client.get("/api/v1/stats")
    assert response.status_code == 200
    assert response.json() == {
        "patients": 100,
        "authorization_cases": 20,
        "policies": 20,
        "system_status": "ok",
    }


def test_patient_search_filters_catalog(client: TestClient) -> None:
    response = client.get("/api/v1/patients", params={"q": "PAT-000001", "limit": 10})
    assert response.status_code == 200
    from tests.helpers import json_dict

    body = json_dict(response)
    assert body["total"] >= 1
    patients = body["patients"]
    assert isinstance(patients, list)
    assert any(
        isinstance(item, dict) and item["patient_id"] == "PAT-000001" for item in patients
    )


def test_disclaimer_constant_matches_the_safety_copy() -> None:
    assert "not a diagnosis or clinical decision" in DISCLAIMER
    assert PROTOTYPE_BANNER == "Not for clinical use or diagnosis."
