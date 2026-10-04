export type TxType = "income" | "expense" | "transfer";
export type TxStatus = "paid" | "pending";
export type PaymentMethod = "pix" | "debit" | "credit" | "cash" | "boleto" | "transfer" | "other";
export type AccountKind = "checking" | "savings" | "cash" | "wallet" | "credit_card" | "investment" | "other";

export interface User {
  id: string;
  email: string;
  name: string;
  settings: { mode?: "basic" | "advanced"; default_account_id?: string };
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
  kind: "pending" | "recurrence" | "invoice";
  id: string;
  date: string;
  type: TxType;
  description: string;
  amount_cents: number;
  overdue: boolean;
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
  engine: "local" | "ai";
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
}

export interface AuditEntry {
  id: string;
  entity: string;
  entity_id: string | null;
  action: string;
  summary: string;
  created_at: string;
}
