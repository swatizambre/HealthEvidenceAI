"""Emergency card public link and access events (family alerts).

Revision ID: 20261015_0007
Revises: 20261015_0006
Create Date: 2026-10-15
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "20261015_0007"
down_revision: str | None = "20261015_0006"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_TZ = sa.DateTime(timezone=True)


def upgrade() -> None:
    # init_db runs create_all before Alembic, so each step checks what already exists.
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    tables = set(inspector.get_table_names())

    if "emergency_profiles" in tables:
        cols = {c["name"] for c in inspector.get_columns("emergency_profiles")}
        if "public_token" not in cols:
            op.add_column(
                "emergency_profiles", sa.Column("public_token", sa.String(length=48), nullable=True)
            )
        if "alert_family" not in cols:
            op.add_column(
                "emergency_profiles",
                sa.Column("alert_family", sa.Boolean(), server_default=sa.text("true")),
            )
        indexes = {ix["name"] for ix in inspector.get_indexes("emergency_profiles")}
        if "ix_emergency_profiles_public_token" not in indexes:
            op.create_index(
                "ix_emergency_profiles_public_token",
                "emergency_profiles",
                ["public_token"],
                unique=True,
            )

    if "emergency_access_events" not in tables:
        op.create_table(
            "emergency_access_events",
            sa.Column("id", sa.String(length=36), primary_key=True),
            sa.Column("created_at", _TZ, nullable=False),
            sa.Column("updated_at", _TZ, nullable=False),
            sa.Column("event_code", sa.String(length=32), nullable=False),
            sa.Column(
                "patient_id",
                sa.String(length=36),
                sa.ForeignKey("patients.id", ondelete="CASCADE"),
                nullable=False,
            ),
            sa.Column("opened_at", _TZ, nullable=False),
            sa.Column("place_note", sa.String(length=200), server_default=""),
            sa.Column("latitude", sa.Float(), nullable=True),
            sa.Column("longitude", sa.Float(), nullable=True),
            sa.Column("user_agent", sa.String(length=160), server_default=""),
            sa.Column("acknowledged_at", _TZ, nullable=True),
            sa.Column("acknowledged_by", sa.String(length=120), server_default=""),
        )
        op.create_index(
            "ix_emergency_access_events_event_code",
            "emergency_access_events",
            ["event_code"],
            unique=True,
        )
        op.create_index(
            "ix_emergency_access_events_patient_id", "emergency_access_events", ["patient_id"]
        )
        op.create_index(
            "ix_emergency_access_events_opened_at", "emergency_access_events", ["opened_at"]
        )


def downgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    tables = set(inspector.get_table_names())
    if "emergency_access_events" in tables:
        op.drop_table("emergency_access_events")
    if "emergency_profiles" in tables:
        indexes = {ix["name"] for ix in inspector.get_indexes("emergency_profiles")}
        if "ix_emergency_profiles_public_token" in indexes:
            op.drop_index("ix_emergency_profiles_public_token", table_name="emergency_profiles")
        cols = {c["name"] for c in inspector.get_columns("emergency_profiles")}
        with op.batch_alter_table("emergency_profiles") as batch:
            if "public_token" in cols:
                batch.drop_column("public_token")
            if "alert_family" in cols:
                batch.drop_column("alert_family")
