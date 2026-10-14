"""Create consent_records and data_subject_requests tables.

Revision ID: 20261013_0003
Revises: 20261009_0002
Create Date: 2026-10-13
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "20261013_0003"
down_revision: str | None = "20261009_0002"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    bind = op.get_bind()
    tables = set(sa.inspect(bind).get_table_names())
    if "consent_records" not in tables:
        op.create_table(
            "consent_records",
            sa.Column("id", sa.String(length=36), primary_key=True),
            sa.Column("consent_code", sa.String(length=32), nullable=False),
            sa.Column(
                "patient_id",
                sa.String(length=36),
                sa.ForeignKey("patients.id", ondelete="CASCADE"),
                nullable=False,
            ),
            sa.Column(
                "org_id",
                sa.String(length=36),
                sa.ForeignKey("organizations.id", ondelete="SET NULL"),
                nullable=True,
            ),
            sa.Column("purpose", sa.String(length=40), nullable=False),
            sa.Column("scope", sa.Text(), nullable=False, server_default=""),
            sa.Column("method", sa.String(length=32), nullable=False),
            sa.Column("language", sa.String(length=16), nullable=False, server_default="en"),
            sa.Column("notice_version", sa.String(length=64), nullable=False),
            sa.Column("granted_by_name", sa.String(length=120), nullable=False),
            sa.Column("recorded_by", sa.String(length=120), nullable=False),
            sa.Column("granted_at", sa.DateTime(timezone=True), nullable=False),
            sa.Column("expires_at", sa.DateTime(timezone=True), nullable=True),
            sa.Column("revoked_at", sa.DateTime(timezone=True), nullable=True),
            sa.Column("revoked_reason", sa.String(length=500), nullable=False, server_default=""),
            sa.Column("revoked_by", sa.String(length=120), nullable=True),
            sa.Column("evidence_ref", sa.String(length=64), nullable=False, server_default=""),
            sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        )
        op.create_index(
            "ix_consent_records_consent_code", "consent_records", ["consent_code"], unique=True
        )
        op.create_index("ix_consent_records_patient_id", "consent_records", ["patient_id"])
        op.create_index("ix_consent_records_org_id", "consent_records", ["org_id"])
        op.create_index("ix_consent_records_purpose", "consent_records", ["purpose"])
    if "data_subject_requests" not in tables:
        op.create_table(
            "data_subject_requests",
            sa.Column("id", sa.String(length=36), primary_key=True),
            sa.Column("request_code", sa.String(length=32), nullable=False),
            sa.Column(
                "patient_id",
                sa.String(length=36),
                sa.ForeignKey("patients.id", ondelete="CASCADE"),
                nullable=False,
            ),
            sa.Column(
                "org_id",
                sa.String(length=36),
                sa.ForeignKey("organizations.id", ondelete="SET NULL"),
                nullable=True,
            ),
            sa.Column("request_type", sa.String(length=32), nullable=False),
            sa.Column("details", sa.Text(), nullable=False, server_default=""),
            sa.Column("status", sa.String(length=16), nullable=False, server_default="open"),
            sa.Column("submitted_by", sa.String(length=120), nullable=False, server_default=""),
            sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
            sa.Column("resolved_at", sa.DateTime(timezone=True), nullable=True),
            sa.Column("resolution_note", sa.Text(), nullable=False, server_default=""),
            sa.Column("outcome", sa.String(length=40), nullable=False, server_default=""),
            sa.Column("handled_by", sa.String(length=120), nullable=True),
        )
        op.create_index(
            "ix_data_subject_requests_request_code",
            "data_subject_requests",
            ["request_code"],
            unique=True,
        )
        op.create_index(
            "ix_data_subject_requests_patient_id", "data_subject_requests", ["patient_id"]
        )
        op.create_index("ix_data_subject_requests_org_id", "data_subject_requests", ["org_id"])
        op.create_index(
            "ix_data_subject_requests_request_type", "data_subject_requests", ["request_type"]
        )
        op.create_index("ix_data_subject_requests_status", "data_subject_requests", ["status"])


def downgrade() -> None:
    bind = op.get_bind()
    tables = set(sa.inspect(bind).get_table_names())
    if "data_subject_requests" in tables:
        op.drop_table("data_subject_requests")
    if "consent_records" in tables:
        op.drop_table("consent_records")
