"""Add authorization_cases.assigned_to and baseline revision.

Revision ID: 20261009_0001
Revises:
Create Date: 2026-10-09
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "20261009_0001"
down_revision: str | None = None
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    if "authorization_cases" in inspector.get_table_names():
        cols = {c["name"] for c in inspector.get_columns("authorization_cases")}
        if "assigned_to" not in cols:
            op.add_column(
                "authorization_cases",
                sa.Column("assigned_to", sa.String(length=120), nullable=True),
            )
            op.create_index(
                "ix_authorization_cases_assigned_to",
                "authorization_cases",
                ["assigned_to"],
            )


def downgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    if "authorization_cases" in inspector.get_table_names():
        cols = {c["name"] for c in inspector.get_columns("authorization_cases")}
        if "assigned_to" in cols:
            op.drop_index("ix_authorization_cases_assigned_to", table_name="authorization_cases")
            op.drop_column("authorization_cases", "assigned_to")
