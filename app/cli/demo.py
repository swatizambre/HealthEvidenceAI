"""Evidence review demo using the configured LLM provider."""

from __future__ import annotations

import tempfile
from collections import Counter
from pathlib import Path

from app.agents.llm import build_llm
from app.agents.review import resume_review, review_authorization
from app.core.config import get_settings
from app.core.exceptions import LLMUnavailable
from app.core.safety import contains_autonomous_decision
from app.db.session import (
    check_connection,
    create_db_engine,
    create_session_factory,
    init_db,
    prepare_sqlite_path,
)
from app.schemas.api import (
    AuthorizationReviewRequest,
    AuthorizationReviewResponse,
    HumanReviewResumeRequest,
)
from app.services.seed import persist_dataset
from app.services.synthetic import DEMO_CASE, DEMO_PATIENT, DEMO_POLICY, get_demo_procedure

_EXPECTED = {"SUPPORTED": 5, "NOT_SUPPORTED": 0, "MISSING": 0, "UNKNOWN": 0}


def format_demo(result: AuthorizationReviewResponse) -> str:
    counts: Counter[str] = Counter(item.status for item in result.criteria)
    review = "YES" if result.human_review_required else "NO"
    lines = [
        "=========================================",
        "HEALTHEVIDENCE AI — EVIDENCE REVIEW DEMO",
        "=========================================",
        "",
        f"Patient: {result.patient_id}",
        f"Authorization: {result.case_id}",
        f"Procedure: {result.procedure}",
        f"Policy: {result.policy_id}",
        f"Run: {result.run_id}",
        f"LLM: {get_settings().llm_provider}/{get_settings().model_for_provider()}",
        "",
        "Agent trace:",
    ]
    for step in result.agent_trace:
        lines.append(f"  - {step.agent} / {step.node} ({step.detail or step.status})")
    lines.extend(
        [
            "",
            f"Criteria evaluated: {len(result.criteria)}",
            "",
            f"{'SUPPORTED:':<15}{counts['SUPPORTED']}",
            f"{'NOT_SUPPORTED:':<15}{counts['NOT_SUPPORTED']}",
            f"{'MISSING:':<15}{counts['MISSING']}",
            f"{'UNKNOWN:':<15}{counts['UNKNOWN']}",
            "",
            f"Evidence coverage: {result.evidence_coverage}",
            "",
            f"Human review required: {review}",
            f"Report: {result.report_summary[:160]}",
            "",
            "Safety:",
            "Synthetic data: YES",
            "Autonomous clinical decision: NO",
            "",
            "=========================================",
            "DEMO COMPLETE",
            "=========================================",
        ]
    )
    return "\n".join(lines)


def run_demo() -> int:
    settings = get_settings()
    try:
        llm = build_llm(settings)
        # Smoke the provider before seeding a full DB.
        _ = llm.complete_report("ping", ["synthetic evidence context"])
    except LLMUnavailable as exc:
        print(f"Live LLM unavailable ({settings.llm_provider}): {exc.message}")
        print("Set LLM_PROVIDER=local (default), or start Ollama / set Gemini/OpenAI/Anthropic credentials.")
        return 1

    with tempfile.TemporaryDirectory() as directory:
        database = Path(directory) / "demo.db"
        url = f"sqlite:///{database.as_posix()}"
        prepare_sqlite_path(url)
        engine = create_db_engine(url)
        try:
            check_connection(engine)
            init_db(engine)
            factory = create_session_factory(engine)
            session = factory()
            try:
                counts = persist_dataset(session)
                session.commit()
                if counts["patients"] < 100:
                    print("Seed verification failed.")
                    return 1
                result = review_authorization(
                    session,
                    AuthorizationReviewRequest(
                        patient_id=DEMO_PATIENT,
                        policy_id=DEMO_POLICY,
                        procedure=get_demo_procedure(),
                        case_id=DEMO_CASE,
                    ),
                )
                if result.awaiting_human_review:
                    result = resume_review(
                        session,
                        result.run_id,
                        HumanReviewResumeRequest(
                            decision="acknowledged",
                            notes="cli demo senior sign-off",
                        ),
                    )
            finally:
                session.close()
        finally:
            engine.dispose()
    print(
        f"Service check: database ok, LLM provider ok ({settings.llm_provider}), review graph ok"
    )
    print(format_demo(result))
    observed = Counter(item.status for item in result.criteria)
    counted = {
        "SUPPORTED": observed["SUPPORTED"],
        "NOT_SUPPORTED": observed["NOT_SUPPORTED"],
        "MISSING": observed["MISSING"],
        "UNKNOWN": observed["UNKNOWN"],
    }
    if counted != _EXPECTED:
        print("Deterministic demo case returned unexpected criterion counts.")
        return 1
    if result.missing_evidence:
        print("Complete live sample should not report missing evidence.")
        return 1
    if result.human_review_required or result.evidence_coverage != "COMPLETE":
        print("Complete live sample should not require human review.")
        return 1
    if result.review_type != "evidence_review":
        return 1
    if contains_autonomous_decision(result.model_dump(mode="json")):
        print("Demo output contained an autonomous clinical decision.")
        return 1
    supported = [item for item in result.criteria if item.status == "SUPPORTED"]
    if not supported or any(not item.evidence for item in supported):
        print("Supported criteria were missing evidence.")
        return 1
    if not result.agent_trace:
        print("Agent trace missing from demo.")
        return 1
    return 0


def main() -> None:
    raise SystemExit(run_demo())


if __name__ == "__main__":
    main()
