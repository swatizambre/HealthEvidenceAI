"""India rural↔urban facility taxonomy and desk guidance."""

from __future__ import annotations

from app.services.india_desk import (
    desk_subtitle,
    describe_india_desk,
    facility_catalog,
    facility_label,
    india_org_seeds,
)
from app.services.organizations import list_organizations, org_code_for_facility
from fastapi.testclient import TestClient


def test_facility_catalog_covers_rural_urban_ladder() -> None:
    ids = {item["id"] for item in facility_catalog()}
    assert {"phc", "chc", "taluk", "district", "multispecialty", "government"} <= ids
    assert facility_label("phc").startswith("PHC")
    assert "cashless" in desk_subtitle(role="staff", facility_type="multispecialty").lower()
    assert "referral" in desk_subtitle(role="senior_clinician", facility_type="phc").lower()


def test_india_org_seeds_and_mapping() -> None:
    seeds = india_org_seeds()
    assert any(item["facility_type"] == "phc" for item in seeds)
    assert org_code_for_facility("phc") == "ORG-000002"
    assert org_code_for_facility("district") == "ORG-000004"
    assert describe_india_desk()["market"] == "india"


def test_facilities_endpoint(client: TestClient) -> None:
    response = client.get("/api/v1/facilities")
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["market"] == "india"
    assert len(body["facilities"]) >= 6
    assert "phc" in body["referral_ladder"]
    assert "disclaimer" in body


def test_organizations_include_india_chain(client: TestClient) -> None:
    response = client.get("/api/v1/organizations")
    assert response.status_code == 200, response.text
    orgs = response.json()["organizations"]
    codes = {item["org_code"] for item in orgs}
    assert "ORG-000001" in codes
    assert "ORG-000002" in codes
    types = {item["facility_type"] for item in orgs}
    assert "phc" in types or "multispecialty" in types


def test_list_organizations_seeds_session() -> None:
    from app.db.session import create_db_engine, create_session_factory, init_db

    engine = create_db_engine("sqlite://")
    init_db(engine)
    factory = create_session_factory(engine)
    session = factory()
    try:
        rows = list_organizations(session)
        codes = {row.org_code for row in rows}
        assert {"ORG-000001", "ORG-000002", "ORG-000003", "ORG-000004"} <= codes
    finally:
        session.close()
        engine.dispose()
