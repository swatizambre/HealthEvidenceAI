"""Regression tests for still-open review items (audit, MRN, search scope)."""

from __future__ import annotations

from app.models import AuditEvent, Organization, Patient
from app.services.opd_ingest import _find_patient_by_external
from app.services.rag.pipeline import load_corpus
from sqlalchemy import select
from tests.conftest import make_client


def test_denied_chart_access_leaves_durable_audit(monkeypatch) -> None:
    with make_client(monkeypatch, AUTH_MODE="dev-jwt", ENFORCE_ORG_SCOPE="true") as client:
        session = client.app.state.session_factory()
        try:
            other = session.scalar(select(Organization).where(Organization.org_code == "ORG-000099"))
            if other is None:
                other = Organization(
                    org_code="ORG-000099",
                    name="Other Facility",
                    facility_type="clinic",
                    active=True,
                )
                session.add(other)
                session.flush()
            patient = session.scalar(select(Patient).where(Patient.patient_code == "PAT-000002"))
            assert patient is not None
            patient.org_id = other.id
            session.commit()
        finally:
            session.close()

        minted = client.post(
            "/api/v1/auth/dev-token",
            json={"subject": "staff-auditor", "roles": ["staff"], "org_code": "ORG-000001"},
        )
        assert minted.status_code == 200
        token = minted.json()["access_token"]
        denied = client.get(
            "/api/v1/patients/PAT-000002",
            headers={"Authorization": f"Bearer {token}"},
        )
        assert denied.status_code == 403

        check = client.app.state.session_factory()
        try:
            rows = list(
                check.scalars(
                    select(AuditEvent).where(
                        AuditEvent.action == "patient_scope_denied",
                        AuditEvent.resource_id == "PAT-000002",
                        AuditEvent.status == "denied",
                    )
                ).all()
            )
            assert rows, "denied chart access must leave a durable audit row"
        finally:
            check.close()


def test_external_mrn_does_not_merge_orphan_or_other_org(monkeypatch) -> None:
    with make_client(monkeypatch, AUTH_MODE="none") as client:
        session = client.app.state.session_factory()
        try:
            default = session.scalar(select(Organization).where(Organization.org_code == "ORG-000001"))
            other = session.scalar(select(Organization).where(Organization.org_code == "ORG-000002"))
            assert default is not None and other is not None
            # Orphan chart with MRN metadata via document would be skipped; direct unit check:
            orphan = session.scalar(select(Patient).where(Patient.patient_code == "PAT-000001"))
            assert orphan is not None
            orphan.org_id = None
            session.commit()
            assert _find_patient_by_external(session, "anything", org_id=default.id) is None

            # Other-org patient must not match even if metadata later points at same external id.
            other_patient = session.scalar(select(Patient).where(Patient.patient_code == "PAT-000002"))
            assert other_patient is not None
            other_patient.org_id = other.id
            session.commit()
            assert (
                _find_patient_by_external(session, "UHID-SHARED", org_id=default.id) is None
            )
        finally:
            session.close()


def test_load_corpus_scopes_to_patient_before_ranking(monkeypatch) -> None:
    with make_client(monkeypatch, AUTH_MODE="none") as client:
        session = client.app.state.session_factory()
        try:
            scoped = load_corpus(session, patient_code="PAT-000001")
            assert scoped
            assert all(row.patient_id == "PAT-000001" for row in scoped)
            full = load_corpus(session)
            assert len(full) >= len(scoped)
        finally:
            session.close()


def test_evidence_search_requires_patient_when_org_scope_on(monkeypatch) -> None:
    with make_client(monkeypatch, AUTH_MODE="dev-jwt", ENFORCE_ORG_SCOPE="true") as client:
        minted = client.post(
            "/api/v1/auth/dev-token",
            json={"subject": "searcher", "roles": ["staff"], "org_code": "ORG-000001"},
        )
        token = minted.json()["access_token"]
        response = client.post(
            "/api/v1/evidence/search",
            headers={"Authorization": f"Bearer {token}"},
            json={"query": "diabetes", "limit": 3},
        )
        assert response.status_code == 400
        assert response.json()["error_code"] == "PATIENT_ID_REQUIRED"
