"""anexos

Revision ID: 0002
Revises: 0001
Create Date: 2026-10-03 18:19:37.523023
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0002"
down_revision: str | None = "0001"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "attachments",
        sa.Column("user_id", sa.String(length=36), nullable=False),
        sa.Column("transaction_id", sa.String(length=36), nullable=True),
        sa.Column("filename", sa.String(length=200), nullable=False),
        sa.Column("content_type", sa.String(length=60), nullable=False),
        sa.Column("size_bytes", sa.Integer(), nullable=False),
        sa.Column("sha256", sa.String(length=64), nullable=False),
        sa.Column("data", sa.LargeBinary(), nullable=False),
        sa.Column("extracted", sa.JSON(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.CheckConstraint("size_bytes > 0", name=op.f("ck_attachments_size_positive")),
        sa.ForeignKeyConstraint(
            ["transaction_id"],
            ["transactions.id"],
            name=op.f("fk_attachments_transaction_id_transactions"),
            ondelete="SET NULL",
        ),
        sa.ForeignKeyConstraint(
            ["user_id"], ["users.id"], name=op.f("fk_attachments_user_id_users"), ondelete="CASCADE"
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_attachments")),
    )
    with op.batch_alter_table("attachments", schema=None) as batch_op:
        batch_op.create_index(batch_op.f("ix_attachments_transaction_id"), ["transaction_id"], unique=False)
        batch_op.create_index(batch_op.f("ix_attachments_user_id"), ["user_id"], unique=False)


def downgrade() -> None:
    with op.batch_alter_table("attachments", schema=None) as batch_op:
        batch_op.drop_index(batch_op.f("ix_attachments_user_id"))
        batch_op.drop_index(batch_op.f("ix_attachments_transaction_id"))

    op.drop_table("attachments")
