"""Emergency card QR link: public opening, family alerts, place sharing, link rotation."""

from __future__ import annotations

from app.models.entities import CareRelationship, Patient
from app.services import qr
from fastapi.testclient import TestClient
from sqlalchemy import select
from tests.conftest import make_client


def _patient_headers(client: TestClient, patient_id: str) -> dict[str, str]:
    response = client.post(
        "/api/v1/auth/dev-token",
        json={"subject": patient_id, "roles": ["patient"], "patient_id": patient_id},
    )
    assert response.status_code == 200, response.text
    return {"Authorization": f"Bearer {response.json()['access_token']}"}


def _token_from(card: dict) -> str:
    url = card["emergency_url"]
    assert "/e/" in url
    return url.rsplit("/e/", 1)[1]


def test_qr_matrix_shape() -> None:
    rows = qr.encode("https://example.in/e/AbCdEfGhIjKlMnOpQrStUv")
    assert len(rows) == 33  # version 4 for a 43-byte link
    assert all(len(row) == len(rows) for row in rows)
    assert set("".join(rows)) <= {"0", "1"}
    # Finder pattern corners are dark.
    assert rows[0][0] == rows[0][-1] == rows[-1][0] == "1"


def test_owner_card_has_link_and_qr(monkeypatch) -> None:
    with make_client(monkeypatch, AUTH_MODE="dev-jwt", PUBLIC_APP_URL="https://app.example.in/") as client:
        headers = _patient_headers(client, "PAT-000001")
        card = client.get("/api/v1/me/emergency-card", headers=headers)
        assert card.status_code == 200, card.text
        body = card.json()
        assert body["emergency_url"].startswith("https://app.example.in/e/")
        assert len(body["qr_modules"]) >= 21
        assert body["alert_family"] is True

        again = client.get("/api/v1/me/emergency-card", headers=headers).json()
        assert again["emergency_url"] == body["emergency_url"], "link is stable until rotated"

        # Staff viewing the chart's card never get the patient's secret link.
        staff = client.post(
            "/api/v1/auth/dev-token", json={"subject": "nurse", "roles": ["staff"]}
        ).json()["access_token"]
        staff_card = client.get(
            "/api/v1/patients/PAT-000001/emergency-card",
            headers={"Authorization": f"Bearer {staff}"},
        )
        assert staff_card.status_code == 200, staff_card.text
        assert staff_card.json()["emergency_url"] == ""


def test_public_open_alerts_owner_and_family_once(monkeypatch) -> None:
    with make_client(monkeypatch, AUTH_MODE="dev-jwt") as client:
        owner = _patient_headers(client, "PAT-000001")
        family = _patient_headers(client, "PAT-000002")
        stranger = _patient_headers(client, "PAT-000003")
        session = client.app.state.session_factory()
        try:
            patient = session.scalar(select(Patient).where(Patient.patient_code == "PAT-000001"))
            assert patient is not None
            session.add(
                CareRelationship(
                    relationship_code="REL-EA-0001",
                    patient_id=patient.id,
                    related_display_name="Daughter",
                    relationship_type="child",
                    related_patient_code="PAT-000002",
                )
            )
            session.commit()
        finally:
            session.close()
        client.patch(
            "/api/v1/me/emergency-card",
            headers=owner,
            json={
                "blood_group": "B+",
                "emergency_contacts": [{"name": "Asha", "phone": "+91 90000 00000", "relation": "daughter"}],
            },
        )
        token = _token_from(client.get("/api/v1/me/emergency-card", headers=owner).json())

        # No sign-in needed; the same browser reloading does not raise a second alert.
        ua = {"User-Agent": "test-phone"}
        opened = client.get(f"/api/v1/emergency/{token}", headers=ua)
        assert opened.status_code == 200, opened.text
        public = opened.json()
        assert public["blood_group"] == "B+"
        assert public["emergency_contacts"][0]["phone"] == "+91 90000 00000"
        assert public["family_alerted"] is True
        assert "patient_id" not in public
        reload = client.get(f"/api/v1/emergency/{token}", headers=ua).json()
        assert reload["event_id"] == public["event_id"]

        place = client.post(
            f"/api/v1/emergency/{token}/events/{public['event_id']}/place",
            json={
                "place_note": "  City Hospital,   ER bay 3 ",
                "latitude": 18.520431,
                "longitude": 73.856743,
            },
        )
        assert place.status_code == 200, place.text
        assert place.json()["place_note"] == "City Hospital, ER bay 3"
        assert place.json()["latitude"] == 18.52

        own_alerts = client.get("/api/v1/me/emergency-alerts", headers=owner).json()["alerts"]
        assert len(own_alerts) == 1
        assert own_alerts[0]["whose"] == "you"
        family_alerts = client.get("/api/v1/me/emergency-alerts", headers=family).json()["alerts"]
        assert [a["event_id"] for a in family_alerts] == [public["event_id"]]
        assert family_alerts[0]["whose"] != "you"
        assert client.get("/api/v1/me/emergency-alerts", headers=stranger).json()["alerts"] == []

        denied = client.post(f"/api/v1/me/emergency-alerts/{public['event_id']}/ack", headers=stranger)
        assert denied.status_code == 404
        ack = client.post(f"/api/v1/me/emergency-alerts/{public['event_id']}/ack", headers=family)
        assert ack.status_code == 200, ack.text
        assert ack.json()["acknowledged"] is True


def test_rotate_link_and_family_opt_out(monkeypatch) -> None:
    with make_client(monkeypatch, AUTH_MODE="dev-jwt") as client:
        owner = _patient_headers(client, "PAT-000001")
        old = _token_from(client.get("/api/v1/me/emergency-card", headers=owner).json())
        rotated = client.post("/api/v1/me/emergency-card/rotate-link", headers=owner)
        assert rotated.status_code == 200, rotated.text
        new = _token_from(rotated.json())
        assert new != old
        assert client.get(f"/api/v1/emergency/{old}").status_code == 404
        assert client.get(f"/api/v1/emergency/{new}").status_code == 200

        off = client.patch("/api/v1/me/emergency-card", headers=owner, json={"alert_family": False})
        assert off.status_code == 200, off.text
        assert off.json()["alert_family"] is False
        reopened = client.get(f"/api/v1/emergency/{new}", headers={"User-Agent": "x"})
        assert reopened.json()["family_alerted"] is False


def test_bad_links_and_bad_places(monkeypatch) -> None:
    with make_client(monkeypatch, AUTH_MODE="dev-jwt") as client:
        assert client.get("/api/v1/emergency/short").status_code == 404
        assert client.get("/api/v1/emergency/" + "x" * 30).status_code == 404
        owner = _patient_headers(client, "PAT-000001")
        token = _token_from(client.get("/api/v1/me/emergency-card", headers=owner).json())
        event = client.get(f"/api/v1/emergency/{token}").json()["event_id"]
        half = client.post(
            f"/api/v1/emergency/{token}/events/{event}/place", json={"latitude": 10.0}
        )
        assert half.status_code == 422
        far = client.post(
            f"/api/v1/emergency/{token}/events/{event}/place",
            json={"latitude": 100.0, "longitude": 10.0},
        )
        assert far.status_code == 422
        missing = client.post(f"/api/v1/emergency/{token}/events/EMA-NOPE/place", json={})
        assert missing.status_code == 404
