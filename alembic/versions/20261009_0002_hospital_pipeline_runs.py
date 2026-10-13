"""Create hospital_pipeline_runs table.

Revision ID: 20261009_0002
Revises: 20261009_0001
Create Date: 2026-10-09
"""

from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "20261009_0002"
down_revision: Union[str, None] = "20261009_0001"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    if "hospital_pipeline_runs" in inspector.get_table_names():
        return
    op.create_table(
        "hospital_pipeline_runs",
        sa.Column("id", sa.String(length=36), primary_key=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("run_id", sa.String(length=64), nullable=False),
        sa.Column("status", sa.String(length=16), nullable=False),
        sa.Column("source", sa.String(length=64), nullable=False, server_default=""),
        sa.Column("patient_id", sa.String(length=32), nullable=True),
        sa.Column("case_id", sa.String(length=32), nullable=True),
        sa.Column("encounter_id", sa.String(length=64), nullable=True),
        sa.Column("ingest_id", sa.String(length=64), nullable=True),
        sa.Column("readiness_percent", sa.Integer(), nullable=True),
        sa.Column("gap_count", sa.Integer(), nullable=True),
        sa.Column("auto_prepared", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("detail", sa.String(length=500), nullable=False, server_default=""),
        sa.Column("org_id", sa.String(length=36), nullable=True),
        sa.Column("actor", sa.String(length=120), nullable=False, server_default=""),
    )
    op.create_index("ix_hospital_pipeline_runs_run_id", "hospital_pipeline_runs", ["run_id"], unique=True)
    op.create_index("ix_hospital_pipeline_runs_status", "hospital_pipeline_runs", ["status"])
    op.create_index("ix_hospital_pipeline_runs_patient_id", "hospital_pipeline_runs", ["patient_id"])
    op.create_index("ix_hospital_pipeline_runs_case_id", "hospital_pipeline_runs", ["case_id"])
    op.create_index("ix_hospital_pipeline_runs_org_id", "hospital_pipeline_runs", ["org_id"])


def downgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    if "hospital_pipeline_runs" not in inspector.get_table_names():
        return
    op.drop_table("hospital_pipeline_runs")
