"""Multi-agent critic, pathway, readiness, and query expansion."""

from __future__ import annotations

from app.services.critic import calibrate_confidence, critic_reflect
from app.services.pathway import build_documentation_pathway
from app.services.query_rewrite import expand_retrieval_queries
from app.services.readiness import build_readiness_scorecard


def test_expand_retrieval_queries_adds_angles() -> None:
    queries = expand_retrieval_queries("MRI for disc disease after physical therapy")
    assert queries
    assert queries[0].startswith("MRI")
    joined = " ".join(queries).lower()
    assert "imaging" in joined or "radiology" in joined or "therapy" in joined


def test_critic_rejects_uncited_support() -> None:
    outcome = critic_reflect(
        [
            {
                "criterion_id": "C1",
                "criterion": "Needs imaging",
                "status": "SUPPORTED",
                "evidence": [],
                "reason": "claimed",
            }
        ]
    )
    assert outcome["criterion_results"][0]["status"] == "UNKNOWN"
    assert outcome["criterion_results"][0]["confidence"] is not None
    assert outcome["critic_notes"]


def test_calibrate_confidence_bounds() -> None:
    assert 0 < calibrate_confidence("SUPPORTED", 2, "ok") <= 1
    assert calibrate_confidence("SUPPORTED", 0, "") < 0.5


def test_pathway_orders_conflicts_first() -> None:
    pathway = build_documentation_pathway(
        criterion_results=[
            {
                "criterion_id": "C1",
                "criterion": "Lab A1c",
                "status": "MISSING",
                "reason": "missing labs",
            }
        ],
        missing_evidence=[],
        contradictions=[{"criterion": "C0", "description": "conflict"}],
        documentation_risk="high",
    )
    assert pathway["pathway"][0]["title"].lower().startswith("resolve")
    assert pathway["gap_count"] == 1


def test_readiness_scorecard_high_when_conflicts() -> None:
    card = build_readiness_scorecard(
        readiness_percent=90,
        criterion_results=[{"status": "SUPPORTED", "confidence": 0.9}],
        contradictions=[{"x": 1}],
        documentation_risk="high",
        critic_notes=["thin"],
    )
    assert card["documentation_risk"] == "high"
    assert card["handoff_readiness_percent"] < 90
    assert "not a coverage" in card["disclaimer"].lower()
