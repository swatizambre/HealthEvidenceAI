"""Reproducible agent evaluation (engineering metrics only)."""

from __future__ import annotations

import json
import tempfile
from collections import Counter
from pathlib import Path

from app.agents.review import resume_review, review_authorization
from app.db.session import create_db_engine, create_session_factory, init_db, prepare_sqlite_path
from app.mcp.tools import call_tool
from app.schemas.api import AuthorizationReviewRequest, HumanReviewResumeRequest
from app.services.permissions import authorize_permission
from app.services.seed import persist_dataset
from app.services.synthetic import get_demo_procedure

ROOT = Path(__file__).resolve().parent


def main() -> int:
    cases = json.loads((ROOT / "agent_cases.json").read_text(encoding="utf-8"))["cases"]
    passed = 0
    with tempfile.TemporaryDirectory() as directory:
        url = f"sqlite:///{Path(directory).as_posix()}/eval.db"
        prepare_sqlite_path(url)
        engine = create_db_engine(url)
        init_db(engine)
        factory = create_session_factory(engine)
        session = factory()
        try:
            persist_dataset(session)
            session.commit()
            for case in cases:
                if case.get("expect_denied"):
                    decision = authorize_permission(case["agent"], "EVIDENCE_SEARCH")
                    if decision.allowed is False:
                        passed += 1
                        print(f"PASS {case['id']} permission_denied")
                    else:
                        print(f"FAIL {case['id']} expected denial")
                    continue
                result = review_authorization(
                    session,
                    AuthorizationReviewRequest(
                        patient_id=case["patient_id"],
                        policy_id=case["policy_id"],
                        procedure=get_demo_procedure(),
                        case_id=case.get("case_id"),
                    ),
                )
                if result.awaiting_human_review:
                    result = resume_review(
                        session,
                        result.run_id,
                        HumanReviewResumeRequest(
                            decision="acknowledged",
                            notes="eval senior sign-off",
                        ),
                    )
                counts = Counter(item.status for item in result.criteria)
                expected = case.get("expect_statuses") or {}
                ok = all(counts.get(k, 0) == v for k, v in expected.items())
                if case.get("expect_human_review") and not result.human_review_required:
                    ok = False
                if result.agent_trace:
                    ok = ok and True
                else:
                    ok = False
                # Tool path smoke: authorized search
                call_tool(
                    session,
                    tool_name="search_clinical_evidence",
                    agent="ClinicalEvidenceAgent",
                    arguments={"query": "evidence", "patient_id": case["patient_id"], "limit": 3},
                )
                if ok:
                    passed += 1
                    print(f"PASS {case['id']}")
                else:
                    print(f"FAIL {case['id']} counts={dict(counts)}")
            print(f"agent_eval passed={passed}/{len(cases)}")
            return 0 if passed == len(cases) else 1
        finally:
            session.close()
            engine.dispose()


if __name__ == "__main__":
    raise SystemExit(main())
