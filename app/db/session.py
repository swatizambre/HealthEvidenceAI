"""Engine and session factory shared by SQLite and PostgreSQL."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from sqlalchemy import Engine, create_engine, event, text
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

from app.db.base import Base


def prepare_sqlite_path(database_url: str) -> None:
    """Create the parent directory for a file-backed SQLite URL."""
    if not database_url.startswith("sqlite:///"):
        return
    raw = database_url.removeprefix("sqlite:///")
    if raw in {"", ":memory:"}:
        return
    path = Path(raw)
    if path.parent and str(path.parent) not in {"", "."}:
        path.parent.mkdir(parents=True, exist_ok=True)


def _configure_sqlite(dbapi_connection: Any, connection_record: Any) -> None:
    del connection_record
    cursor = dbapi_connection.cursor()
    cursor.execute("PRAGMA foreign_keys=ON")
    cursor.execute("PRAGMA journal_mode=WAL")
    cursor.execute("PRAGMA busy_timeout=30000")
    cursor.execute("PRAGMA synchronous=NORMAL")
    cursor.close()


def create_db_engine(database_url: str) -> Engine:
    """Create an engine. Memory SQLite uses one shared connection."""
    kwargs: dict[str, Any] = {}
    if database_url.startswith("sqlite"):
        kwargs["connect_args"] = {
            "check_same_thread": False,
            "timeout": 30,
        }
        if database_url in {"sqlite://", "sqlite:///:memory:"} or database_url.endswith(":memory:"):
            kwargs["poolclass"] = StaticPool
    else:
        kwargs["pool_pre_ping"] = True
    engine = create_engine(database_url, **kwargs)
    if database_url.startswith("sqlite"):
        event.listen(engine, "connect", _configure_sqlite)
    return engine


def create_session_factory(engine: Engine) -> sessionmaker[Session]:
    return sessionmaker(bind=engine, autoflush=False, autocommit=False, expire_on_commit=False)


def init_db(engine: Engine) -> None:
    """Create tables. Import models so they register on the metadata."""
    from app import models  # noqa: F401
    from app.core.config import get_settings
    from app.core.exceptions import AppError

    Base.metadata.create_all(bind=engine)
    ensure_authorization_case_columns(engine)
    ensure_patient_org_column(engine)
    ensure_patient_abha_column(engine)
    # Prefer Alembic for shared Postgres; SQLite soft-ALTER + create_all cover laptop/tests.
    url = str(engine.url)
    if url.startswith("sqlite"):
        return
    settings = get_settings()
    try:
        run_alembic_upgrade()
    except Exception as exc:
        if settings.alembic_required():
            raise AppError(
                "ALEMBIC_UPGRADE_FAILED",
                f"Database migration failed and this environment requires Alembic: {exc}",
                503,
            ) from exc


def _alembic_config() -> Any:
    from alembic.config import Config

    root = Path(__file__).resolve().parents[2]
    cfg = Config(str(root / "alembic.ini"))
    cfg.set_main_option("script_location", str(root / "alembic"))
    return cfg


def run_alembic_upgrade() -> None:
    """Apply pending Alembic revisions (no-op when already current)."""
    from alembic import command

    command.upgrade(_alembic_config(), "head")


def alembic_revision_status(engine: Engine) -> tuple[set[str], set[str]]:
    """Return (revisions stamped in the database, head revisions in alembic/versions)."""
    from alembic.runtime.migration import MigrationContext
    from alembic.script import ScriptDirectory

    heads = set(ScriptDirectory.from_config(_alembic_config()).get_heads())
    with engine.connect() as connection:
        current = set(MigrationContext.configure(connection).get_current_heads())
    return current, heads


def ensure_authorization_case_columns(engine: Engine) -> None:
    """Soft-migrate lifecycle columns for existing SQLite databases."""
    if not str(engine.url).startswith("sqlite"):
        return
    with engine.begin() as connection:
        rows = connection.execute(text("PRAGMA table_info(authorization_cases)")).fetchall()
        names = {str(row[1]) for row in rows}
        if "status" not in names:
            connection.execute(
                text(
                    "ALTER TABLE authorization_cases "
                    "ADD COLUMN status VARCHAR(32) DEFAULT 'queued'"
                )
            )
        if "last_run_id" not in names:
            connection.execute(
                text("ALTER TABLE authorization_cases ADD COLUMN last_run_id VARCHAR(64)")
            )
        if "lifecycle_note" not in names:
            connection.execute(
                text(
                    "ALTER TABLE authorization_cases "
                    "ADD COLUMN lifecycle_note VARCHAR(500) DEFAULT ''"
                )
            )
        if "prep_started_at" not in names:
            connection.execute(
                text("ALTER TABLE authorization_cases ADD COLUMN prep_started_at DATETIME")
            )
        if "review_ready_at" not in names:
            connection.execute(
                text("ALTER TABLE authorization_cases ADD COLUMN review_ready_at DATETIME")
            )
        if "org_id" not in names:
            connection.execute(
                text("ALTER TABLE authorization_cases ADD COLUMN org_id VARCHAR(36)")
            )
        if "assigned_to" not in names:
            connection.execute(
                text("ALTER TABLE authorization_cases ADD COLUMN assigned_to VARCHAR(120)")
            )
        # India TPA desk fields (see alembic 20261013_0004).
        for name, ddl in _TPA_DESK_CASE_COLUMNS:
            if name not in names:
                connection.execute(
                    text(f"ALTER TABLE authorization_cases ADD COLUMN {name} {ddl}")
                )


_TPA_DESK_CASE_COLUMNS: tuple[tuple[str, str], ...] = (
    ("payer_type", "VARCHAR(16)"),
    ("insurer_name", "VARCHAR(160) DEFAULT ''"),
    ("tpa_name", "VARCHAR(160) DEFAULT ''"),
    ("policy_number", "VARCHAR(64) DEFAULT ''"),
    ("admission_type", "VARCHAR(16) DEFAULT 'planned'"),
    ("admitted_at", "DATETIME"),
    ("expected_discharge_at", "DATETIME"),
    ("treating_doctor", "VARCHAR(160) DEFAULT ''"),
    ("provisional_diagnosis", "VARCHAR(300) DEFAULT ''"),
    ("icd10_code", "VARCHAR(16) DEFAULT ''"),
    ("proposed_treatment", "VARCHAR(300) DEFAULT ''"),
    ("estimated_cost_inr", "INTEGER"),
    ("approved_amount_inr", "INTEGER"),
    ("stage", "VARCHAR(32) DEFAULT 'draft'"),
    ("sent_at", "DATETIME"),
    ("decision_due_at", "DATETIME"),
    ("approved_at", "DATETIME"),
    ("discharge_requested_at", "DATETIME"),
    ("final_due_at", "DATETIME"),
    ("revised_estimate_inr", "INTEGER"),
    ("enhancement_reason", "VARCHAR(500) DEFAULT ''"),
    ("enhancement_requested_at", "DATETIME"),
    ("enhancement_count", "INTEGER DEFAULT 0"),
    ("discharge_override_reason", "VARCHAR(500) DEFAULT ''"),
    ("closed_at", "DATETIME"),
    ("cost_breakdown_inr", "JSON"),
    ("form_extra", "JSON"),
)


def ensure_patient_org_column(engine: Engine) -> None:
    """Soft-migrate patient.org_id for existing SQLite databases."""
    if not str(engine.url).startswith("sqlite"):
        return
    with engine.begin() as connection:
        rows = connection.execute(text("PRAGMA table_info(patients)")).fetchall()
        names = {str(row[1]) for row in rows}
        if "org_id" not in names:
            connection.execute(text("ALTER TABLE patients ADD COLUMN org_id VARCHAR(36)"))


def ensure_patient_abha_column(engine: Engine) -> None:
    """Soft-migrate patient.abha_id for existing SQLite databases."""
    if not str(engine.url).startswith("sqlite"):
        return
    with engine.begin() as connection:
        rows = connection.execute(text("PRAGMA table_info(patients)")).fetchall()
        names = {str(row[1]) for row in rows}
        if "abha_id" not in names:
            connection.execute(text("ALTER TABLE patients ADD COLUMN abha_id VARCHAR(64)"))


def reset_database(engine: Engine) -> None:
    """Drop and recreate the schema. Used by the deterministic seed command."""
    from app import models  # noqa: F401

    Base.metadata.drop_all(bind=engine)
    Base.metadata.create_all(bind=engine)


def check_connection(engine: Engine) -> None:
    with engine.connect() as connection:
        connection.execute(text("SELECT 1"))
