"""Entidades financeiras. Valores monetários sempre em centavos (inteiros)."""

from datetime import date

from sqlalchemy import (
    BigInteger,
    Boolean,
    CheckConstraint,
    Date,
    ForeignKey,
    Index,
    Integer,
    SmallInteger,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base, IdMixin, SoftDeleteMixin, SyncMixin, TimestampMixin, str_enum

ACCOUNT_KINDS = ("checking", "savings", "cash", "wallet", "credit_card", "investment", "other")
CATEGORY_KINDS = ("expense", "income")
TX_TYPES = ("income", "expense", "transfer")
# previsto | confirmado (ex.: boleto agendado) | pago/recebido | cancelado.
# "Atrasado" não é gravado: é previsto/confirmado com data já passada (calculado na hora).
TX_STATUSES = ("pending", "confirmed", "paid", "canceled")
OPEN_STATUSES = ("pending", "confirmed")
PAYMENT_METHODS = ("pix", "debit", "credit", "cash", "boleto", "transfer", "other")
TX_SOURCES = ("manual", "quick_input", "ai", "ocr", "import", "recurrence")
FREQUENCIES = ("weekly", "monthly", "yearly")
DEBT_KINDS = ("loan", "financing", "purchase", "card", "informal", "other")
DEBT_STATUSES = ("active", "canceled")


class Account(IdMixin, TimestampMixin, SoftDeleteMixin, SyncMixin, Base):
    """Conta bancária, carteira, dinheiro ou cartão de crédito."""

    __tablename__ = "accounts"
    __table_args__ = (
        CheckConstraint(
            "kind <> 'credit_card' OR (closing_day IS NOT NULL AND due_day IS NOT NULL)",
            name="card_days_required",
        ),
        CheckConstraint("closing_day IS NULL OR closing_day BETWEEN 1 AND 31", name="closing_day"),
        CheckConstraint("due_day IS NULL OR due_day BETWEEN 1 AND 31", name="due_day"),
        CheckConstraint("credit_limit_cents IS NULL OR credit_limit_cents >= 0", name="limit"),
    )

    user_id: Mapped[str] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    name: Mapped[str] = mapped_column(String(60))
    kind: Mapped[str] = mapped_column(str_enum(ACCOUNT_KINDS, "account_kind"))
    currency: Mapped[str] = mapped_column(String(3), default="BRL")
    initial_balance_cents: Mapped[int] = mapped_column(BigInteger, default=0)
    color: Mapped[str | None] = mapped_column(String(9))
    include_in_total: Mapped[bool] = mapped_column(Boolean, default=True)
    # Somente cartões
    credit_limit_cents: Mapped[int | None] = mapped_column(BigInteger)
    closing_day: Mapped[int | None] = mapped_column(SmallInteger)
    due_day: Mapped[int | None] = mapped_column(SmallInteger)


class Category(IdMixin, TimestampMixin, SoftDeleteMixin, SyncMixin, Base):
    """Categoria (parent_id nulo) ou subcategoria (parent_id preenchido)."""

    __tablename__ = "categories"
    __table_args__ = (Index("ix_categories_user_parent", "user_id", "parent_id"),)

    user_id: Mapped[str] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"))
    parent_id: Mapped[str | None] = mapped_column(ForeignKey("categories.id", ondelete="RESTRICT"))
    name: Mapped[str] = mapped_column(String(60))
    kind: Mapped[str] = mapped_column(str_enum(CATEGORY_KINDS, "category_kind"))
    icon: Mapped[str | None] = mapped_column(String(40))
    color: Mapped[str | None] = mapped_column(String(9))


class Recurrence(IdMixin, TimestampMixin, SoftDeleteMixin, SyncMixin, Base):
    """Regra de lançamento recorrente (aluguel, salário, assinatura...)."""

    __tablename__ = "recurrences"
    __table_args__ = (
        CheckConstraint("amount_cents > 0", name="amount_positive"),
        CheckConstraint("type IN ('income', 'expense')", name="type_no_transfer"),
        CheckConstraint("day_of_month IS NULL OR day_of_month BETWEEN 1 AND 31", name="dom"),
        CheckConstraint("end_date IS NULL OR end_date >= start_date", name="dates"),
    )

    user_id: Mapped[str] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    account_id: Mapped[str] = mapped_column(ForeignKey("accounts.id", ondelete="RESTRICT"))
    category_id: Mapped[str | None] = mapped_column(ForeignKey("categories.id", ondelete="SET NULL"))
    type: Mapped[str] = mapped_column(str_enum(TX_TYPES, "recurrence_type"))
    description: Mapped[str] = mapped_column(String(200))
    amount_cents: Mapped[int] = mapped_column(BigInteger)
    payment_method: Mapped[str | None] = mapped_column(str_enum(PAYMENT_METHODS, "rec_payment"))
    is_fixed: Mapped[bool] = mapped_column(Boolean, default=True)
    frequency: Mapped[str] = mapped_column(str_enum(FREQUENCIES, "frequency"), default="monthly")
    day_of_month: Mapped[int | None] = mapped_column(SmallInteger)
    start_date: Mapped[date] = mapped_column(Date)
    end_date: Mapped[date | None] = mapped_column(Date)


class InstallmentPlan(IdMixin, TimestampMixin, SoftDeleteMixin, SyncMixin, Base):
    """Compra parcelada. As parcelas em si são transações ligadas a este plano."""

    __tablename__ = "installment_plans"
    __table_args__ = (
        CheckConstraint("total_cents > 0", name="total_positive"),
        CheckConstraint("installments BETWEEN 2 AND 120", name="installments_range"),
    )

    user_id: Mapped[str] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    account_id: Mapped[str] = mapped_column(ForeignKey("accounts.id", ondelete="RESTRICT"))
    description: Mapped[str] = mapped_column(String(200))
    total_cents: Mapped[int] = mapped_column(BigInteger)
    installments: Mapped[int] = mapped_column(SmallInteger)
    purchase_date: Mapped[date] = mapped_column(Date)


class Debt(IdMixin, TimestampMixin, SoftDeleteMixin, SyncMixin, Base):
    """Dívida, empréstimo ou financiamento.

    Restante, próxima parcela e data final são CALCULADOS a partir das parcelas
    já pagas antes do cadastro + pagamentos registrados (transações com debt_id).
    """

    __tablename__ = "debts"
    __table_args__ = (
        CheckConstraint("installments_total BETWEEN 1 AND 600", name="installments_range"),
        CheckConstraint("installment_cents > 0", name="installment_positive"),
        CheckConstraint("original_cents > 0", name="original_positive"),
        CheckConstraint(
            "installments_paid_before >= 0 AND installments_paid_before <= installments_total",
            name="paid_before_range",
        ),
        CheckConstraint("interest_monthly_bp IS NULL OR interest_monthly_bp >= 0", name="interest"),
    )

    user_id: Mapped[str] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    name: Mapped[str] = mapped_column(String(80))
    creditor: Mapped[str | None] = mapped_column(String(80))
    kind: Mapped[str] = mapped_column(str_enum(DEBT_KINDS, "debt_kind"), default="other")
    status: Mapped[str] = mapped_column(str_enum(DEBT_STATUSES, "debt_status"), default="active")
    original_cents: Mapped[int] = mapped_column(BigInteger)
    installments_total: Mapped[int] = mapped_column(SmallInteger)
    installment_cents: Mapped[int] = mapped_column(BigInteger)
    installments_paid_before: Mapped[int] = mapped_column(SmallInteger, default=0)
    first_due_date: Mapped[date] = mapped_column(Date)
    # Juros mensais em pontos-base (1,99% = 199). Apenas informativo.
    interest_monthly_bp: Mapped[int | None] = mapped_column(Integer)
    account_id: Mapped[str | None] = mapped_column(ForeignKey("accounts.id", ondelete="SET NULL"))
    category_id: Mapped[str | None] = mapped_column(ForeignKey("categories.id", ondelete="SET NULL"))
    notes: Mapped[str | None] = mapped_column(Text)


class Transaction(IdMixin, TimestampMixin, SoftDeleteMixin, SyncMixin, Base):
    """Toda movimentação financeira: receita, despesa ou transferência."""

    __tablename__ = "transactions"
    __table_args__ = (
        CheckConstraint("amount_cents > 0", name="amount_positive"),
        CheckConstraint(
            "(type = 'transfer' AND to_account_id IS NOT NULL AND to_account_id <> account_id)"
            " OR (type <> 'transfer' AND to_account_id IS NULL)",
            name="transfer_target",
        ),
        CheckConstraint(
            "(installment_plan_id IS NULL) = (installment_number IS NULL)", name="installment_pair"
        ),
        CheckConstraint("(recurrence_id IS NULL) = (occurrence_date IS NULL)", name="recurrence_pair"),
        CheckConstraint("(debt_id IS NULL) = (debt_installment IS NULL)", name="debt_pair"),
        CheckConstraint("version >= 1", name="version"),
        # Impede lançar duas vezes a mesma ocorrência de uma recorrência / parcela
        UniqueConstraint("recurrence_id", "occurrence_date", name="uq_transactions_occurrence"),
        UniqueConstraint("installment_plan_id", "installment_number", name="uq_transactions_installment"),
        UniqueConstraint("debt_id", "debt_installment", name="uq_transactions_debt_installment"),
        # Extrato importado duas vezes não duplica lançamentos
        UniqueConstraint("user_id", "import_ref", name="uq_transactions_import_ref"),
        Index("ix_transactions_user_date", "user_id", "occurred_on"),
        Index("ix_transactions_user_category", "user_id", "category_id"),
        Index("ix_transactions_user_status", "user_id", "status"),
        Index("ix_transactions_user_updated", "user_id", "updated_at"),
        Index("ix_transactions_account", "account_id"),
        Index("ix_transactions_to_account", "to_account_id"),
        Index("ix_transactions_debt", "debt_id"),
    )

    user_id: Mapped[str] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"))
    account_id: Mapped[str] = mapped_column(ForeignKey("accounts.id", ondelete="RESTRICT"))
    to_account_id: Mapped[str | None] = mapped_column(ForeignKey("accounts.id", ondelete="RESTRICT"))
    type: Mapped[str] = mapped_column(str_enum(TX_TYPES, "tx_type"))
    status: Mapped[str] = mapped_column(str_enum(TX_STATUSES, "tx_status"), default="paid")
    amount_cents: Mapped[int] = mapped_column(BigInteger)
    occurred_on: Mapped[date] = mapped_column(Date)
    description: Mapped[str] = mapped_column(String(200))
    notes: Mapped[str | None] = mapped_column(Text)
    category_id: Mapped[str | None] = mapped_column(ForeignKey("categories.id", ondelete="SET NULL"))
    payment_method: Mapped[str | None] = mapped_column(str_enum(PAYMENT_METHODS, "tx_payment"))
    is_fixed: Mapped[bool] = mapped_column(Boolean, default=False)
    source: Mapped[str] = mapped_column(str_enum(TX_SOURCES, "tx_source"), default="manual")
    # Cartão de crédito: mês da fatura (1º dia do mês), calculado pelo sistema
    invoice_month: Mapped[date | None] = mapped_column(Date)
    recurrence_id: Mapped[str | None] = mapped_column(ForeignKey("recurrences.id", ondelete="SET NULL"))
    occurrence_date: Mapped[date | None] = mapped_column(Date)
    installment_plan_id: Mapped[str | None] = mapped_column(
        ForeignKey("installment_plans.id", ondelete="CASCADE")
    )
    installment_number: Mapped[int | None] = mapped_column(SmallInteger)
    debt_id: Mapped[str | None] = mapped_column(ForeignKey("debts.id", ondelete="SET NULL"))
    debt_installment: Mapped[int | None] = mapped_column(SmallInteger)
    import_ref: Mapped[str | None] = mapped_column(String(64))


class Budget(IdMixin, TimestampMixin, SoftDeleteMixin, SyncMixin, Base):
    """Limite mensal de gasto para uma categoria."""

    __tablename__ = "budgets"
    __table_args__ = (
        UniqueConstraint("user_id", "category_id", name="uq_budgets_user_category"),
        CheckConstraint("amount_cents > 0", name="amount_positive"),
    )

    user_id: Mapped[str] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"))
    category_id: Mapped[str] = mapped_column(ForeignKey("categories.id", ondelete="CASCADE"))
    amount_cents: Mapped[int] = mapped_column(BigInteger)


class Goal(IdMixin, TimestampMixin, SoftDeleteMixin, SyncMixin, Base):
    """Meta financeira. Se ligada a uma conta, o progresso é o saldo dessa conta."""

    __tablename__ = "goals"
    __table_args__ = (
        CheckConstraint("target_cents > 0", name="target_positive"),
        CheckConstraint("saved_cents >= 0", name="saved_non_negative"),
    )

    user_id: Mapped[str] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    name: Mapped[str] = mapped_column(String(80))
    target_cents: Mapped[int] = mapped_column(BigInteger)
    saved_cents: Mapped[int] = mapped_column(BigInteger, default=0)
    target_date: Mapped[date | None] = mapped_column(Date)
    account_id: Mapped[str | None] = mapped_column(ForeignKey("accounts.id", ondelete="SET NULL"))


class CategorizationRule(IdMixin, TimestampMixin, Base):
    """Aprendizado: palavra-chave → categoria, gerado a partir das correções do usuário."""

    __tablename__ = "categorization_rules"
    __table_args__ = (UniqueConstraint("user_id", "keyword", name="uq_rules_user_keyword"),)

    user_id: Mapped[str] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"))
    keyword: Mapped[str] = mapped_column(String(80))
    category_id: Mapped[str] = mapped_column(ForeignKey("categories.id", ondelete="CASCADE"))
    hits: Mapped[int] = mapped_column(Integer, default=1)
