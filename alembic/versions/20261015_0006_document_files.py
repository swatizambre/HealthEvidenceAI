"""Document file storage for report PDF/image preview.

Revision ID: 20261015_0006
Revises: 20261015_0005
Create Date: 2026-10-15
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "20261015_0006"
down_revision: str | None = "20261015_0005"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_TZ = sa.DateTime(timezone=True)


def upgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    tables = set(inspector.get_table_names())

    if "document_files" not in tables:
        op.create_table(
            "document_files",
            sa.Column("id", sa.String(length=36), primary_key=True),
            sa.Column("created_at", _TZ, nullable=False),
            sa.Column("updated_at", _TZ, nullable=False),
            sa.Column(
                "document_id",
                sa.String(length=36),
                sa.ForeignKey("documents.id", ondelete="CASCADE"),
                nullable=False,
            ),
            sa.Column("original_filename", sa.String(length=260), server_default=""),
            sa.Column(
                "content_type",
                sa.String(length=120),
                server_default="application/octet-stream",
            ),
            sa.Column("storage_path", sa.String(length=500), nullable=False),
            sa.Column("byte_size", sa.Integer(), server_default="0"),
            sa.Column("sha256", sa.String(length=64), server_default=""),
        )
        op.create_index(
            "ix_document_files_document_id", "document_files", ["document_id"], unique=True
        )

    if "imaging_studies" in tables:
        cols = {c["name"] for c in inspector.get_columns("imaging_studies")}
        if "document_id" not in cols:
            op.add_column(
                "imaging_studies",
                sa.Column("document_id", sa.String(length=36), nullable=True),
            )
            indexes = {ix["name"] for ix in inspector.get_indexes("imaging_studies")}
            if "ix_imaging_studies_document_id" not in indexes:
                op.create_index(
                    "ix_imaging_studies_document_id",
                    "imaging_studies",
                    ["document_id"],
                )


def downgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    tables = set(inspector.get_table_names())
    if "imaging_studies" in tables:
        cols = {c["name"] for c in inspector.get_columns("imaging_studies")}
        if "document_id" in cols:
            indexes = {ix["name"] for ix in inspector.get_indexes("imaging_studies")}
            if "ix_imaging_studies_document_id" in indexes:
                op.drop_index("ix_imaging_studies_document_id", table_name="imaging_studies")
            op.drop_column("imaging_studies", "document_id")
    if "document_files" in tables:
        op.drop_table("document_files")
