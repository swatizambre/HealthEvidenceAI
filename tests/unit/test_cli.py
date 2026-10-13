"""Seed command and PostgreSQL engine configuration."""

from pathlib import Path

import pytest
from app.core.config import get_settings
from app.db.session import create_db_engine
from app.models import Patient
from app.services.seed import seed_command, seed_if_empty
from sqlalchemy import func, select
from sqlalchemy.orm import Session


def test_seed_command_populates_a_file_database(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    database = tmp_path / "seed.db"
    monkeypatch.setenv("DATABASE_URL", f"sqlite:///{database.as_posix()}")
    monkeypatch.setenv("LLM_PROVIDER", "ollama")
    monkeypatch.setenv("ENVIRONMENT", "test")
    monkeypatch.setenv("AUTH_MODE", "none")
    monkeypatch.setenv("IMAGING_BACKEND", "monai")
    get_settings.cache_clear()
    assert seed_command() == 0
    engine = create_db_engine(f"sqlite:///{database.as_posix()}")
    session = Session(engine)
    try:
        total = session.scalar(select(func.count()).select_from(Patient))
        assert total == 100
        assert seed_if_empty(session) is False
    finally:
        session.close()
        engine.dispose()
    get_settings.cache_clear()


def test_postgres_url_selects_the_postgres_dialect() -> None:
    engine = create_db_engine(
        "postgresql+psycopg://healthevidence:healthevidence@localhost:5432/healthevidence"
    )
    assert engine.dialect.name == "postgresql"
    engine.dispose()
