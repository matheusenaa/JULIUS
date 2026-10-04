const brlFmt = new Intl.NumberFormat("pt-BR", { style: "currency", currency: "BRL" });

/** Centavos → "R$ 1.234,56". Exibição apenas; nenhum cálculo financeiro é feito no cliente. */
export function brl(cents: number | null | undefined): string {
  if (cents === null || cents === undefined) return "—";
  return brlFmt.format(cents / 100);
}

export function signedBrl(cents: number, type: string): string {
  if (type === "income") return `+ ${brl(cents)}`;
  if (type === "expense") return `− ${brl(cents)}`;
  return brl(cents);
}

/** "1.234,56" | "1234.56" | "45" → centavos. Retorna null se inválido. */
export function parseMoney(input: string): number | null {
  const s = input.replace(/[R$\s]/g, "").trim();
  if (!s) return null;
  let normalized: string;
  if (s.includes(",")) normalized = s.replace(/\./g, "").replace(",", ".");
  else if (/^\d{1,3}(\.\d{3})+$/.test(s)) normalized = s.replace(/\./g, "");
  else normalized = s;
  if (!/^\d+(\.\d{1,2})?$/.test(normalized)) return null;
  const cents = Math.round(Number(normalized) * 100);
  return Number.isFinite(cents) && cents > 0 ? cents : null;
}

export function centsToInput(cents: number | null | undefined): string {
  if (!cents) return "";
  return (cents / 100).toFixed(2).replace(".", ",");
}

export function todayIso(): string {
  const d = new Date();
  return `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, "0")}-${String(d.getDate()).padStart(2, "0")}`;
}

function parseIso(iso: string): Date {
  const [y, m, d] = iso.slice(0, 10).split("-").map(Number);
  return new Date(y, m - 1, d);
}

export function shortDate(iso: string): string {
  return parseIso(iso).toLocaleDateString("pt-BR", { day: "2-digit", month: "2-digit" });
}

export function fullDate(iso: string): string {
  return parseIso(iso).toLocaleDateString("pt-BR");
}

export function dayLabel(iso: string): string {
  const today = todayIso();
  const d = parseIso(iso);
  const t = parseIso(today);
  const diff = Math.round((d.getTime() - t.getTime()) / 86400000);
  if (diff === 0) return "Hoje";
  if (diff === -1) return "Ontem";
  if (diff === 1) return "Amanhã";
  return d.toLocaleDateString("pt-BR", { weekday: "long", day: "numeric", month: "long" });
}

export function monthLabel(iso: string): string {
  const s = parseIso(iso).toLocaleDateString("pt-BR", { month: "long", year: "numeric" });
  return s.charAt(0).toUpperCase() + s.slice(1);
}

export function shortMonth(iso: string): string {
  return parseIso(iso).toLocaleDateString("pt-BR", { month: "short" }).replace(".", "");
}

export const TYPE_LABEL = { income: "Receita", expense: "Despesa", transfer: "Transferência" } as const;

export const PAYMENT_LABEL: Record<string, string> = {
  pix: "Pix",
  debit: "Débito",
  credit: "Crédito",
  cash: "Dinheiro",
  boleto: "Boleto",
  transfer: "Transferência",
  other: "Outro",
};

export const ACCOUNT_KIND_LABEL: Record<string, string> = {
  checking: "Conta corrente",
  savings: "Poupança",
  cash: "Dinheiro",
  wallet: "Carteira digital",
  credit_card: "Cartão de crédito",
  investment: "Investimentos",
  other: "Outra",
};

export const FREQUENCY_LABEL = { weekly: "Semanal", monthly: "Mensal", yearly: "Anual" } as const;
