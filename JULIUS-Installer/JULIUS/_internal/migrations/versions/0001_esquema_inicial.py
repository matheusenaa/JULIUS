"""esquema inicial

Revision ID: 0001
Revises:
Create Date: 2026-10-03 16:16:39.829954
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0001"
down_revision: str | None = None
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "users",
        sa.Column("email", sa.String(length=254), nullable=False),
        sa.Column("name", sa.String(length=80), nullable=False),
        sa.Column("password_hash", sa.String(length=200), nullable=False),
        sa.Column("settings", sa.JSON(), nullable=False),
        sa.Column("last_login_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("deleted_at", sa.DateTime(timezone=True), nullable=True),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_users")),
        sa.UniqueConstraint("email", name=op.f("uq_users_email")),
    )
    op.create_table(
        "accounts",
        sa.Column("user_id", sa.String(length=36), nullable=False),
        sa.Column("name", sa.String(length=60), nullable=False),
        sa.Column(
            "kind",
            sa.Enum(
                "checking",
                "savings",
                "cash",
                "wallet",
                "credit_card",
                "investment",
                "other",
                name="account_kind",
                native_enum=False,
                create_constraint=True,
                length=20,
            ),
            nullable=False,
        ),
        sa.Column("currency", sa.String(length=3), nullable=False),
        sa.Column("initial_balance_cents", sa.BigInteger(), nullable=False),
        sa.Column("color", sa.String(length=9), nullable=True),
        sa.Column("include_in_total", sa.Boolean(), nullable=False),
        sa.Column("credit_limit_cents", sa.BigInteger(), nullable=True),
        sa.Column("closing_day", sa.SmallInteger(), nullable=True),
        sa.Column("due_day", sa.SmallInteger(), nullable=True),
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("deleted_at", sa.DateTime(timezone=True), nullable=True),
        sa.CheckConstraint(
            "kind <> 'credit_card' OR (closing_day IS NOT NULL AND due_day IS NOT NULL)",
            name=op.f("ck_accounts_card_days_required"),
        ),
        sa.CheckConstraint(
            "kind IN ('checking', 'savings', 'cash', 'wallet', 'credit_card', 'investment', 'other')",
            name=op.f("ck_accounts_account_kind"),
        ),
        sa.CheckConstraint(
            "closing_day IS NULL OR closing_day BETWEEN 1 AND 31", name=op.f("ck_accounts_closing_day")
        ),
        sa.CheckConstraint(
            "credit_limit_cents IS NULL OR credit_limit_cents >= 0", name=op.f("ck_accounts_limit")
        ),
        sa.CheckConstraint("due_day IS NULL OR due_day BETWEEN 1 AND 31", name=op.f("ck_accounts_due_day")),
        sa.ForeignKeyConstraint(
            ["user_id"], ["users.id"], name=op.f("fk_accounts_user_id_users"), ondelete="CASCADE"
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_accounts")),
    )
    with op.batch_alter_table("accounts", schema=None) as batch_op:
        batch_op.create_index(batch_op.f("ix_accounts_user_id"), ["user_id"], unique=False)

    op.create_table(
        "ai_conversations",
        sa.Column("user_id", sa.String(length=36), nullable=False),
        sa.Column("title", sa.String(length=120), nullable=False),
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(
            ["user_id"], ["users.id"], name=op.f("fk_ai_conversations_user_id_users"), ondelete="CASCADE"
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_ai_conversations")),
    )
    with op.batch_alter_table("ai_conversations", schema=None) as batch_op:
        batch_op.create_index(batch_op.f("ix_ai_conversations_user_id"), ["user_id"], unique=False)

    op.create_table(
        "audit_logs",
        sa.Column("user_id", sa.String(length=36), nullable=True),
        sa.Column("entity", sa.String(length=40), nullable=False),
        sa.Column("entity_id", sa.String(length=36), nullable=True),
        sa.Column("action", sa.String(length=20), nullable=False),
        sa.Column("summary", sa.String(length=300), nullable=False),
        sa.Column("changes", sa.JSON(), nullable=True),
        sa.Column("ip", sa.String(length=64), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.ForeignKeyConstraint(
            ["user_id"], ["users.id"], name=op.f("fk_audit_logs_user_id_users"), ondelete="CASCADE"
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_audit_logs")),
    )
    with op.batch_alter_table("audit_logs", schema=None) as batch_op:
        batch_op.create_index("ix_audit_entity", ["entity", "entity_id"], unique=False)
        batch_op.create_index("ix_audit_user_created", ["user_id", "created_at"], unique=False)

    op.create_table(
        "categories",
        sa.Column("user_id", sa.String(length=36), nullable=False),
        sa.Column("parent_id", sa.String(length=36), nullable=True),
        sa.Column("name", sa.String(length=60), nullable=False),
        sa.Column(
            "kind",
            sa.Enum(
                "expense",
                "income",
                name="category_kind",
                native_enum=False,
                create_constraint=True,
                length=20,
            ),
            nullable=False,
        ),
        sa.Column("icon", sa.String(length=40), nullable=True),
        sa.Column("color", sa.String(length=9), nullable=True),
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("deleted_at", sa.DateTime(timezone=True), nullable=True),
        sa.CheckConstraint("kind IN ('expense', 'income')", name=op.f("ck_categories_category_kind")),
        sa.ForeignKeyConstraint(
            ["parent_id"],
            ["categories.id"],
            name=op.f("fk_categories_parent_id_categories"),
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["user_id"], ["users.id"], name=op.f("fk_categories_user_id_users"), ondelete="CASCADE"
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_categories")),
    )
    with op.batch_alter_table("categories", schema=None) as batch_op:
        batch_op.create_index("ix_categories_user_parent", ["user_id", "parent_id"], unique=False)

    op.create_table(
        "sessions",
        sa.Column("user_id", sa.String(length=36), nullable=False),
        sa.Column("token_hash", sa.String(length=64), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("last_seen_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("user_agent", sa.String(length=300), nullable=True),
        sa.Column("ip", sa.String(length=64), nullable=True),
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.ForeignKeyConstraint(
            ["user_id"], ["users.id"], name=op.f("fk_sessions_user_id_users"), ondelete="CASCADE"
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_sessions")),
        sa.UniqueConstraint("token_hash", name=op.f("uq_sessions_token_hash")),
    )
    with op.batch_alter_table("sessions", schema=None) as batch_op:
        batch_op.create_index(batch_op.f("ix_sessions_user_id"), ["user_id"], unique=False)

    op.create_table(
        "ai_messages",
        sa.Column("conversation_id", sa.String(length=36), nullable=False),
        sa.Column("role", sa.String(length=10), nullable=False),
        sa.Column("content", sa.Text(), nullable=False),
        sa.Column("data", sa.JSON(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.ForeignKeyConstraint(
            ["conversation_id"],
            ["ai_conversations.id"],
            name=op.f("fk_ai_messages_conversation_id_ai_conversations"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_ai_messages")),
    )
    with op.batch_alter_table("ai_messages", schema=None) as batch_op:
        batch_op.create_index(batch_op.f("ix_ai_messages_conversation_id"), ["conversation_id"], unique=False)

    op.create_table(
        "budgets",
        sa.Column("user_id", sa.String(length=36), nullable=False),
        sa.Column("category_id", sa.String(length=36), nullable=False),
        sa.Column("amount_cents", sa.BigInteger(), nullable=False),
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint("amount_cents > 0", name=op.f("ck_budgets_amount_positive")),
        sa.ForeignKeyConstraint(
            ["category_id"],
            ["categories.id"],
            name=op.f("fk_budgets_category_id_categories"),
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["user_id"], ["users.id"], name=op.f("fk_budgets_user_id_users"), ondelete="CASCADE"
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_budgets")),
        sa.UniqueConstraint("user_id", "category_id", name="uq_budgets_user_category"),
    )
    op.create_table(
        "categorization_rules",
        sa.Column("user_id", sa.String(length=36), nullable=False),
        sa.Column("keyword", sa.String(length=80), nullable=False),
        sa.Column("category_id", sa.String(length=36), nullable=False),
        sa.Column("hits", sa.Integer(), nullable=False),
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(
            ["category_id"],
            ["categories.id"],
            name=op.f("fk_categorization_rules_category_id_categories"),
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["user_id"], ["users.id"], name=op.f("fk_categorization_rules_user_id_users"), ondelete="CASCADE"
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_categorization_rules")),
        sa.UniqueConstraint("user_id", "keyword", name="uq_rules_user_keyword"),
    )
    op.create_table(
        "goals",
        sa.Column("user_id", sa.String(length=36), nullable=False),
        sa.Column("name", sa.String(length=80), nullable=False),
        sa.Column("target_cents", sa.BigInteger(), nullable=False),
        sa.Column("saved_cents", sa.BigInteger(), nullable=False),
        sa.Column("target_date", sa.Date(), nullable=True),
        sa.Column("account_id", sa.String(length=36), nullable=True),
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("deleted_at", sa.DateTime(timezone=True), nullable=True),
        sa.CheckConstraint("saved_cents >= 0", name=op.f("ck_goals_saved_non_negative")),
        sa.CheckConstraint("target_cents > 0", name=op.f("ck_goals_target_positive")),
        sa.ForeignKeyConstraint(
            ["account_id"], ["accounts.id"], name=op.f("fk_goals_account_id_accounts"), ondelete="SET NULL"
        ),
        sa.ForeignKeyConstraint(
            ["user_id"], ["users.id"], name=op.f("fk_goals_user_id_users"), ondelete="CASCADE"
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_goals")),
    )
    with op.batch_alter_table("goals", schema=None) as batch_op:
        batch_op.create_index(batch_op.f("ix_goals_user_id"), ["user_id"], unique=False)

    op.create_table(
        "installment_plans",
        sa.Column("user_id", sa.String(length=36), nullable=False),
        sa.Column("account_id", sa.String(length=36), nullable=False),
        sa.Column("description", sa.String(length=200), nullable=False),
        sa.Column("total_cents", sa.BigInteger(), nullable=False),
        sa.Column("installments", sa.SmallInteger(), nullable=False),
        sa.Column("purchase_date", sa.Date(), nullable=False),
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("deleted_at", sa.DateTime(timezone=True), nullable=True),
        sa.CheckConstraint(
            "installments BETWEEN 2 AND 120", name=op.f("ck_installment_plans_installments_range")
        ),
        sa.CheckConstraint("total_cents > 0", name=op.f("ck_installment_plans_total_positive")),
        sa.ForeignKeyConstraint(
            ["account_id"],
            ["accounts.id"],
            name=op.f("fk_installment_plans_account_id_accounts"),
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["user_id"], ["users.id"], name=op.f("fk_installment_plans_user_id_users"), ondelete="CASCADE"
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_installment_plans")),
    )
    with op.batch_alter_table("installment_plans", schema=None) as batch_op:
        batch_op.create_index(batch_op.f("ix_installment_plans_user_id"), ["user_id"], unique=False)

    op.create_table(
        "recurrences",
        sa.Column("user_id", sa.String(length=36), nullable=False),
        sa.Column("account_id", sa.String(length=36), nullable=False),
        sa.Column("category_id", sa.String(length=36), nullable=True),
        sa.Column(
            "type",
            sa.Enum(
                "income",
                "expense",
                "transfer",
                name="recurrence_type",
                native_enum=False,
                create_constraint=True,
                length=20,
            ),
            nullable=False,
        ),
        sa.Column("description", sa.String(length=200), nullable=False),
        sa.Column("amount_cents", sa.BigInteger(), nullable=False),
        sa.Column(
            "payment_method",
            sa.Enum(
                "pix",
                "debit",
                "credit",
                "cash",
                "boleto",
                "transfer",
                "other",
                name="rec_payment",
                native_enum=False,
                create_constraint=True,
                length=20,
            ),
            nullable=True,
        ),
        sa.Column("is_fixed", sa.Boolean(), nullable=False),
        sa.Column(
            "frequency",
            sa.Enum(
                "weekly",
                "monthly",
                "yearly",
                name="frequency",
                native_enum=False,
                create_constraint=True,
                length=20,
            ),
            nullable=False,
        ),
        sa.Column("day_of_month", sa.SmallInteger(), nullable=True),
        sa.Column("start_date", sa.Date(), nullable=False),
        sa.Column("end_date", sa.Date(), nullable=True),
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("deleted_at", sa.DateTime(timezone=True), nullable=True),
        sa.CheckConstraint(
            "frequency IN ('weekly', 'monthly', 'yearly')", name=op.f("ck_recurrences_frequency")
        ),
        sa.CheckConstraint(
            "payment_method IN ('pix', 'debit', 'credit', 'cash', 'boleto', 'transfer', 'other')",
            name=op.f("ck_recurrences_rec_payment"),
        ),
        sa.CheckConstraint("type IN ('income', 'expense')", name=op.f("ck_recurrences_type_no_transfer")),
        sa.CheckConstraint(
            "type IN ('income', 'expense', 'transfer')", name=op.f("ck_recurrences_recurrence_type")
        ),
        sa.CheckConstraint("amount_cents > 0", name=op.f("ck_recurrences_amount_positive")),
        sa.CheckConstraint(
            "day_of_month IS NULL OR day_of_month BETWEEN 1 AND 31", name=op.f("ck_recurrences_dom")
        ),
        sa.CheckConstraint("end_date IS NULL OR end_date >= start_date", name=op.f("ck_recurrences_dates")),
        sa.ForeignKeyConstraint(
            ["account_id"],
            ["accounts.id"],
            name=op.f("fk_recurrences_account_id_accounts"),
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["category_id"],
            ["categories.id"],
            name=op.f("fk_recurrences_category_id_categories"),
            ondelete="SET NULL",
        ),
        sa.ForeignKeyConstraint(
            ["user_id"], ["users.id"], name=op.f("fk_recurrences_user_id_users"), ondelete="CASCADE"
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_recurrences")),
    )
    with op.batch_alter_table("recurrences", schema=None) as batch_op:
        batch_op.create_index(batch_op.f("ix_recurrences_user_id"), ["user_id"], unique=False)

    op.create_table(
        "transactions",
        sa.Column("user_id", sa.String(length=36), nullable=False),
        sa.Column("account_id", sa.String(length=36), nullable=False),
        sa.Column("to_account_id", sa.String(length=36), nullable=True),
        sa.Column(
            "type",
            sa.Enum(
                "income",
                "expense",
                "transfer",
                name="tx_type",
                native_enum=False,
                create_constraint=True,
                length=20,
            ),
            nullable=False,
        ),
        sa.Column(
            "status",
            sa.Enum(
                "paid", "pending", name="tx_status", native_enum=False, create_constraint=True, length=20
            ),
            nullable=False,
        ),
        sa.Column("amount_cents", sa.BigInteger(), nullable=False),
        sa.Column("occurred_on", sa.Date(), nullable=False),
        sa.Column("description", sa.String(length=200), nullable=False),
        sa.Column("notes", sa.Text(), nullable=True),
        sa.Column("category_id", sa.String(length=36), nullable=True),
        sa.Column(
            "payment_method",
            sa.Enum(
                "pix",
                "debit",
                "credit",
                "cash",
                "boleto",
                "transfer",
                "other",
                name="tx_payment",
                native_enum=False,
                create_constraint=True,
                length=20,
            ),
            nullable=True,
        ),
        sa.Column("is_fixed", sa.Boolean(), nullable=False),
        sa.Column(
            "source",
            sa.Enum(
                "manual",
                "quick_input",
                "ai",
                "ocr",
                "import",
                "recurrence",
                name="tx_source",
                native_enum=False,
                create_constraint=True,
                length=20,
            ),
            nullable=False,
        ),
        sa.Column("invoice_month", sa.Date(), nullable=True),
        sa.Column("recurrence_id", sa.String(length=36), nullable=True),
        sa.Column("occurrence_date", sa.Date(), nullable=True),
        sa.Column("installment_plan_id", sa.String(length=36), nullable=True),
        sa.Column("installment_number", sa.SmallInteger(), nullable=True),
        sa.Column("version", sa.Integer(), nullable=False),
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("deleted_at", sa.DateTime(timezone=True), nullable=True),
        sa.CheckConstraint(
            "(type = 'transfer' AND to_account_id IS NOT NULL AND to_account_id <> account_id) OR (type <> 'transfer' AND to_account_id IS NULL)",
            name=op.f("ck_transactions_transfer_target"),
        ),
        sa.CheckConstraint(
            "payment_method IN ('pix', 'debit', 'credit', 'cash', 'boleto', 'transfer', 'other')",
            name=op.f("ck_transactions_tx_payment"),
        ),
        sa.CheckConstraint(
            "source IN ('manual', 'quick_input', 'ai', 'ocr', 'import', 'recurrence')",
            name=op.f("ck_transactions_tx_source"),
        ),
        sa.CheckConstraint("status IN ('paid', 'pending')", name=op.f("ck_transactions_tx_status")),
        sa.CheckConstraint("type IN ('income', 'expense', 'transfer')", name=op.f("ck_transactions_tx_type")),
        sa.CheckConstraint(
            "(installment_plan_id IS NULL) = (installment_number IS NULL)",
            name=op.f("ck_transactions_installment_pair"),
        ),
        sa.CheckConstraint(
            "(recurrence_id IS NULL) = (occurrence_date IS NULL)",
            name=op.f("ck_transactions_recurrence_pair"),
        ),
        sa.CheckConstraint("amount_cents > 0", name=op.f("ck_transactions_amount_positive")),
        sa.CheckConstraint("version >= 1", name=op.f("ck_transactions_version")),
        sa.ForeignKeyConstraint(
            ["account_id"],
            ["accounts.id"],
            name=op.f("fk_transactions_account_id_accounts"),
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["category_id"],
            ["categories.id"],
            name=op.f("fk_transactions_category_id_categories"),
            ondelete="SET NULL",
        ),
        sa.ForeignKeyConstraint(
            ["installment_plan_id"],
            ["installment_plans.id"],
            name=op.f("fk_transactions_installment_plan_id_installment_plans"),
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["recurrence_id"],
            ["recurrences.id"],
            name=op.f("fk_transactions_recurrence_id_recurrences"),
            ondelete="SET NULL",
        ),
        sa.ForeignKeyConstraint(
            ["to_account_id"],
            ["accounts.id"],
            name=op.f("fk_transactions_to_account_id_accounts"),
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["user_id"], ["users.id"], name=op.f("fk_transactions_user_id_users"), ondelete="CASCADE"
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_transactions")),
        sa.UniqueConstraint("installment_plan_id", "installment_number", name="uq_transactions_installment"),
        sa.UniqueConstraint("recurrence_id", "occurrence_date", name="uq_transactions_occurrence"),
    )
    with op.batch_alter_table("transactions", schema=None) as batch_op:
        batch_op.create_index("ix_transactions_account", ["account_id"], unique=False)
        batch_op.create_index("ix_transactions_to_account", ["to_account_id"], unique=False)
        batch_op.create_index("ix_transactions_user_category", ["user_id", "category_id"], unique=False)
        batch_op.create_index("ix_transactions_user_date", ["user_id", "occurred_on"], unique=False)


def downgrade() -> None:
    with op.batch_alter_table("transactions", schema=None) as batch_op:
        batch_op.drop_index("ix_transactions_user_date")
        batch_op.drop_index("ix_transactions_user_category")
        batch_op.drop_index("ix_transactions_to_account")
        batch_op.drop_index("ix_transactions_account")

    op.drop_table("transactions")
    with op.batch_alter_table("recurrences", schema=None) as batch_op:
        batch_op.drop_index(batch_op.f("ix_recurrences_user_id"))

    op.drop_table("recurrences")
    with op.batch_alter_table("installment_plans", schema=None) as batch_op:
        batch_op.drop_index(batch_op.f("ix_installment_plans_user_id"))

    op.drop_table("installment_plans")
    with op.batch_alter_table("goals", schema=None) as batch_op:
        batch_op.drop_index(batch_op.f("ix_goals_user_id"))

    op.drop_table("goals")
    op.drop_table("categorization_rules")
    op.drop_table("budgets")
    with op.batch_alter_table("ai_messages", schema=None) as batch_op:
        batch_op.drop_index(batch_op.f("ix_ai_messages_conversation_id"))

    op.drop_table("ai_messages")
    with op.batch_alter_table("sessions", schema=None) as batch_op:
        batch_op.drop_index(batch_op.f("ix_sessions_user_id"))

    op.drop_table("sessions")
    with op.batch_alter_table("categories", schema=None) as batch_op:
        batch_op.drop_index("ix_categories_user_parent")

    op.drop_table("categories")
    with op.batch_alter_table("audit_logs", schema=None) as batch_op:
        batch_op.drop_index("ix_audit_user_created")
        batch_op.drop_index("ix_audit_entity")

    op.drop_table("audit_logs")
    with op.batch_alter_table("ai_conversations", schema=None) as batch_op:
        batch_op.drop_index(batch_op.f("ix_ai_conversations_user_id"))

    op.drop_table("ai_conversations")
    with op.batch_alter_table("accounts", schema=None) as batch_op:
        batch_op.drop_index(batch_op.f("ix_accounts_user_id"))

    op.drop_table("accounts")
    op.drop_table("users")
