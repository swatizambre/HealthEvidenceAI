"""verify_evidence node: cited chunks must resolve to stored text that affirms the claim."""

from __future__ import annotations

from collections.abc import Iterator
from datetime import date
from typing import Any

import pytest
from app.agents.nodes import critic_reflect_node, verify_evidence
from app.core.config import get_settings
from app.services.citation_check import DOWNGRADE_REASON
from sqlalchemy.orm import Session


@pytest.fixture
def session() -> Iterator[Session]:
    from app.db.session import create_db_engine, create_session_factory, init_db
    from app.models import Document, DocumentChunk, Patient

    engine = create_db_engine("sqlite://")
    init_db(engine)
    db = create_session_factory(engine)()
    patient = Patient(
        patient_code="PAT-CITE-1",
        synthetic_name="Citation Test",
        birth_date=date(1970, 1, 1),
        sex="female",
        conditions=[],
    )
    other = Patient(
        patient_code="PAT-CITE-2",
        synthetic_name="Other Patient",
        birth_date=date(1971, 1, 1),
        sex="male",
        conditions=[],
    )
    db.add_all([patient, other])
    db.flush()
    for code, owner, text in [
        ("DOC-CITE-1", patient, "Known diabetes on metformin."),
        ("DOC-CITE-2", patient, "Mother has diabetes."),
        ("DOC-CITE-3", other, "Known diabetes on metformin."),
    ]:
        doc = Document(
            document_code=code,
            patient_id=owner.id,
            document_type="clinical_note",
            source="test",
            content=text,
            document_metadata={},
        )
        db.add(doc)
        db.flush()
        db.add(DocumentChunk(chunk_code=f"{code}-01", document_id=doc.id, chunk_index=0, content=text))
    db.commit()
    try:
        yield db
    finally:
        db.close()
        engine.dispose()


def _state(chunk_id: str, document_id: str) -> dict[str, Any]:
    return {
        "run_id": "RUN-CITE",
        "trace_id": "TRACE-CITE",
        "patient_id": "PAT-CITE-1",
        "criteria": [
            {
                "criterion_id": "CRIT-DM",
                "description": "Diabetes is documented.",
                "rule": {"type": "keyword", "required_any": ["diabetes"], "negation_any": []},
            }
        ],
        "evidence": [],
        "criterion_results": [
            {
                "criterion_id": "CRIT-DM",
                "criterion": "Diabetes is documented.",
                "status": "SUPPORTED",
                "evidence": [
                    {
                        "document_id": document_id,
                        "chunk_id": chunk_id,
                        "source": "clinical_note",
                        "text_reference": "model quote",
                    }
                ],
                "reason": "AI check: documented.",
            }
        ],
        "human_review_required": False,
    }


def test_supported_citation_from_db_passes(session: Session) -> None:
    out = verify_evidence(_state("DOC-CITE-1-01", "DOC-CITE-1"), session, get_settings())
    assert out["criterion_results"][0]["status"] == "SUPPORTED"
    assert out["human_review_required"] is False
    assert "passed=1" in out["agent_trace"][0]["detail"]


def test_family_history_citation_downgrades(session: Session) -> None:
    state = _state("DOC-CITE-2-01", "DOC-CITE-2")
    out = verify_evidence(state, session, get_settings())
    item = out["criterion_results"][0]
    assert item["status"] == "UNKNOWN"
    assert item["reason"] == DOWNGRADE_REASON
    assert out["human_review_required"] is True
    assert "citation_unsupported:CRIT-DM" in out["errors"]
    assert "downgraded=1" in out["agent_trace"][0]["detail"]
    # The critic keeps the citation note alongside its own.
    critic = critic_reflect_node({**state, **out}, session, get_settings())
    assert any("did not support" in note for note in critic["critic_notes"])


def test_other_patients_chunk_does_not_resolve(session: Session) -> None:
    out = verify_evidence(_state("DOC-CITE-3-01", "DOC-CITE-3"), session, get_settings())
    item = out["criterion_results"][0]
    assert item["status"] == "UNKNOWN"
    assert item["evidence"] == []
    assert "unresolved=1" in out["agent_trace"][0]["detail"]


def test_retrieved_hit_text_resolves_without_db(session: Session) -> None:
    state = _state("HIT-1", "DOC-HIT")
    state["evidence"] = [
        {"chunk_id": "HIT-1", "document_id": "DOC-HIT", "content": "Type 2 diabetes, no complications."}
    ]
    out = verify_evidence(state, session, get_settings())
    assert out["criterion_results"][0]["status"] == "SUPPORTED"
