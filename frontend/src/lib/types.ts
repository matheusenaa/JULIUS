export type TxType = "income" | "expense" | "transfer";
export type TxStatus = "pending" | "confirmed" | "paid" | "canceled";
export type PaymentMethod = "pix" | "debit" | "credit" | "cash" | "boleto" | "transfer" | "other";
export type AccountKind = "checking" | "savings" | "cash" | "wallet" | "credit_card" | "investment" | "other";

export interface User {
  id: string;
  email: string;
  name: string;
  settings: {
    mode?: "basic" | "advanced";
    default_account_id?: string;
    currency?: "BRL" | "USD" | "EUR";
    ai_enabled?: boolean;
    ai_share_descriptions?: boolean;
    ai_custom_instructions?: string;
    notify_due?: boolean;
    onboarded?: boolean;
  };
}

export interface Invoice {
  invoice_month: string;
  due_date: string;
  total_cents: number;
  paid_cents: number;
  remaining_cents: number;
}

export interface Account {
  id: string;
  name: string;
  kind: AccountKind;
  currency: string;
  color: string | null;
  include_in_total: boolean;
  initial_balance_cents: number;
  balance_cents: number;
  credit_limit_cents: number | null;
  closing_day: number | null;
  due_day: number | null;
  used_cents: number | null;
  available_cents: number | null;
  current_invoice: Invoice | null;
}

export interface Category {
  id: string;
  name: string;
  kind: "income" | "expense";
  parent_id: string | null;
  icon: string | null;
  color: string | null;
}

export interface Transaction {
  id: string;
  type: TxType;
  status: TxStatus;
  account_id: string;
  to_account_id: string | null;
  amount_cents: number;
  occurred_on: string;
  description: string;
  notes: string | null;
  category_id: string | null;
  payment_method: PaymentMethod | null;
  is_fixed: boolean;
  source: string;
  invoice_month: string | null;
  recurrence_id: string | null;
  installment_plan_id: string | null;
  installment_number: number | null;
  installment_total: number | null;
  debt_id?: string | null;
  debt_installment?: number | null;
  version: number;
  created_at: string;
  updated_at: string;
  /** Somente no cliente: aguardando sincronização */
  _queued?: boolean;
}

export interface TransactionInput {
  id?: string;
  type: TxType;
  account_id: string;
  to_account_id?: string | null;
  amount_cents: number;
  occurred_on: string;
  description: string;
  notes?: string | null;
  category_id?: string | null;
  payment_method?: PaymentMethod | null;
  is_fixed?: boolean;
  status?: TxStatus;
  installments?: number;
  source?: string;
}

export interface TransactionPage {
  items: Transaction[];
  total: number;
  page: number;
  page_size: number;
  income_cents: number;
  expense_cents: number;
}

export interface Recurrence {
  id: string;
  type: "income" | "expense";
  account_id: string;
  category_id: string | null;
  description: string;
  amount_cents: number;
  payment_method: PaymentMethod | null;
  is_fixed: boolean;
  frequency: "weekly" | "monthly" | "yearly";
  day_of_month: number | null;
  start_date: string;
  end_date: string | null;
  next_date: string | null;
}

export interface UpcomingItem {
  kind: "transaction" | "recurrence" | "invoice" | "debt";
  id: string;
  date: string;
  type: TxType;
  description: string;
  amount_cents: number;
  overdue: boolean;
  status?: string;
  extra?: Record<string, unknown>;
}

export interface CategoryTotal {
  category_id: string | null;
  name: string;
  color: string | null;
  icon: string | null;
  total_cents: number;
  share: number;
  previous_cents?: number;
}

export interface BudgetStatus {
  id: string;
  category_id: string;
  name: string;
  color: string | null;
  amount_cents: number;
  spent_cents: number;
  ratio: number;
}

export interface GoalStatus {
  id: string;
  name: string;
  target_cents: number;
  saved_cents: number;
  target_date: string | null;
  account_id: string | null;
  progress_cents: number;
  monthly_needed_cents: number | null;
}

export interface Dashboard {
  today: string;
  balance_cents: number;
  month: {
    start: string;
    end: string;
    income_cents: number;
    expense_cents: number;
    fixed_cents: number;
    variable_cents: number;
  };
  projection: {
    current_cents: number;
    pending_cents: number;
    recurring_cents: number;
    card_invoices_cents: number;
    projected_cents: number;
    until: string;
  };
  upcoming: UpcomingItem[];
  recent: Transaction[];
  categories: CategoryTotal[];
  budgets: BudgetStatus[];
  goals: GoalStatus[];
  cards: { id: string; name: string; open_cents: number; next_due: string | null }[];
  insights: { level: "info" | "warning" | "danger"; text: string }[];
}

export interface Forecast {
  available: boolean;
  reason?: string;
  is_estimate?: boolean;
  based_on_months?: number;
  avg_net_cents?: number;
  current_cents: number;
  points?: { month: string; balance_cents: number }[];
}

export interface Report {
  period: "day" | "week" | "month" | "year";
  start: string;
  end: string;
  income_cents: number;
  expense_cents: number;
  net_cents: number;
  savings_rate: number | null;
  previous: { start: string; end: string; income_cents: number; expense_cents: number; net_cents: number };
  by_category: CategoryTotal[];
  fixed_cents: number;
  variable_cents: number;
  top_expenses: { id: string; date: string; description: string; amount_cents: number; category_id: string | null }[];
  series: { label: string; income: number; expense: number }[];
  forecast: Forecast;
}

export interface Proposal {
  text?: string;
  type: TxType;
  amount_cents: number | null;
  occurred_on: string;
  description: string;
  category_id: string | null;
  account_id: string | null;
  to_account_id: string | null;
  payment_method: PaymentMethod | null;
  installments: number;
  status: TxStatus;
  is_fixed: boolean;
  recurrence: { frequency: "weekly" | "monthly" | "yearly"; day_of_month: number } | null;
  notes?: string | null;
  engine: "local" | "ai" | "rules" | "rules+ai";
  ai_error?: boolean;
  learned?: boolean;
  confidence?: number;
  missing: string[];
}

export interface AssistantAnswer {
  answer: string;
  intent: string;
  engine: string;
  is_estimate: boolean;
  conversation_id: string;
  actions?: AIActionItem[];
}

export interface AuditEntry {
  id: string;
  entity: string;
  entity_id: string | null;
  action: string;
  summary: string;
  created_at: string;
}

// ---------- Atualização 2 ----------
export type EventStatus = "pending" | "confirmed" | "overdue" | "scheduled";

export interface TimelineEvent {
  date: string;
  effective: string;
  kind: "transaction" | "recurrence" | "invoice" | "debt";
  flow: "in" | "out";
  amount_cents: number;
  description: string;
  status: EventStatus;
  ref_id: string;
  account_id: string | null;
  category_id: string | null;
  extra: Record<string, unknown>;
  balance_after: number;
}

export interface Timeline {
  today: string;
  until: string;
  start_balance_cents: number;
  end_balance_cents: number;
  income_cents: number;
  expense_cents: number;
  lowest: { date: string; balance_cents: number };
  events: TimelineEvent[];
}

export interface DebtItem {
  id: string;
  name: string;
  creditor: string | null;
  kind: string;
  status: "active" | "canceled";
  original_cents: number;
  installments_total: number;
  installment_cents: number;
  installments_paid_before: number;
  first_due_date: string;
  interest_monthly_bp: number | null;
  account_id: string | null;
  category_id: string | null;
  notes: string | null;
  paid_installments: number;
  remaining_installments: number;
  paid_cents: number;
  remaining_cents: number;
  total_cents: number;
  next_due: string | null;
  end_date: string;
  situation: "em_dia" | "atrasada" | "quitada" | "cancelada";
  overdue_installments: number;
}

export interface CalendarDay {
  date: string;
  in_cents: number;
  out_cents: number;
  events: { description: string; amount_cents: number; flow: "in" | "out"; status: EventStatus; kind: string }[];
}

export interface Overview {
  today: string;
  horizon_days: number;
  kpis: {
    balance_cents: number;
    month_income_cents: number;
    month_expense_cents: number;
    projected_month_end_cents: number;
    projected_horizon_cents: number;
    to_pay_cents: number;
    to_receive_cents: number;
    overdue_count: number;
    debts_remaining_cents: number;
    installments_remaining_cents: number;
  };
  timeline: { start_balance_cents: number; end_balance_cents: number; lowest: { date: string; balance_cents: number }; events: TimelineEvent[] };
  projection: { date: string; balance_cents: number }[];
  history: { date: string; balance_cents: number }[];
  monthly: { month: string; income: number; expense: number }[];
  categories: CategoryTotal[];
  calendar: CalendarDay[];
  debts: { id: string; name: string; creditor: string | null; remaining_cents: number; remaining_installments: number; installments_total: number; next_due: string | null; situation: string }[];
  installments: { id: string; description: string; total_cents: number; installments: number; remaining_installments: number; remaining_cents: number; next_date: string | null }[];
  recurring: { monthly_in_cents: number; monthly_out_cents: number; count: number };
  goals: GoalStatus[];
  alerts: { level: "info" | "warning" | "danger"; text: string }[];
}

export interface DocumentItem {
  id: string;
  filename: string;
  content_type: string;
  size_bytes: number;
  title: string | null;
  kind: "receipt" | "bill" | "invoice" | "pix" | "statement" | "contract" | "other";
  status: "uploaded" | "review" | "confirmed" | "discarded";
  transaction_id: string | null;
  created_at: string;
  amount_cents: number | null;
  due_date: string | null;
  beneficiary: string | null;
  institution: string | null;
  barcode: string | null;
  barcode_valid: boolean | null;
  document_number: string | null;
  pix_key: string | null;
  engine: string | null;
  warnings: string[];
}

export interface AIActionItem {
  id: string;
  tool: string;
  summary: string;
  status: "pending" | "confirmed" | "rejected" | "expired" | "failed";
  result: Record<string, unknown> | null;
  created_at: string;
}

export interface SyncStatus {
  linked: boolean;
  remote_url: string | null;
  remote_email: string | null;
  last_sync_at: string | null;
  last_error: string | null;
  pending: number;
  conflicts: { id: string; entity: string; entity_id: string; local: Record<string, unknown>; remote: Record<string, unknown>; created_at: string }[];
}
