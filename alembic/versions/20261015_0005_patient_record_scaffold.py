"""Patient emergency card, shares, family stubs, abha_id.

Revision ID: 20261015_0005
Revises: 20261013_0004
Create Date: 2026-10-15
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "20261015_0005"
down_revision: str | None = "20261013_0004"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_TZ = sa.DateTime(timezone=True)


def upgrade() -> None:
    op.add_column("patients", sa.Column("abha_id", sa.String(length=64), nullable=True))
    op.create_index("ix_patients_abha_id", "patients", ["abha_id"])

    op.create_table(
        "emergency_profiles",
        sa.Column("id", sa.String(length=36), primary_key=True),
        sa.Column("created_at", _TZ, nullable=False),
        sa.Column("updated_at", _TZ, nullable=False),
        sa.Column("patient_id", sa.String(length=36), sa.ForeignKey("patients.id", ondelete="CASCADE"), nullable=False),
        sa.Column("blood_group", sa.String(length=16), server_default=""),
        sa.Column("implants", sa.Text(), server_default=""),
        sa.Column("emergency_contacts", sa.JSON(), nullable=True),
        sa.Column("notes", sa.Text(), server_default=""),
        sa.Column("show_on_lock_screen", sa.Boolean(), server_default=sa.text("true")),
    )
    op.create_index("ix_emergency_profiles_patient_id", "emergency_profiles", ["patient_id"], unique=True)

    op.create_table(
        "record_shares",
        sa.Column("id", sa.String(length=36), primary_key=True),
        sa.Column("created_at", _TZ, nullable=False),
        sa.Column("updated_at", _TZ, nullable=False),
        sa.Column("share_code", sa.String(length=32), nullable=False),
        sa.Column("token", sa.String(length=64), nullable=False),
        sa.Column("patient_id", sa.String(length=36), sa.ForeignKey("patients.id", ondelete="CASCADE"), nullable=False),
        sa.Column("label", sa.String(length=160), server_default=""),
        sa.Column("scopes", sa.JSON(), nullable=True),
        sa.Column("expires_at", _TZ, nullable=False),
        sa.Column("revoked_at", _TZ, nullable=True),
        sa.Column("created_by", sa.String(length=120), server_default=""),
        sa.Column("view_count", sa.Integer(), server_default="0"),
        sa.Column("last_viewed_at", _TZ, nullable=True),
    )
    op.create_index("ix_record_shares_share_code", "record_shares", ["share_code"], unique=True)
    op.create_index("ix_record_shares_token", "record_shares", ["token"], unique=True)
    op.create_index("ix_record_shares_patient_id", "record_shares", ["patient_id"])

    op.create_table(
        "care_relationships",
        sa.Column("id", sa.String(length=36), primary_key=True),
        sa.Column("created_at", _TZ, nullable=False),
        sa.Column("updated_at", _TZ, nullable=False),
        sa.Column("relationship_code", sa.String(length=32), nullable=False),
        sa.Column("patient_id", sa.String(length=36), sa.ForeignKey("patients.id", ondelete="CASCADE"), nullable=False),
        sa.Column("related_display_name", sa.String(length=160), nullable=False),
        sa.Column("relationship_type", sa.String(length=32), server_default="caregiver"),
        sa.Column("related_patient_code", sa.String(length=32), nullable=True),
        sa.Column("access_level", sa.String(length=32), server_default="view"),
    )
    op.create_index(
        "ix_care_relationships_relationship_code",
        "care_relationships",
        ["relationship_code"],
        unique=True,
    )
    op.create_index("ix_care_relationships_patient_id", "care_relationships", ["patient_id"])


def downgrade() -> None:
    op.drop_table("care_relationships")
    op.drop_table("record_shares")
    op.drop_table("emergency_profiles")
    op.drop_index("ix_patients_abha_id", table_name="patients")
    op.drop_column("patients", "abha_id")
