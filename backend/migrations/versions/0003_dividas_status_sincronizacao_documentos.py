"""dividas status sincronizacao documentos

Revision ID: 0003
Revises: 0002
Create Date: 2026-10-04 15:22:26.784310
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0003"
down_revision: str | None = "0002"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

NEW_STATUS = "status IN ('pending', 'confirmed', 'paid', 'canceled')"
OLD_STATUS = "status IN ('paid', 'pending')"


def upgrade() -> None:
    op.create_table(
        "sync_conflicts",
        sa.Column("user_id", sa.String(length=36), nullable=False),
        sa.Column("entity", sa.String(length=40), nullable=False),
        sa.Column("entity_id", sa.String(length=36), nullable=False),
        sa.Column("local_data", sa.JSON(), nullable=False),
        sa.Column("remote_data", sa.JSON(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("resolved_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("resolution", sa.String(length=10), nullable=True),
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.ForeignKeyConstraint(
            ["user_id"], ["users.id"], name=op.f("fk_sync_conflicts_user_id_users"), ondelete="CASCADE"
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_sync_conflicts")),
    )
    with op.batch_alter_table("sync_conflicts", schema=None) as batch_op:
        batch_op.create_index("ix_sync_conflicts_user_open", ["user_id", "resolved_at"], unique=False)

    op.create_table(
        "sync_state",
        sa.Column("user_id", sa.String(length=36), nullable=False),
        sa.Column("remote_url", sa.String(length=300), nullable=False),
        sa.Column("remote_email", sa.String(length=254), nullable=False),
        sa.Column("remote_token", sa.String(length=200), nullable=True),
        sa.Column("last_pull_cursor", sa.String(length=40), nullable=True),
        sa.Column("last_sync_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("last_error", sa.String(length=300), nullable=True),
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(
            ["user_id"], ["users.id"], name=op.f("fk_sync_state_user_id_users"), ondelete="CASCADE"
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_sync_state")),
        sa.UniqueConstraint("user_id", name=op.f("uq_sync_state_user_id")),
    )
    op.create_table(
        "ai_actions",
        sa.Column("user_id", sa.String(length=36), nullable=False),
        sa.Column("conversation_id", sa.String(length=36), nullable=True),
        sa.Column("tool", sa.String(length=40), nullable=False),
        sa.Column("payload", sa.JSON(), nullable=False),
        sa.Column("summary", sa.String(length=300), nullable=False),
        sa.Column(
            "status",
            sa.Enum(
                "pending",
                "confirmed",
                "rejected",
                "expired",
                "failed",
                name="ai_action_status",
                native_enum=False,
                create_constraint=True,
                length=20,
            ),
            nullable=False,
        ),
        sa.Column("result", sa.JSON(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("decided_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.CheckConstraint(
            "status IN ('pending', 'confirmed', 'rejected', 'expired', 'failed')",
            name=op.f("ck_ai_actions_ai_action_status"),
        ),
        sa.ForeignKeyConstraint(
            ["conversation_id"],
            ["ai_conversations.id"],
            name=op.f("fk_ai_actions_conversation_id_ai_conversations"),
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["user_id"], ["users.id"], name=op.f("fk_ai_actions_user_id_users"), ondelete="CASCADE"
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_ai_actions")),
    )
    with op.batch_alter_table("ai_actions", schema=None) as batch_op:
        batch_op.create_index("ix_ai_actions_user_status", ["user_id", "status"], unique=False)

    op.create_table(
        "debts",
        sa.Column("user_id", sa.String(length=36), nullable=False),
        sa.Column("name", sa.String(length=80), nullable=False),
        sa.Column("creditor", sa.String(length=80), nullable=True),
        sa.Column(
            "kind",
            sa.Enum(
                "loan",
                "financing",
                "purchase",
                "card",
                "informal",
                "other",
                name="debt_kind",
                native_enum=False,
                create_constraint=True,
                length=20,
            ),
            nullable=False,
        ),
        sa.Column(
            "status",
            sa.Enum(
                "active", "canceled", name="debt_status", native_enum=False, create_constraint=True, length=20
            ),
            nullable=False,
        ),
        sa.Column("original_cents", sa.BigInteger(), nullable=False),
        sa.Column("installments_total", sa.SmallInteger(), nullable=False),
        sa.Column("installment_cents", sa.BigInteger(), nullable=False),
        sa.Column("installments_paid_before", sa.SmallInteger(), nullable=False),
        sa.Column("first_due_date", sa.Date(), nullable=False),
        sa.Column("interest_monthly_bp", sa.Integer(), nullable=True),
        sa.Column("account_id", sa.String(length=36), nullable=True),
        sa.Column("category_id", sa.String(length=36), nullable=True),
        sa.Column("notes", sa.Text(), nullable=True),
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("deleted_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("version", sa.Integer(), server_default="1", nullable=False),
        sa.Column("synced_version", sa.Integer(), nullable=True),
        sa.CheckConstraint(
            "kind IN ('loan', 'financing', 'purchase', 'card', 'informal', 'other')",
            name=op.f("ck_debts_debt_kind"),
        ),
        sa.CheckConstraint("status IN ('active', 'canceled')", name=op.f("ck_debts_debt_status")),
        sa.CheckConstraint("installment_cents > 0", name=op.f("ck_debts_installment_positive")),
        sa.CheckConstraint(
            "installments_paid_before >= 0 AND installments_paid_before <= installments_total",
            name=op.f("ck_debts_paid_before_range"),
        ),
        sa.CheckConstraint("installments_total BETWEEN 1 AND 600", name=op.f("ck_debts_installments_range")),
        sa.CheckConstraint(
            "interest_monthly_bp IS NULL OR interest_monthly_bp >= 0", name=op.f("ck_debts_interest")
        ),
        sa.CheckConstraint("original_cents > 0", name=op.f("ck_debts_original_positive")),
        sa.ForeignKeyConstraint(
            ["account_id"], ["accounts.id"], name=op.f("fk_debts_account_id_accounts"), ondelete="SET NULL"
        ),
        sa.ForeignKeyConstraint(
            ["category_id"],
            ["categories.id"],
            name=op.f("fk_debts_category_id_categories"),
            ondelete="SET NULL",
        ),
        sa.ForeignKeyConstraint(
            ["user_id"], ["users.id"], name=op.f("fk_debts_user_id_users"), ondelete="CASCADE"
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_debts")),
    )
    with op.batch_alter_table("debts", schema=None) as batch_op:
        batch_op.create_index(batch_op.f("ix_debts_user_id"), ["user_id"], unique=False)

    with op.batch_alter_table("accounts", schema=None) as batch_op:
        batch_op.add_column(sa.Column("version", sa.Integer(), server_default="1", nullable=False))
        batch_op.add_column(sa.Column("synced_version", sa.Integer(), nullable=True))

    with op.batch_alter_table("attachments", schema=None) as batch_op:
        batch_op.add_column(
            sa.Column("storage_backend", sa.String(length=10), server_default="db", nullable=False)
        )
        batch_op.add_column(sa.Column("storage_key", sa.String(length=200), nullable=True))
        batch_op.add_column(sa.Column("title", sa.String(length=120), nullable=True))
        batch_op.add_column(
            sa.Column(
                "kind",
                sa.Enum(
                    "receipt",
                    "bill",
                    "invoice",
                    "pix",
                    "statement",
                    "contract",
                    "other",
                    name="doc_kind",
                    native_enum=False,
                    create_constraint=True,
                    length=20,
                ),
                server_default="other",
                nullable=False,
            )
        )
        batch_op.add_column(
            sa.Column(
                "status",
                sa.Enum(
                    "uploaded",
                    "review",
                    "confirmed",
                    "discarded",
                    name="doc_status",
                    native_enum=False,
                    create_constraint=True,
                    length=20,
                ),
                server_default="uploaded",
                nullable=False,
            )
        )
        batch_op.add_column(sa.Column("deleted_at", sa.DateTime(timezone=True), nullable=True))
        batch_op.alter_column("data", existing_type=sa.LargeBinary(), nullable=True)
        batch_op.create_index("ix_attachments_user_created", ["user_id", "created_at"], unique=False)

    with op.batch_alter_table("budgets", schema=None) as batch_op:
        batch_op.add_column(sa.Column("deleted_at", sa.DateTime(timezone=True), nullable=True))
        batch_op.add_column(sa.Column("version", sa.Integer(), server_default="1", nullable=False))
        batch_op.add_column(sa.Column("synced_version", sa.Integer(), nullable=True))

    with op.batch_alter_table("categories", schema=None) as batch_op:
        batch_op.add_column(sa.Column("version", sa.Integer(), server_default="1", nullable=False))
        batch_op.add_column(sa.Column("synced_version", sa.Integer(), nullable=True))

    with op.batch_alter_table("goals", schema=None) as batch_op:
        batch_op.add_column(sa.Column("version", sa.Integer(), server_default="1", nullable=False))
        batch_op.add_column(sa.Column("synced_version", sa.Integer(), nullable=True))

    with op.batch_alter_table("installment_plans", schema=None) as batch_op:
        batch_op.add_column(sa.Column("version", sa.Integer(), server_default="1", nullable=False))
        batch_op.add_column(sa.Column("synced_version", sa.Integer(), nullable=True))

    with op.batch_alter_table("recurrences", schema=None) as batch_op:
        batch_op.add_column(sa.Column("version", sa.Integer(), server_default="1", nullable=False))
        batch_op.add_column(sa.Column("synced_version", sa.Integer(), nullable=True))

    with op.batch_alter_table("transactions", schema=None) as batch_op:
        batch_op.add_column(sa.Column("debt_id", sa.String(length=36), nullable=True))
        batch_op.add_column(sa.Column("debt_installment", sa.SmallInteger(), nullable=True))
        batch_op.add_column(sa.Column("import_ref", sa.String(length=64), nullable=True))
        batch_op.add_column(sa.Column("synced_version", sa.Integer(), nullable=True))
        batch_op.create_index("ix_transactions_debt", ["debt_id"], unique=False)
        batch_op.create_index("ix_transactions_user_status", ["user_id", "status"], unique=False)
        batch_op.create_index("ix_transactions_user_updated", ["user_id", "updated_at"], unique=False)
        batch_op.create_unique_constraint("uq_transactions_debt_installment", ["debt_id", "debt_installment"])
        batch_op.create_unique_constraint("uq_transactions_import_ref", ["user_id", "import_ref"])
        batch_op.create_foreign_key(
            batch_op.f("fk_transactions_debt_id_debts"), "debts", ["debt_id"], ["id"], ondelete="SET NULL"
        )
        # Novos status: confirmado e cancelado (autogenerate nÃ£o detecta mudanÃ§a em CHECK)
        batch_op.drop_constraint(op.f("ck_transactions_tx_status"), type_="check")
        batch_op.create_check_constraint("tx_status", NEW_STATUS)
        batch_op.create_check_constraint("debt_pair", "(debt_id IS NULL) = (debt_installment IS NULL)")


def downgrade() -> None:
    # O esquema antigo sÃ³ conhece "paid"/"pending": confirmados voltam a previstos e
    # cancelados viram previstos EXCLUÃDOS (exclusÃ£o lÃ³gica â€” nada Ã© apagado).
    op.execute("UPDATE transactions SET status = 'pending' WHERE status = 'confirmed'")
    op.execute(
        "UPDATE transactions SET status = 'pending', deleted_at = CURRENT_TIMESTAMP "
        "WHERE status = 'canceled' AND deleted_at IS NULL"
    )
    op.execute("UPDATE transactions SET status = 'pending' WHERE status = 'canceled'")
    with op.batch_alter_table("transactions", schema=None) as batch_op:
        batch_op.drop_constraint(op.f("ck_transactions_debt_pair"), type_="check")
        batch_op.drop_constraint(op.f("ck_transactions_tx_status"), type_="check")
        batch_op.create_check_constraint("tx_status", OLD_STATUS)
        batch_op.drop_constraint(batch_op.f("fk_transactions_debt_id_debts"), type_="foreignkey")
        batch_op.drop_constraint("uq_transactions_import_ref", type_="unique")
        batch_op.drop_constraint("uq_transactions_debt_installment", type_="unique")
        batch_op.drop_index("ix_transactions_user_updated")
        batch_op.drop_index("ix_transactions_user_status")
        batch_op.drop_index("ix_transactions_debt")
        batch_op.drop_column("synced_version")
        batch_op.drop_column("import_ref")
        batch_op.drop_column("debt_installment")
        batch_op.drop_column("debt_id")

    with op.batch_alter_table("recurrences", schema=None) as batch_op:
        batch_op.drop_column("synced_version")
        batch_op.drop_column("version")

    with op.batch_alter_table("installment_plans", schema=None) as batch_op:
        batch_op.drop_column("synced_version")
        batch_op.drop_column("version")

    with op.batch_alter_table("goals", schema=None) as batch_op:
        batch_op.drop_column("synced_version")
        batch_op.drop_column("version")

    with op.batch_alter_table("categories", schema=None) as batch_op:
        batch_op.drop_column("synced_version")
        batch_op.drop_column("version")

    with op.batch_alter_table("budgets", schema=None) as batch_op:
        batch_op.drop_column("synced_version")
        batch_op.drop_column("version")
        batch_op.drop_column("deleted_at")

    with op.batch_alter_table("attachments", schema=None) as batch_op:
        batch_op.drop_index("ix_attachments_user_created")
        batch_op.drop_constraint(op.f("ck_attachments_doc_kind"), type_="check")
        batch_op.drop_constraint(op.f("ck_attachments_doc_status"), type_="check")
        batch_op.alter_column("data", existing_type=sa.LargeBinary(), nullable=False)
        batch_op.drop_column("deleted_at")
        batch_op.drop_column("status")
        batch_op.drop_column("kind")
        batch_op.drop_column("title")
        batch_op.drop_column("storage_key")
        batch_op.drop_column("storage_backend")

    with op.batch_alter_table("accounts", schema=None) as batch_op:
        batch_op.drop_column("synced_version")
        batch_op.drop_column("version")

    with op.batch_alter_table("debts", schema=None) as batch_op:
        batch_op.drop_index(batch_op.f("ix_debts_user_id"))

    op.drop_table("debts")
    with op.batch_alter_table("ai_actions", schema=None) as batch_op:
        batch_op.drop_index("ix_ai_actions_user_status")

    op.drop_table("ai_actions")
    op.drop_table("sync_state")
    with op.batch_alter_table("sync_conflicts", schema=None) as batch_op:
        batch_op.drop_index("ix_sync_conflicts_user_open")

    op.drop_table("sync_conflicts")
