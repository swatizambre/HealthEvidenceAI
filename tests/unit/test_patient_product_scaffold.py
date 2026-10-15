"""Patient-first scaffold: legal notices, emergency card, shares, ABDM stub, doctor brief."""

from fastapi.testclient import TestClient

from app.services import patient_record_share


def test_legal_notices_list_and_privacy_en(client: TestClient) -> None:
    listed = client.get("/api/v1/legal/notices")
    assert listed.status_code == 200, listed.text
    ids = {item["id"] for item in listed.json()["notices"]}
    assert "privacy-notice" in ids
    assert "ai-intended-use" in ids
    notice = client.get("/api/v1/legal/notices/privacy-notice?lang=en")
    assert notice.status_code == 200, notice.text
    body = notice.json()
    assert body["notice_version"] == "privacy-notice.v1"
    assert "Data Fiduciary" in body["body"] or "privacy" in body["body"].lower()


def test_legal_notice_hindi(client: TestClient) -> None:
    notice = client.get("/api/v1/legal/notices/privacy-notice?lang=hi")
    assert notice.status_code == 200, notice.text
    assert notice.json()["language"] in {"hi", "en"}
    assert notice.json()["body"]


def test_abdm_status_not_configured(client: TestClient) -> None:
    response = client.get("/api/v1/abdm/status")
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["status"] == "not_configured"
    assert body["sandbox"] is True


def test_emergency_card_doctor_brief_and_share_flow(client: TestClient) -> None:
    card = client.get("/api/v1/patients/PAT-000001/emergency-card")
    assert card.status_code == 200, card.text
    payload = card.json()
    assert payload["patient_id"] == "PAT-000001"
    assert "disclaimer" in payload

    brief = client.get("/api/v1/patients/PAT-000001/doctor-brief")
    assert brief.status_code == 200, brief.text
    assert brief.json()["brief_lines"]

    ask = client.post(
        "/api/v1/patients/PAT-000001/chart-ask",
        json={"question": "any contrast reaction?"},
    )
    assert ask.status_code == 200, ask.text
    assert ask.json()["answers"]

    session = client.app.state.session_factory()
    try:
        share = patient_record_share.create_share(
            session,
            "PAT-000001",
            scopes=["emergency", "medications", "allergies"],
            hours=2,
            label="Unit test share",
            actor="test",
        )
        session.commit()
        token = share["token"]
        share_id = share["share_id"]
        assert token
    finally:
        session.close()

    public = client.get(f"/api/v1/share/{token}")
    assert public.status_code == 200, public.text
    assert public.json()["patient_id"] == "PAT-000001"

    session = client.app.state.session_factory()
    try:
        patient_record_share.revoke_share(session, "PAT-000001", share_id, actor="test")
        session.commit()
    finally:
        session.close()
    gone = client.get(f"/api/v1/share/{token}")
    assert gone.status_code == 410, gone.text


def test_abdm_link_disabled(client: TestClient) -> None:
    response = client.post(
        "/api/v1/abdm/link",
        json={"abha_id": "12-3456-7890-1234", "patient_id": "PAT-000001"},
    )
    assert response.status_code == 503, response.text
