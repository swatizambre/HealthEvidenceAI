"""Reproducible hybrid RAG evaluation (not clinical accuracy)."""

from __future__ import annotations

import json
import tempfile
from pathlib import Path

from app.db.session import create_db_engine, create_session_factory, init_db, prepare_sqlite_path
from app.services.rag.pipeline import hybrid_search
from app.services.seed import persist_dataset

ROOT = Path(__file__).resolve().parent


def main() -> int:
    cases = json.loads((ROOT / "rag_cases.json").read_text(encoding="utf-8"))["cases"]
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
            hits_ok = 0
            citation_ok = 0
            empty_ok = 0
            total = 0
            for case in cases:
                total += 1
                results = hybrid_search(
                    session,
                    query=case["query"],
                    patient_code=case.get("patient_id"),
                    limit=5,
                )
                if case.get("adversarial"):
                    if not results:
                        empty_ok += 1
                        hits_ok += 1
                    continue
                if results:
                    hits_ok += 1
                    prefix = case.get("expected_document_prefix")
                    if prefix and results[0].document_id.startswith(prefix):
                        citation_ok += 1
                    if results[0].chunk_id:
                        citation_ok += 0  # counted via document prefix
                    if all(hit.chunk_id for hit in results):
                        citation_ok += 1
            recall = hits_ok / total if total else 0.0
            citation = citation_ok / max(total, 1)
            print("RAG evaluation (engineering metrics only; not clinical accuracy)")
            print(f"cases={total} retrieval_hit_rate={recall:.2f} citation_signal={citation:.2f}")
            print(f"adversarial_empty_ok={empty_ok}")
            return 0 if recall >= 0.5 else 1
        finally:
            session.close()
            engine.dispose()


if __name__ == "__main__":
    raise SystemExit(main())
