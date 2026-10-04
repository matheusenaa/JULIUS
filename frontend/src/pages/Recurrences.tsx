import { CalendarClock, Plus, Repeat } from "lucide-react";
import { useState, type FormEvent } from "react";

import { useToast } from "../components/Toast";
import { AccountSelect, CategorySelect } from "../components/TransactionForm";
import { Amount, Button, EmptyState, ErrorState, Field, Sheet, Skeleton } from "../components/ui";
import { api, errorMessage } from "../lib/api";
import { brl, centsToInput, FREQUENCY_LABEL, fullDate, parseMoney, shortDate, todayIso } from "../lib/format";
import { invalidateFinance, useAccounts, useCategories, useOccurrences, useRecurrences } from "../lib/queries";
import type { Recurrence } from "../lib/types";

function RecurrenceForm({ rec, onDone }: { rec?: Recurrence; onDone: () => void }) {
  const toast = useToast();
  const accounts = useAccounts().data ?? [];
  const categories = useCategories().data ?? [];
  const [type, setType] = useState<"expense" | "income">(rec?.type ?? "expense");
  const [description, setDescription] = useState(rec?.description ?? "");
  const [amount, setAmount] = useState(centsToInput(rec?.amount_cents));
  const [accountId, setAccountId] = useState(rec?.account_id ?? accounts.find((a) => a.kind !== "credit_card")?.id ?? "");
  const [categoryId, setCategoryId] = useState(rec?.category_id ?? "");
  const [frequency, setFrequency] = useState<Recurrence["frequency"]>(rec?.frequency ?? "monthly");
  const [day, setDay] = useState(String(rec?.day_of_month ?? new Date().getDate()));
  const [start, setStart] = useState(rec?.start_date ?? todayIso());
  const [end, setEnd] = useState(rec?.end_date ?? "");
  const [error, setError] = useState<string | null>(null);
  const [saving, setSaving] = useState(false);
  const [confirmEnd, setConfirmEnd] = useState(false);

  async function submit(e: FormEvent) {
    e.preventDefault();
    const cents = parseMoney(amount);
    if (!description.trim()) return setError("Descreva a recorrência. Ex.: Aluguel");
    if (!cents) return setError("Informe o valor.");
    if (!accountId) return setError("Escolha a conta.");
    const dom = Number(day);
    if (frequency === "monthly" && (!Number.isInteger(dom) || dom < 1 || dom > 31)) return setError("Dia do mês entre 1 e 31.");
    setSaving(true);
    setError(null);
    const common = {
      description: description.trim(),
      amount_cents: cents,
      account_id: accountId,
      category_id: categoryId || null,
      day_of_month: frequency === "monthly" ? dom : null,
      end_date: end || null,
    };
    try {
      if (rec) await api(`/api/recurrences/${rec.id}`, { method: "PATCH", body: common });
      else await api("/api/recurrences", { body: { ...common, type, frequency, start_date: start, is_fixed: true } });
      invalidateFinance();
      toast(rec ? "Recorrência atualizada. Vale para as próximas ocorrências." : "Recorrência criada.");
      onDone();
    } catch (err) {
      setError(errorMessage(err));
    } finally {
      setSaving(false);
    }
  }

  async function finish() {
    if (!rec) return;
    try {
      await api(`/api/recurrences/${rec.id}`, { method: "DELETE" });
      invalidateFinance();
      toast("Recorrência encerrada. Lançamentos já feitos foram mantidos.");
      onDone();
    } catch (err) {
      setError(errorMessage(err));
    }
  }

  return (
    <form className="form" onSubmit={submit}>
      {!rec && (
        <div className="segmented">
          <button type="button" aria-pressed={type === "expense"} onClick={() => (setType("expense"), setCategoryId(""))}>
            Despesa
          </button>
          <button type="button" aria-pressed={type === "income"} onClick={() => (setType("income"), setCategoryId(""))}>
            Receita
          </button>
        </div>
      )}
      <Field label="Descrição">
        <input className="input" value={description} maxLength={200} onChange={(e) => setDescription(e.target.value)} placeholder="Ex.: Aluguel, Salário, Internet" />
      </Field>
      <div className="form-row">
        <Field label="Valor (R$)">
          <input className="input" inputMode="decimal" value={amount} onChange={(e) => setAmount(e.target.value)} placeholder="0,00" />
        </Field>
        {!rec && (
          <Field label="Frequência">
            <select className="select" value={frequency} onChange={(e) => setFrequency(e.target.value as Recurrence["frequency"])}>
              {Object.entries(FREQUENCY_LABEL).map(([k, v]) => (
                <option key={k} value={k}>
                  {v}
                </option>
              ))}
            </select>
          </Field>
        )}
      </div>
      <div className="form-row">
        {frequency === "monthly" && (
          <Field label="Todo dia" hint="Em meses mais curtos, usa o último dia">
            <input className="input" type="number" min={1} max={31} value={day} onChange={(e) => setDay(e.target.value)} />
          </Field>
        )}
        {!rec && (
          <Field label="Começa em">
            <input className="input" type="date" value={start} onChange={(e) => setStart(e.target.value)} />
          </Field>
        )}
      </div>
      <div className="form-row">
        <Field label="Conta">
          <AccountSelect accounts={accounts} value={accountId} onChange={setAccountId} />
        </Field>
        <Field label="Categoria">
          <CategorySelect categories={categories} kind={type} value={categoryId} onChange={setCategoryId} />
        </Field>
      </div>
      <Field label="Termina em (opcional)">
        <input className="input" type="date" value={end} onChange={(e) => setEnd(e.target.value)} />
      </Field>
      {error && <div className="alert danger">{error}</div>}
      <div className="form-actions">
        {rec && (
          <Button type="button" variant="danger" style={{ marginRight: "auto" }} onClick={() => (confirmEnd ? finish() : setConfirmEnd(true))}>
            {confirmEnd ? "Confirmar: encerrar" : "Encerrar recorrência"}
          </Button>
        )}
        <Button type="submit" variant="primary" loading={saving}>
          Salvar
        </Button>
      </div>
    </form>
  );
}

export default function Recurrences() {
  const toast = useToast();
  const { data, isLoading, error, refetch } = useRecurrences();
  const occurrences = useOccurrences(31).data ?? [];
  const [editing, setEditing] = useState<Recurrence | "new" | null>(null);
  const [busy, setBusy] = useState<string | null>(null);

  const monthlyExpense = (data ?? []).filter((r) => r.type === "expense" && r.frequency === "monthly").reduce((s, r) => s + r.amount_cents, 0);
  const monthlyIncome = (data ?? []).filter((r) => r.type === "income" && r.frequency === "monthly").reduce((s, r) => s + r.amount_cents, 0);

  async function act(recId: string, date: string, action: "confirm" | "skip", label: string) {
    setBusy(recId + date + action);
    try {
      await api(`/api/recurrences/${recId}/${action}`, { body: { occurrence_date: date } });
      invalidateFinance();
      toast(action === "confirm" ? `${label}: lançado.` : `${label}: ocorrência pulada.`);
    } catch (err) {
      toast(errorMessage(err), { kind: "error" });
    } finally {
      setBusy(null);
    }
  }

  return (
    <>
      <div className="page-head">
        <div>
          <h1>Fixas e recorrentes</h1>
          <p>
            Por mês: saem {brl(monthlyExpense)} · entram {brl(monthlyIncome)}
          </p>
        </div>
        <Button variant="primary" onClick={() => setEditing("new")}>
          <Plus size={16} /> Nova recorrência
        </Button>
      </div>

      <div className="grid cols-2">
        <section className="panel">
          <h2 style={{ marginBottom: 8 }}>
            <CalendarClock size={17} style={{ verticalAlign: -3 }} /> Próximos 31 dias
          </h2>
          <p className="small muted" style={{ marginBottom: 8 }}>
            Previsões: só viram lançamento quando você confirma. Assim nada é contado em dobro.
          </p>
          {occurrences.length === 0 ? (
            <p className="small muted">Nenhuma ocorrência prevista.</p>
          ) : (
            <ul className="list">
              {occurrences.map((o) => (
                <li key={o.recurrence_id + o.date} className="row">
                  <div className="main-col">
                    <div className="title">{o.description}</div>
                    <div className="sub" style={o.overdue ? { color: "var(--danger)" } : undefined}>
                      {o.overdue ? "Atrasada · " : ""}
                      {shortDate(o.date)}
                    </div>
                  </div>
                  <Amount cents={o.amount_cents} type={o.type} />
                  <Button size="small" variant="ghost" loading={busy === o.recurrence_id + o.date + "skip"} onClick={() => act(o.recurrence_id, o.date, "skip", o.description)}>
                    Pular
                  </Button>
                  <Button size="small" loading={busy === o.recurrence_id + o.date + "confirm"} onClick={() => act(o.recurrence_id, o.date, "confirm", o.description)}>
                    {o.type === "income" ? "Recebi" : "Paguei"}
                  </Button>
                </li>
              ))}
            </ul>
          )}
        </section>

        <section className="panel">
          <h2 style={{ marginBottom: 8 }}>
            <Repeat size={17} style={{ verticalAlign: -3 }} /> Cadastradas
          </h2>
          {isLoading && <Skeleton lines={4} />}
          {error && !data && <ErrorState message={errorMessage(error)} onRetry={() => refetch()} />}
          {data && data.length === 0 && (
            <EmptyState icon={Repeat} title="Nada cadastrado" text="Cadastre aluguel, internet, salário, assinaturas… O JULIUS lembra os vencimentos e projeta seu saldo." />
          )}
          {data && data.length > 0 && (
            <ul className="list">
              {data.map((r) => (
                <li key={r.id} className="row clickable" role="button" tabIndex={0} onClick={() => setEditing(r)} onKeyDown={(e) => e.key === "Enter" && setEditing(r)}>
                  <div className="main-col">
                    <div className="title">{r.description}</div>
                    <div className="sub">
                      {FREQUENCY_LABEL[r.frequency]}
                      {r.frequency === "monthly" && r.day_of_month ? `, todo dia ${r.day_of_month}` : ""}
                      {r.next_date ? ` · próxima ${fullDate(r.next_date)}` : " · encerrada"}
                    </div>
                  </div>
                  <Amount cents={r.amount_cents} type={r.type} />
                </li>
              ))}
            </ul>
          )}
        </section>
      </div>

      {editing && (
        <Sheet title={editing === "new" ? "Nova recorrência" : "Editar recorrência"} onClose={() => setEditing(null)}>
          <RecurrenceForm rec={editing === "new" ? undefined : editing} onDone={() => setEditing(null)} />
        </Sheet>
      )}
    </>
  );
}
