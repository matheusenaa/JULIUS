import { AlertTriangle, ArrowDownLeft, ArrowUpRight, Briefcase, CalendarClock, Plus } from "lucide-react";
import { useState, type FormEvent } from "react";
import { Link, useNavigate } from "react-router";

import { useToast } from "../components/Toast";
import { AccountSelect, CategorySelect, TransactionForm } from "../components/TransactionForm";
import { Button, EmptyState, ErrorState, Field, Sheet, Skeleton } from "../components/ui";
import { api, errorMessage } from "../lib/api";
import { brl, fullDate, parseMoney, PAYMENT_LABEL, shortDate, STATUS_LABEL, todayIso } from "../lib/format";
import { invalidateFinance, useAccounts, useCategories, useTimeline } from "../lib/queries";
import type { Category, PaymentMethod, Transaction, TimelineEvent } from "../lib/types";

type Preset = {
  key: string;
  label: string;
  type: "income" | "expense";
  category?: string;
  repeat?: "monthly" | "none";
  installments?: boolean;
  route?: string;
};

const PRESETS: Preset[] = [
  { key: "salary", label: "Salário", type: "income", category: "Salário", repeat: "monthly" },
  { key: "income", label: "Receita", type: "income", repeat: "none" },
  { key: "bill", label: "Conta (luz, água…)", type: "expense", category: "Contas", repeat: "monthly" },
  { key: "rent", label: "Aluguel", type: "expense", category: "Aluguel", repeat: "monthly" },
  { key: "subscription", label: "Assinatura", type: "expense", category: "Streaming", repeat: "monthly" },
  { key: "installment", label: "Parcela / carnê", type: "expense", repeat: "none", installments: true },
  { key: "card", label: "Compra no cartão", type: "expense", repeat: "none", installments: true },
  { key: "debt", label: "Dívida, empréstimo ou financiamento", type: "expense", route: "/dividas?nova=1" },
  { key: "other", label: "Outro compromisso", type: "expense", repeat: "none" },
];

function findCat(cats: Category[], name: string | undefined, kind: string) {
  if (!name) return "";
  return cats.find((c) => c.name === name && c.kind === kind)?.id ?? "";
}

function FutureForm({ preset, onDone }: { preset: Preset; onDone: () => void }) {
  const toast = useToast();
  const accounts = useAccounts().data ?? [];
  const categories = useCategories().data ?? [];
  const cards = accounts.filter((a) => a.kind === "credit_card");
  const [description, setDescription] = useState(preset.key === "other" || preset.key === "income" ? "" : preset.label.split(" (")[0]);
  const [amount, setAmount] = useState("");
  const [date, setDate] = useState(todayIso());
  const [accountId, setAccountId] = useState(
    preset.key === "card" ? cards[0]?.id ?? "" : accounts.find((a) => a.kind !== "credit_card")?.id ?? "",
  );
  const [categoryId, setCategoryId] = useState(findCat(categories, preset.category, preset.type));
  const [payment, setPayment] = useState<PaymentMethod | "">("");
  const [repeat, setRepeat] = useState<"none" | "monthly" | "weekly" | "yearly">(preset.repeat === "monthly" ? "monthly" : "none");
  const [installments, setInstallments] = useState("1");
  const [status, setStatus] = useState<"pending" | "confirmed">("pending");
  const [notes, setNotes] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [saving, setSaving] = useState(false);

  async function submit(e: FormEvent) {
    e.preventDefault();
    const cents = parseMoney(amount);
    if (!description.trim()) return setError("Descreva o compromisso.");
    if (!cents) return setError("Informe o valor. Ex.: 99,90");
    if (!accountId) return setError("Escolha a conta.");
    setSaving(true);
    setError(null);
    try {
      if (repeat !== "none") {
        await api("/api/recurrences", {
          body: {
            type: preset.type, account_id: accountId, category_id: categoryId || null, description: description.trim(),
            amount_cents: cents, payment_method: payment || null, is_fixed: true, frequency: repeat,
            day_of_month: repeat === "monthly" ? Number(date.slice(8)) : null, start_date: date,
          },
        });
        toast(`${description.trim()}: previsto ${repeat === "monthly" ? `todo dia ${Number(date.slice(8))}` : "com repetição"}.`);
      } else {
        const n = Number(installments) || 1;
        await api("/api/transactions", {
          body: {
            type: preset.type, account_id: accountId, category_id: categoryId || null, description: description.trim(),
            amount_cents: cents, occurred_on: date, payment_method: payment || null, status,
            installments: preset.type === "expense" ? n : 1, notes: notes.trim() || null,
          },
        });
        toast(n > 1 ? `${n} parcelas previstas.` : "Lançamento futuro registrado.");
      }
      invalidateFinance();
      onDone();
    } catch (err) {
      setError(errorMessage(err));
    } finally {
      setSaving(false);
    }
  }

  return (
    <form className="form" onSubmit={submit}>
      <Field label="Descrição">
        <input className="input" value={description} maxLength={200} onChange={(e) => setDescription(e.target.value)} autoFocus />
      </Field>
      <div className="form-row">
        <Field label={preset.installments ? "Valor total (R$)" : "Valor (R$)"}>
          <input className="input num" inputMode="decimal" placeholder="0,00" value={amount} onChange={(e) => setAmount(e.target.value)} />
        </Field>
        <Field label={repeat === "none" ? "Data / vencimento" : "Primeiro vencimento"}>
          <input className="input" type="date" value={date} onChange={(e) => setDate(e.target.value)} />
        </Field>
      </div>
      <div className="form-row">
        <Field label="Conta ou cartão">
          <AccountSelect accounts={accounts} value={accountId} onChange={setAccountId} />
        </Field>
        <Field label="Categoria">
          <CategorySelect categories={categories} kind={preset.type} value={categoryId} onChange={setCategoryId} />
        </Field>
      </div>
      <div className="form-row">
        <Field label="Repetição">
          <select className="select" value={repeat} onChange={(e) => setRepeat(e.target.value as typeof repeat)}>
            <option value="none">Não repete</option>
            <option value="monthly">Todo mês</option>
            <option value="weekly">Toda semana</option>
            <option value="yearly">Todo ano</option>
          </select>
        </Field>
        {repeat === "none" && preset.type === "expense" ? (
          <Field label="Parcelas" hint={Number(installments) > 1 ? "O valor é o TOTAL; o JULIUS divide." : undefined}>
            <input className="input" type="number" min={1} max={120} value={installments} onChange={(e) => setInstallments(e.target.value)} />
          </Field>
        ) : (
          <Field label="Forma de pagamento">
            <select className="select" value={payment} onChange={(e) => setPayment(e.target.value as PaymentMethod)}>
              <option value="">Não informar</option>
              {Object.entries(PAYMENT_LABEL).map(([k, v]) => <option key={k} value={k}>{v}</option>)}
            </select>
          </Field>
        )}
      </div>
      {repeat === "none" && (
        <>
          <div className="chips" role="group" aria-label="Status">
            <button type="button" className="chip" aria-pressed={status === "pending"} onClick={() => setStatus("pending")}>Previsto</button>
            <button type="button" className="chip" aria-pressed={status === "confirmed"} onClick={() => setStatus("confirmed")}>Confirmado (ex.: agendado)</button>
          </div>
          <Field label="Observação (opcional)">
            <textarea className="textarea" value={notes} maxLength={2000} onChange={(e) => setNotes(e.target.value)} />
          </Field>
        </>
      )}
      {error && <div className="alert danger" role="alert">{error}</div>}
      <div className="form-actions">
        <Button type="submit" variant="primary" loading={saving}>Salvar</Button>
      </div>
    </form>
  );
}

function EventActions({ e, onEdit }: { e: TimelineEvent; onEdit: (id: string) => void }) {
  const toast = useToast();
  const [busy, setBusy] = useState<string | null>(null);
  const run = async (key: string, fn: () => Promise<unknown>, ok: string) => {
    setBusy(key);
    try {
      await fn();
      invalidateFinance();
      toast(ok);
    } catch (err) {
      toast(errorMessage(err), { kind: "error" });
    } finally {
      setBusy(null);
    }
  };
  const verb = e.flow === "in" ? "Recebi" : "Paguei";
  if (e.kind === "transaction") {
    const version = e.extra.version as number;
    const patch = (body: Record<string, unknown>) => api(`/api/transactions/${e.ref_id}`, { method: "PATCH", body: { version, ...body } });
    return (
      <div className="chips">
        <Button size="small" loading={busy === "pay"} onClick={() => run("pay", () => patch({ status: "paid", occurred_on: e.date < todayIso() ? todayIso() : e.date }), `${e.description}: marcado como ${e.flow === "in" ? "recebido" : "pago"}.`)}>{verb}</Button>
        {e.status !== "confirmed" && e.status !== "scheduled" && (
          <Button size="small" variant="ghost" loading={busy === "conf"} onClick={() => run("conf", () => patch({ status: "confirmed" }), "Confirmado.")}>Confirmar</Button>
        )}
        <Button size="small" variant="ghost" onClick={() => onEdit(e.ref_id)}>Editar</Button>
        <Button size="small" variant="ghost" loading={busy === "cancel"} onClick={() => run("cancel", () => patch({ status: "canceled" }), "Cancelado. Continua no histórico, fora dos saldos.")}>Cancelar</Button>
      </div>
    );
  }
  if (e.kind === "recurrence") {
    const occ = e.extra.occurrence_date as string;
    return (
      <div className="chips">
        <Button size="small" loading={busy === "pay"} onClick={() => run("pay", () => api(`/api/recurrences/${e.ref_id}/confirm`, { body: { occurrence_date: occ } }), `${e.description}: lançado.`)}>{verb}</Button>
        <Button size="small" variant="ghost" loading={busy === "skip"} onClick={() => run("skip", () => api(`/api/recurrences/${e.ref_id}/skip`, { body: { occurrence_date: occ } }), "Ocorrência pulada.")}>Pular este mês</Button>
      </div>
    );
  }
  if (e.kind === "debt") {
    return (
      <Button size="small" loading={busy === "pay"} onClick={() => run("pay", () => api(`/api/debts/${e.ref_id}/pay`, { body: {} }), "Parcela registrada como paga.")}>Paguei a parcela</Button>
    );
  }
  return <Link className="btn small" to="/contas">Pagar fatura</Link>;
}

export default function Futures() {
  const navigate = useNavigate();
  const [days, setDays] = useState(60);
  const [flow, setFlow] = useState<"all" | "out" | "in" | "late">("all");
  const [preset, setPreset] = useState<Preset | null>(null);
  const [choosing, setChoosing] = useState(false);
  const [editing, setEditing] = useState<Transaction | null>(null);
  const { data, isLoading, error, refetch } = useTimeline(days);
  const toast = useToast();

  const events = (data?.events ?? []).filter((e) =>
    flow === "all" ? true : flow === "late" ? e.status === "overdue" : e.flow === flow,
  );

  async function openEdit(id: string) {
    try {
      setEditing(await api<Transaction>(`/api/transactions/${id}`));
    } catch (err) {
      toast(errorMessage(err), { kind: "error" });
    }
  }

  return (
    <>
      <div className="page-head">
        <div>
          <h1>Futuros</h1>
          <p>O que ainda vai entrar e sair — e como fica seu saldo depois de cada um</p>
        </div>
        <div className="chips">
          <Button onClick={() => setPreset(PRESETS[0])}>
            <Briefcase size={16} /> Cadastrar salário
          </Button>
          <Button variant="primary" onClick={() => setChoosing(true)}>
            <Plus size={16} /> Novo lançamento futuro
          </Button>
        </div>
      </div>

      <div className="panel" style={{ marginBottom: 16, display: "flex", gap: 12, flexWrap: "wrap", alignItems: "center" }}>
        <div className="chips">
          {([["all", "Tudo"], ["out", "A pagar"], ["in", "A receber"], ["late", "Atrasados"]] as const).map(([k, l]) => (
            <button key={k} className="chip" aria-pressed={flow === k} onClick={() => setFlow(k)}>{l}</button>
          ))}
        </div>
        <div className="segmented" style={{ marginLeft: "auto" }}>
          {[30, 60, 90, 180].map((d) => <button key={d} aria-pressed={days === d} onClick={() => setDays(d)}>{d}d</button>)}
        </div>
      </div>

      {data && (
        <div className="stat-row" style={{ marginBottom: 16 }}>
          <div className="panel stat"><div className="label">Saldo hoje</div><div className="value num">{brl(data.start_balance_cents)}</div></div>
          <div className="panel stat" style={{ marginTop: 0 }}><div className="label">A receber</div><div className="value num income">{brl(data.income_cents)}</div></div>
          <div className="panel stat" style={{ marginTop: 0 }}><div className="label">A pagar</div><div className="value num">{brl(data.expense_cents)}</div></div>
          <div className="panel stat" style={{ marginTop: 0 }}>
            <div className="label">Saldo em {days} dias*</div>
            <div className="value num" style={data.end_balance_cents < 0 ? { color: "var(--danger)" } : undefined}>{brl(data.end_balance_cents)}</div>
          </div>
        </div>
      )}

      <section className="panel">
        {isLoading && <Skeleton lines={6} />}
        {error && !data && <ErrorState message={errorMessage(error)} onRetry={() => refetch()} />}
        {data && events.length === 0 && (
          <EmptyState icon={CalendarClock} title="Nada previsto neste período" text="Cadastre seu salário, aluguel, contas e parcelas para ver como seu saldo vai ficar." />
        )}
        <ol className="list">
          {events.map((e) => {
            const st = STATUS_LABEL[e.status];
            return (
              <li key={`${e.kind}${e.ref_id}${e.date}${e.description}`} className="row" style={{ flexWrap: "wrap" }}>
                <span className="cat-dot" aria-hidden="true" style={{ color: e.flow === "in" ? "var(--income)" : undefined }}>
                  {e.flow === "in" ? <ArrowDownLeft size={17} /> : <ArrowUpRight size={17} />}
                </span>
                <div className="main-col" style={{ minWidth: 160 }}>
                  <div className="title">{e.description}</div>
                  <div className="sub">
                    {fullDate(e.date)}
                    {st && <span className={`badge ${st.tone}`} style={{ marginLeft: 6 }}>{e.status === "overdue" && <AlertTriangle size={10} />} {st.label}</span>}
                  </div>
                </div>
                <div style={{ textAlign: "right" }}>
                  <div className={`num ${e.flow === "in" ? "income" : ""}`}>{e.flow === "in" ? "+" : "−"} {brl(e.amount_cents)}</div>
                  <div className="small muted num">saldo depois: {brl(e.balance_after)}</div>
                </div>
                <div style={{ width: "100%", paddingLeft: 48 }}>
                  <EventActions e={e} onEdit={openEdit} />
                </div>
              </li>
            );
          })}
        </ol>
        {data && <p className="small muted" style={{ marginTop: 12 }}>* Estimativa: considera só o que está cadastrado. Itens atrasados entram como se acontecessem hoje. Menor saldo previsto: {brl(data.lowest.balance_cents)} em {shortDate(data.lowest.date)}.</p>}
      </section>

      {choosing && (
        <Sheet title="O que você quer prever?" onClose={() => setChoosing(false)}>
          <div className="chips">
            {PRESETS.map((p) => (
              <button key={p.key} className="chip" onClick={() => { setChoosing(false); if (p.route) navigate(p.route); else setPreset(p); }}>
                {p.label}
              </button>
            ))}
          </div>
        </Sheet>
      )}
      {preset && (
        <Sheet title={preset.label} onClose={() => setPreset(null)}>
          <FutureForm preset={preset} onDone={() => setPreset(null)} />
        </Sheet>
      )}
      {editing && (
        <Sheet title="Editar lançamento" onClose={() => setEditing(null)}>
          <TransactionForm editing={editing} onDone={() => setEditing(null)} />
        </Sheet>
      )}
    </>
  );
}
