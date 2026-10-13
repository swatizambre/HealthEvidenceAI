"""Persist the deterministic synthetic dataset."""

from __future__ import annotations

import logging

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.db.session import (
    check_connection,
    create_db_engine,
    create_session_factory,
    prepare_sqlite_path,
    reset_database,
)
from app.models import Patient
from app.services.indexing import index_document
from app.services.synthetic import SyntheticDataset, build_dataset

logger = logging.getLogger("healthevidence.seed")


def persist_dataset(session: Session, dataset: SyntheticDataset | None = None) -> dict[str, int]:
    """Insert a dataset and index every document. The caller commits."""
    from app.services.organizations import ensure_pilot_organizations

    data = dataset or build_dataset()
    org, secondary = ensure_pilot_organizations(session)
    for index, patient in enumerate(data.patients):
        if getattr(patient, "org_id", None) is None:
            # Keep early personas on primary org; a later slice on secondary for isolation demos.
            patient.org_id = secondary.id if index >= 7 and index % 7 == 0 else org.id
    for case in data.cases:
        if getattr(case, "org_id", None) is None:
            # Inherit patient org when possible; else primary.
            patient_org = next(
                (p.org_id for p in data.patients if p.id == case.patient_id),
                org.id,
            )
            case.org_id = patient_org or org.id
        if getattr(case, "prep_started_at", None) is None:
            case.prep_started_at = getattr(case, "created_at", None)
    session.add_all(data.patients)
    session.flush()
    session.add_all(data.documents)
    session.flush()
    session.add_all(data.policies)
    session.flush()
    session.add_all(data.criteria)
    session.add_all(data.notes)
    session.add_all(data.labs)
    session.add_all(data.medications)
    session.add_all(data.procedures)
    session.add_all(data.imaging_studies)
    session.add_all(data.claims)
    session.add_all(data.cases)
    session.flush()
    chunk_count = 0
    for document in data.documents:
        chunk_count += len(index_document(session, document))
    session.flush()
    return {
        "patients": len(data.patients),
        "notes": len(data.notes),
        "labs": len(data.labs),
        "medications": len(data.medications),
        "procedures": len(data.procedures),
        "imaging_studies": len(data.imaging_studies),
        "claims": len(data.claims),
        "policies": len(data.policies),
        "criteria": len(data.criteria),
        "documents": len(data.documents),
        "cases": len(data.cases),
        "chunks": chunk_count,
        "organizations": 2,
    }


def seed_if_empty(session: Session) -> bool:
    from app.services.organizations import ensure_pilot_organizations

    ensure_pilot_organizations(session)
    existing = session.scalar(select(func.count()).select_from(Patient)) or 0
    if int(existing) > 0:
        session.commit()
        return False
    counts = persist_dataset(session)
    session.commit()
    logger.info(
        "synthetic_dataset_ready patients=%s policies=%s documents=%s",
        counts["patients"],
        counts["policies"],
        counts["documents"],
    )
    return True


def seed_command() -> int:
    """Reset the configured database and load the synthetic dataset."""
    from app.core.config import get_settings

    settings = get_settings()
    prepare_sqlite_path(settings.database_url)
    engine = create_db_engine(settings.database_url)
    try:
        check_connection(engine)
        reset_database(engine)
        factory = create_session_factory(engine)
        session = factory()
        try:
            counts = persist_dataset(session)
            session.commit()
            print("Synthea sample loaded. Display names are synthetic. Contact identifiers were not stored.")
            for key in (
                "patients",
                "notes",
                "labs",
                "medications",
                "policies",
                "criteria",
                "imaging_studies",
                "claims",
                "documents",
                "chunks",
            ):
                print(f"{key}: {counts[key]}")
        except Exception:
            session.rollback()
            raise
        finally:
            session.close()
    finally:
        engine.dispose()
    return 0
