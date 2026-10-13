"""Lifelong multi-facility health biography."""

from fastapi.testclient import TestClient
from tests.helpers import json_dict


def test_lifelong_summary_has_cross_facility_depth(client: TestClient) -> None:
    response = client.get("/api/v1/patients/PAT-000001/lifelong")
    assert response.status_code == 200, response.text
    body = json_dict(response)
    assert body["patient_id"] == "PAT-000001"
    assert body["facilities_count"] >= 2
    events = body["events"]
    assert isinstance(events, list) and len(events) >= 3
    titles = " ".join(
        str(item.get("title", "")).lower() for item in events if isinstance(item, dict)
    )
    clinical_tokens = ("back", "disc", "physio", "lscs", "cesarean", "append", "diabetes", "thyroid")
    assert any(token in titles for token in clinical_tokens)
    assert body["doctor_brief"]
    brief = body["doctor_brief"].lower()
    assert "filter by" in brief or "filter by label" in brief or "lifelong clinical" in brief
    assert "Medication reconciliation" not in body["doctor_brief"]
    assert "homeless" not in titles
    assert "primary school" not in titles
    assert "medication reconciliation" not in titles
    assert body["disorders_count"] >= 2
    disorders = body["disorders"]
    by_disorder = body["by_disorder"]
    assert isinstance(disorders, list) and len(disorders) >= 2
    assert isinstance(by_disorder, list) and len(by_disorder) >= 2
    disorder_keys = {
        str(group["key"]) for group in by_disorder if isinstance(group, dict)
    }
    assert any(name in disorder_keys for name in disorders)
    assert all(
        isinstance(group, dict) and group["count"] == len(group["events"])
        for group in by_disorder
    )
    # Primary filters are disorders — not hospitals or specialty service lines.
    hospitalish = {
        "Casualty — District Civil Hospital",
        "District Civil Hospital — Satara",
        "Primary Health Centre — Wadki",
    }
    assert hospitalish.isdisjoint(set(body["disorders"]))
    assert "General surgery" not in body["disorders"]
    assert "Unspecified" not in body["disorders"]
    # At least one common chronic-style chapter appears in the catalog path.
    catalogish = {
        "Diabetes",
        "Thyroid disorder",
        "Hypertension",
        "Disc disease / back pain",
        "Trauma / injury",
        "Obstetric history",
        "Gastritis / GI",
    }
    assert disorder_keys & catalogish
    assert all(
        isinstance(item, dict) and isinstance(item.get("disorders"), list) for item in events
    )
