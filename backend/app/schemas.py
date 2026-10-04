"""Contratos da API. Valores monetários trafegam em centavos (inteiros)."""

from datetime import date, datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, EmailStr, Field, field_validator, model_validator

AccountKind = Literal["checking", "savings", "cash", "wallet", "credit_card", "investment", "other"]
TxType = Literal["income", "expense", "transfer"]
TxStatus = Literal["paid", "pending"]
PaymentMethod = Literal["pix", "debit", "credit", "cash", "boleto", "transfer", "other"]
TxSource = Literal["manual", "quick_input", "ai", "ocr", "import", "recurrence"]
Frequency = Literal["weekly", "monthly", "yearly"]

MAX_CENTS = 10**12  # R$ 10 bilhões: protege contra erros de digitação absurdos
Cents = Field(gt=0, le=MAX_CENTS)
Color = Field(default=None, pattern=r"^#[0-9A-Fa-f]{6}$")


class _In(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)


class _Out(BaseModel):
    model_config = ConfigDict(from_attributes=True)


# ---------- Autenticação ----------
class RegisterIn(_In):
    email: EmailStr
    name: str = Field(min_length=1, max_length=80)
    password: str = Field(min_length=10, max_length=200)


class LoginIn(_In):
    email: EmailStr
    password: str = Field(min_length=1, max_length=200)


class PasswordChangeIn(_In):
    current_password: str = Field(min_length=1, max_length=200)
    new_password: str = Field(min_length=10, max_length=200)


class SettingsIn(_In):
    mode: Literal["basic", "advanced"] | None = None
    default_account_id: str | None = None
    name: str | None = Field(default=None, min_length=1, max_length=80)


class UserOut(_Out):
    id: str
    email: str
    name: str
    settings: dict


# ---------- Contas ----------
class AccountIn(_In):
    name: str = Field(min_length=1, max_length=60)
    kind: AccountKind
    initial_balance_cents: int = Field(default=0, ge=-MAX_CENTS, le=MAX_CENTS)
    color: str | None = Color
    include_in_total: bool = True
    credit_limit_cents: int | None = Field(default=None, ge=0, le=MAX_CENTS)
    closing_day: int | None = Field(default=None, ge=1, le=31)
    due_day: int | None = Field(default=None, ge=1, le=31)

    @model_validator(mode="after")
    def _card(self):
        if self.kind == "credit_card" and (self.closing_day is None or self.due_day is None):
            raise ValueError("Cartão de crédito precisa de dia de fechamento e de vencimento.")
        return self


class AccountUpdate(_In):
    name: str | None = Field(default=None, min_length=1, max_length=60)
    initial_balance_cents: int | None = Field(default=None, ge=-MAX_CENTS, le=MAX_CENTS)
    color: str | None = Color
    include_in_total: bool | None = None
    credit_limit_cents: int | None = Field(default=None, ge=0, le=MAX_CENTS)
    closing_day: int | None = Field(default=None, ge=1, le=31)
    due_day: int | None = Field(default=None, ge=1, le=31)


class InvoiceOut(BaseModel):
    invoice_month: date
    due_date: date
    total_cents: int
    paid_cents: int
    remaining_cents: int


class AccountOut(_Out):
    id: str
    name: str
    kind: str
    currency: str
    color: str | None
    include_in_total: bool
    initial_balance_cents: int
    balance_cents: int = 0
    credit_limit_cents: int | None
    closing_day: int | None
    due_day: int | None
    used_cents: int | None = None
    available_cents: int | None = None
    current_invoice: InvoiceOut | None = None


# ---------- Categorias ----------
class CategoryIn(_In):
    name: str = Field(min_length=1, max_length=60)
    kind: Literal["expense", "income"]
    parent_id: str | None = None
    icon: str | None = Field(default=None, max_length=40)
    color: str | None = Color


class CategoryUpdate(_In):
    name: str | None = Field(default=None, min_length=1, max_length=60)
    icon: str | None = Field(default=None, max_length=40)
    color: str | None = Color


class CategoryOut(_Out):
    id: str
    name: str
    kind: str
    parent_id: str | None
    icon: str | None
    color: str | None


# ---------- Transações ----------
class TransactionIn(_In):
    # UUID opcional gerado no cliente: torna a criação idempotente (sincronização offline)
    id: str | None = Field(default=None, pattern=r"^[0-9a-f-]{36}$")
    type: TxType
    account_id: str
    to_account_id: str | None = None
    amount_cents: int = Cents
    occurred_on: date
    description: str = Field(min_length=1, max_length=200)
    notes: str | None = Field(default=None, max_length=2000)
    category_id: str | None = None
    payment_method: PaymentMethod | None = None
    is_fixed: bool = False
    status: TxStatus = "paid"
    installments: int = Field(default=1, ge=1, le=120)
    source: TxSource = "manual"

    @model_validator(mode="after")
    def _rules(self):
        if self.type == "transfer":
            if not self.to_account_id or self.to_account_id == self.account_id:
                raise ValueError("Transferência precisa de uma conta de destino diferente da origem.")
            if self.installments > 1:
                raise ValueError("Transferências não podem ser parceladas.")
            self.category_id = None
        elif self.to_account_id:
            raise ValueError("Conta de destino só se aplica a transferências.")
        if self.installments > 1 and self.type != "expense":
            raise ValueError("Somente despesas podem ser parceladas.")
        return self


class TransactionUpdate(_In):
    version: int = Field(ge=1)
    account_id: str | None = None
    to_account_id: str | None = None
    amount_cents: int | None = Field(default=None, gt=0, le=MAX_CENTS)
    occurred_on: date | None = None
    description: str | None = Field(default=None, min_length=1, max_length=200)
    notes: str | None = Field(default=None, max_length=2000)
    category_id: str | None = None
    payment_method: PaymentMethod | None = None
    is_fixed: bool | None = None
    status: TxStatus | None = None


class TransactionOut(_Out):
    id: str
    type: str
    status: str
    account_id: str
    to_account_id: str | None
    amount_cents: int
    occurred_on: date
    description: str
    notes: str | None
    category_id: str | None
    payment_method: str | None
    is_fixed: bool
    source: str
    invoice_month: date | None
    recurrence_id: str | None
    installment_plan_id: str | None
    installment_number: int | None
    installment_total: int | None = None
    version: int
    created_at: datetime
    updated_at: datetime


class TransactionPage(BaseModel):
    items: list[TransactionOut]
    total: int
    page: int
    page_size: int
    income_cents: int
    expense_cents: int


# ---------- Recorrências ----------
class RecurrenceIn(_In):
    type: Literal["income", "expense"]
    account_id: str
    category_id: str | None = None
    description: str = Field(min_length=1, max_length=200)
    amount_cents: int = Cents
    payment_method: PaymentMethod | None = None
    is_fixed: bool = True
    frequency: Frequency = "monthly"
    day_of_month: int | None = Field(default=None, ge=1, le=31)
    start_date: date
    end_date: date | None = None

    @model_validator(mode="after")
    def _dates(self):
        if self.end_date and self.end_date < self.start_date:
            raise ValueError("A data final não pode ser anterior à inicial.")
        return self


class RecurrenceUpdate(_In):
    account_id: str | None = None
    category_id: str | None = None
    description: str | None = Field(default=None, min_length=1, max_length=200)
    amount_cents: int | None = Field(default=None, gt=0, le=MAX_CENTS)
    payment_method: PaymentMethod | None = None
    is_fixed: bool | None = None
    day_of_month: int | None = Field(default=None, ge=1, le=31)
    end_date: date | None = None


class RecurrenceOut(_Out):
    id: str
    type: str
    account_id: str
    category_id: str | None
    description: str
    amount_cents: int
    payment_method: str | None
    is_fixed: bool
    frequency: str
    day_of_month: int | None
    start_date: date
    end_date: date | None
    next_date: date | None = None


class OccurrenceOut(BaseModel):
    recurrence_id: str
    date: date
    type: str
    description: str
    amount_cents: int
    account_id: str
    category_id: str | None
    overdue: bool


class OccurrenceConfirmIn(_In):
    occurrence_date: date
    occurred_on: date | None = None
    amount_cents: int | None = Field(default=None, gt=0, le=MAX_CENTS)
    account_id: str | None = None


class OccurrenceSkipIn(_In):
    occurrence_date: date


# ---------- Orçamentos e metas ----------
class BudgetIn(_In):
    category_id: str
    amount_cents: int = Cents


class BudgetOut(_Out):
    id: str
    category_id: str
    amount_cents: int
    spent_cents: int = 0


class GoalIn(_In):
    name: str = Field(min_length=1, max_length=80)
    target_cents: int = Cents
    saved_cents: int = Field(default=0, ge=0, le=MAX_CENTS)
    target_date: date | None = None
    account_id: str | None = None


class GoalUpdate(_In):
    name: str | None = Field(default=None, min_length=1, max_length=80)
    target_cents: int | None = Field(default=None, gt=0, le=MAX_CENTS)
    saved_cents: int | None = Field(default=None, ge=0, le=MAX_CENTS)
    target_date: date | None = None
    account_id: str | None = None


class GoalOut(_Out):
    id: str
    name: str
    target_cents: int
    saved_cents: int
    target_date: date | None
    account_id: str | None
    progress_cents: int = 0
    monthly_needed_cents: int | None = None


# ---------- Quick input / assistente ----------
class QuickInputIn(_In):
    text: str = Field(min_length=1, max_length=500)

    @field_validator("text")
    @classmethod
    def _not_blank(cls, v: str) -> str:
        if not v.strip():
            raise ValueError("Digite o que aconteceu.")
        return v


class AskIn(_In):
    question: str = Field(min_length=1, max_length=500)
    conversation_id: str | None = None


class AuditOut(_Out):
    id: str
    entity: str
    entity_id: str | None
    action: str
    summary: str
    changes: dict | None
    created_at: datetime
