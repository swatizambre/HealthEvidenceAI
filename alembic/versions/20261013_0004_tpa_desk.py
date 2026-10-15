"""India TPA desk: cashless case fields on authorization_cases + case_queries table.

Revision ID: 20261013_0004
Revises: 20261013_0003
Create Date: 2026-10-13
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "20261013_0004"
down_revision: str | None = "20261013_0003"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_TZ = sa.DateTime(timezone=True)

# (name, type, server_default) — nullable or defaulted so existing rows keep working.
_CASE_COLUMNS: tuple[tuple[str, sa.types.TypeEngine, str | None], ...] = (
    ("payer_type", sa.String(length=16), None),
    ("insurer_name", sa.String(length=160), ""),
    ("tpa_name", sa.String(length=160), ""),
    ("policy_number", sa.String(length=64), ""),
    ("admission_type", sa.String(length=16), "planned"),
    ("admitted_at", _TZ, None),
    ("expected_discharge_at", _TZ, None),
    ("treating_doctor", sa.String(length=160), ""),
    ("provisional_diagnosis", sa.String(length=300), ""),
    ("icd10_code", sa.String(length=16), ""),
    ("proposed_treatment", sa.String(length=300), ""),
    ("estimated_cost_inr", sa.Integer(), None),
    ("approved_amount_inr", sa.Integer(), None),
    ("stage", sa.String(length=32), "draft"),
    ("sent_at", _TZ, None),
    ("decision_due_at", _TZ, None),
    ("approved_at", _TZ, None),
    ("discharge_requested_at", _TZ, None),
    ("final_due_at", _TZ, None),
    ("revised_estimate_inr", sa.Integer(), None),
    ("enhancement_reason", sa.String(length=500), ""),
    ("enhancement_requested_at", _TZ, None),
    ("enhancement_count", sa.Integer(), "0"),
    ("discharge_override_reason", sa.String(length=500), ""),
    ("closed_at", _TZ, None),
    ("cost_breakdown_inr", sa.JSON(), None),
    ("form_extra", sa.JSON(), None),
)


def upgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    tables = set(inspector.get_table_names())
    if "authorization_cases" in tables:
        cols = {c["name"] for c in inspector.get_columns("authorization_cases")}
        for name, type_, default in _CASE_COLUMNS:
            if name in cols:
                continue
            op.add_column(
                "authorization_cases",
                sa.Column(
                    name,
                    type_,
                    nullable=True,
                    server_default=sa.text(default) if default == "0" else default,
                ),
            )
        indexes = {ix["name"] for ix in inspector.get_indexes("authorization_cases")}
        if "ix_authorization_cases_stage" not in indexes:
            op.create_index("ix_authorization_cases_stage", "authorization_cases", ["stage"])
        if "ix_authorization_cases_payer_type" not in indexes:
            op.create_index(
                "ix_authorization_cases_payer_type", "authorization_cases", ["payer_type"]
            )
    if "case_queries" not in tables:
        op.create_table(
            "case_queries",
            sa.Column("id", sa.String(length=36), primary_key=True),
            sa.Column("query_code", sa.String(length=32), nullable=False),
            sa.Column(
                "case_id",
                sa.String(length=36),
                sa.ForeignKey("authorization_cases.id", ondelete="CASCADE"),
                nullable=False,
            ),
            sa.Column("raised_at", _TZ, nullable=False),
            sa.Column("text", sa.Text(), nullable=False, server_default=""),
            sa.Column("response_due_at", _TZ, nullable=True),
            sa.Column("responded_at", _TZ, nullable=True),
            sa.Column("response", sa.Text(), nullable=False, server_default=""),
            sa.Column("raised_by", sa.String(length=120), nullable=False, server_default=""),
            sa.Column("responded_by", sa.String(length=120), nullable=False, server_default=""),
            sa.Column("resume_stage", sa.String(length=32), nullable=False, server_default="sent"),
            sa.Column("created_at", _TZ, nullable=False),
            sa.Column("updated_at", _TZ, nullable=False),
        )
        op.create_index("ix_case_queries_query_code", "case_queries", ["query_code"], unique=True)
        op.create_index("ix_case_queries_case_id", "case_queries", ["case_id"])


def downgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    tables = set(inspector.get_table_names())
    if "case_queries" in tables:
        op.drop_table("case_queries")
    # SQLite keeps the added columns on downgrade (no portable DROP COLUMN for indexed /
    # defaulted columns); they are nullable/defaulted, so older code ignores them.
    if "authorization_cases" in tables and bind.dialect.name != "sqlite":
        indexes = {ix["name"] for ix in inspector.get_indexes("authorization_cases")}
        for index in ("ix_authorization_cases_stage", "ix_authorization_cases_payer_type"):
            if index in indexes:
                op.drop_index(index, table_name="authorization_cases")
        cols = {c["name"] for c in inspector.get_columns("authorization_cases")}
        for name, _type, _default in reversed(_CASE_COLUMNS):
            if name in cols:
                op.drop_column("authorization_cases", name)
