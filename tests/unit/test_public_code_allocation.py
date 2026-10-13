"""Public code allocation: SQLite plain read, PostgreSQL per-prefix advisory lock."""

from __future__ import annotations

from datetime import date
from typing import Any

from app.db.base import Base
from app.db.repository import next_public_code
from app.db.session import create_db_engine, create_session_factory
from app.models import Patient


def _sqlite_session() -> Any:
    from app import models  # noqa: F401 — register tables

    engine = create_db_engine("sqlite://")
    Base.metadata.create_all(bind=engine)
    return create_session_factory(engine)()


def test_next_public_code_sqlite_increments_max_without_locking() -> None:
    session = _sqlite_session()
    try:
        assert next_public_code(session, Patient.patient_code, "PAT") == "PAT-000001"
        for code in ("PAT-000001", "PAT-000007", "OTHER-000099"):
            session.add(
                Patient(
                    patient_code=code,
                    synthetic_name="Synthetic Person",
                    birth_date=date(1980, 1, 1),
                    sex="female",
                    conditions=[],
                )
            )
        session.flush()
        assert next_public_code(session, Patient.patient_code, "PAT") == "PAT-000008"
        assert next_public_code(session, Patient.patient_code, "OTHER") == "OTHER-000100"
    finally:
        session.close()


class _FakeDialect:
    name = "postgresql"


class _FakeBind:
    dialect = _FakeDialect()


class _FakeScalars:
    def __init__(self, values: list[str]) -> None:
        self._values = values

    def all(self) -> list[str]:
        return self._values


class _FakePostgresSession:
    def __init__(self, values: list[str]) -> None:
        self.values = values
        self.executed: list[tuple[str, dict[str, Any]]] = []
        self.scalar_statements: list[str] = []

    def get_bind(self) -> _FakeBind:
        return _FakeBind()

    def execute(self, statement: Any, params: dict[str, Any] | None = None) -> None:
        self.executed.append((str(statement), dict(params or {})))

    def scalars(self, statement: Any) -> _FakeScalars:
        self.scalar_statements.append(str(statement).upper())
        return _FakeScalars(self.values)


def test_next_public_code_postgres_takes_advisory_lock_before_read() -> None:
    session = _FakePostgresSession(["NOTE-000041", "NOTE-000042"])
    code = next_public_code(session, Patient.patient_code, "NOTE")  # type: ignore[arg-type]
    assert code == "NOTE-000043"
    assert len(session.executed) == 1
    sql, params = session.executed[0]
    assert "pg_advisory_xact_lock(hashtext(:prefix))" in sql
    assert params == {"prefix": "NOTE"}
    # No row-level FOR SHARE / FOR UPDATE on the whole column anymore.
    assert session.scalar_statements
    assert all("FOR SHARE" not in stmt and "FOR UPDATE" not in stmt for stmt in session.scalar_statements)
