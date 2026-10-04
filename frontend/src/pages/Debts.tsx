import { HandCoins, Plus } from "lucide-react";
import { useState, type FormEvent } from "react";
import { useSearchParams } from "react-router";

import { useToast } from "../components/Toast";
import { AccountSelect, CategorySelect } from "../components/TransactionForm";
import { Button, EmptyState, ErrorState, Field, Progress, Sheet, Skeleton } from "../components/ui";
import { api, errorMessage } from "../lib/api";
import { brl, centsToInput, DEBT_KIND_LABEL, fullDate, parseMoney, todayIso } from "../lib/format";
import { invalidateFinance, useAccounts, useCategories, useDebts } from "../lib/queries";
import type { DebtItem } from "../lib/types";

const SITUATION: Record<string, { label: string; tone: string }> = {
  em_dia: { label: "Em dia", tone: "green" },
  atrasada: { label: "Atrasada", tone: "danger" },
  quitada: { label: "Quitada", tone: "" },
  cancelada: { label: "Cancelada", tone: "" },
};

function DebtForm({ debt, onDone }: { debt?: DebtItem; onDone: () => void }) {
  const toast = useToast();
  const accounts = useAccounts().data ?? [];
  const categories = useCategories().data ?? [];
  const [name, setName] = useState(debt?.name ?? "");
  const [creditor, setCreditor] = useState(debt?.creditor ?? "");
  const [kind, setKind] = useState(debt?.kind ?? "loan");
  const [original, setOriginal] = useState(centsToInput(debt?.original_cents));
  const [total, setTotal] = useState(String(debt?.installments_total ?? ""));
  const [installment, setInstallment] = useState(centsToInput(debt?.installment_cents));
  const [paidBefore, setPaidBefore] = useState(String(debt?.installments_paid_before ?? 0));
  const [firstDue, setFirstDue] = useState(debt?.first_due_date ?? todayIso());
  const [interest, setInterest] = useState(debt?.interest_monthly_bp != null ? String(debt.interest_monthly_bp / 100).replace(".", ",") : "");
  const [accountId, setAccountId] = useState(debt?.account_id ?? accounts.find((a) => a.kind !== "credit_card")?.id ?? "");
  const [categoryId, setCategoryId] = useState(debt?.category_id ?? "");
  const [error, setError] = useState<string | null>(null);
  const [saving, setSaving] = useState(false);

  async function submit(e: FormEvent) {
    e.preventDefault();
    const inst = parseMoney(installment);
    const orig = parseMoney(original) ?? (inst && Number(total) ? inst * Number(total) : null);
    if (!name.trim()) return setError("Dê um nome à dívida. Ex.: Notebook, Financiamento do carro");
    if (!Number.isInteger(Number(total)) || Number(total) < 1) return setError("Informe o número de parcelas.");
    if (!inst) return setError("Informe o valor da parcela.");
    if (Number(paidBefore) > Number(total)) return setError("Parcelas já pagas não podem passar do total.");
    const interestBp = interest ? Math.round(Number(interest.replace(",", ".")) * 100) : null;
    if (interest && !Number.isFinite(interestBp)) return setError("Juros inválidos. Ex.: 1,99");
    const body = {
      name: name.trim(), creditor: creditor.trim() || null, kind, original_cents: orig, installments_total: Number(total),
      installment_cents: inst, installments_paid_before: Number(paidBefore) || 0, first_due_date: firstDue,
      interest_monthly_bp: interestBp, account_id: accountId || null, category_id: categoryId || null,
    };
    setSaving(true);
    setError(null);
    try {
      if (debt) {
        const changes: Partial<typeof body> = { ...body };
        delete changes.original_cents; // valor original não muda depois do cadastro
        await api(`/api/debts/${debt.id}`, { method: "PATCH", body: changes });
      } else await api("/api/debts", { body });
      invalidateFinance();
      toast(debt ? "Dívida atualizada." : "Dívida cadastrada. As próximas parcelas já aparecem em Futuros.");
      onDone();
    } catch (err) {
      setError(errorMessage(err));
    } finally {
      setSaving(false);
    }
  }

  async function remove() {
    if (!debt) return;
    try {
      await api(`/api/debts/${debt.id}`, { method: "DELETE" });
      invalidateFinance();
      onDone();
    } catch (err) {
      setError(errorMessage(err));
    }
  }

  return (
    <form className="form" onSubmit={submit}>
      <div className="form-row">
        <Field label="Nome"><input className="input" value={name} maxLength={80} onChange={(e) => setName(e.target.value)} autoFocus /></Field>
        <Field label="Credor (opcional)"><input className="input" value={creditor} maxLength={80} onChange={(e) => setCreditor(e.target.value)} placeholder="Banco, loja, pessoa" /></Field>
      </div>
      <div className="form-row">
        <Field label="Tipo">
          <select className="select" value={kind} onChange={(e) => setKind(e.target.value)}>
            {Object.entries(DEBT_KIND_LABEL).map(([k, v]) => <option key={k} value={k}>{v}</option>)}
          </select>
        </Field>
        <Field label="Valor original (R$)" hint="Opcional: se vazio, usa parcelas × valor">
          <input className="input" inputMode="decimal" value={original} onChange={(e) => setOriginal(e.target.value)} disabled={!!debt} />
        </Field>
      </div>
      <div className="form-row">
        <Field label="Número de parcelas"><input className="input" type="number" min={1} max={600} value={total} onChange={(e) => setTotal(e.target.value)} /></Field>
        <Field label="Valor da parcela (R$)"><input className="input" inputMode="decimal" value={installment} onChange={(e) => setInstallment(e.target.value)} /></Field>
      </div>
      <div className="form-row">
        <Field label="Parcelas já pagas antes" hint="Pagas antes de usar o JULIUS">
          <input className="input" type="number" min={0} value={paidBefore} onChange={(e) => setPaidBefore(e.target.value)} />
        </Field>
        <Field label="Vencimento da 1ª parcela"><input className="input" type="date" value={firstDue} onChange={(e) => setFirstDue(e.target.value)} /></Field>
      </div>
      <div className="form-row">
        <Field label="Pagar com"><AccountSelect accounts={accounts} value={accountId} onChange={setAccountId} /></Field>
        <Field label="Juros ao mês (%)" hint="Opcional, informativo"><input className="input" inputMode="decimal" value={interest} onChange={(e) => setInterest(e.target.value)} /></Field>
      </div>
      <Field label="Categoria"><CategorySelect categories={categories} kind="expense" value={categoryId} onChange={setCategoryId} /></Field>
      {error && <div className="alert danger" role="alert">{error}</div>}
      <div className="form-actions">
        {debt && <Button type="button" variant="danger" style={{ marginRight: "auto" }} onClick={remove}>Remover</Button>}
        <Button type="submit" variant="primary" loading={saving}>Salvar</Button>
      </div>
    </form>
  );
}

export default function Debts() {
  const toast = useToast();
  const [params, setParams] = useSearchParams();
  const { data, isLoading, error, refetch } = useDebts();
  const [editing, setEditing] = useState<DebtItem | "new" | null>(params.get("nova") ? "new" : null);
  const [paying, setPaying] = useState<string | null>(null);
  const active = (data ?? []).filter((d) => d.situation !== "quitada" && d.situation !== "cancelada");
  const done = (data ?? []).filter((d) => d.situation === "quitada");
  const totalRemaining = active.reduce((s, d) => s + d.remaining_cents, 0);

  async function pay(d: DebtItem) {
    setPaying(d.id);
    try {
      await api(`/api/debts/${d.id}/pay`, { body: {} });
      invalidateFinance();
      toast(`Parcela ${d.paid_installments + 1}/${d.installments_total} de ${d.name} paga.`);
    } catch (err) {
      toast(errorMessage(err), { kind: "error" });
    } finally {
      setPaying(null);
    }
  }

  return (
    <>
      <div className="page-head">
        <div>
          <h1>Dívidas</h1>
          <p>Total que falta pagar: <strong className="num">{brl(totalRemaining)}</strong> (calculado pelo JULIUS)</p>
        </div>
        <Button variant="primary" onClick={() => setEditing("new")}><Plus size={16} /> Nova dívida</Button>
      </div>
      {isLoading && <Skeleton lines={5} />}
      {error && !data && <ErrorState message={errorMessage(error)} onRetry={() => refetch()} />}
      {data && data.length === 0 && (
        <div className="panel">
          <EmptyState icon={HandCoins} title="Nenhuma dívida cadastrada" text="Empréstimos, financiamentos, compras no carnê ou dinheiro devido a alguém. O JULIUS calcula quanto falta e quando vence." />
        </div>
      )}
      <div className="grid cols-2">
        {active.map((d) => {
          const sit = SITUATION[d.situation];
          return (
            <section key={d.id} className="panel" style={{ marginTop: 0 }}>
              <div className="panel-head">
                <div>
                  <h2>{d.name}</h2>
                  <span className="small muted">{DEBT_KIND_LABEL[d.kind]}{d.creditor ? ` · ${d.creditor}` : ""}</span>
                </div>
                <span className={`badge ${sit.tone}`}>{sit.label}</span>
              </div>
              <Progress ratio={d.paid_installments / d.installments_total} label={`Parcelas pagas de ${d.name}`} />
              <div className="stat-row" style={{ marginTop: 14 }}>
                <div className="stat"><div className="label">Falta pagar</div><div className="value num">{brl(d.remaining_cents)}</div></div>
                <div className="stat"><div className="label">Parcelas</div><div className="value num">{d.remaining_installments} de {d.installments_total}</div></div>
              </div>
              <p className="small muted" style={{ margin: "10px 0" }}>
                {d.remaining_installments} × {brl(d.installment_cents)}
                {d.next_due && ` · próxima em ${fullDate(d.next_due)}`} · termina em {fullDate(d.end_date)}
                {d.interest_monthly_bp != null && ` · juros ${(d.interest_monthly_bp / 100).toLocaleString("pt-BR")}% a.m.`}
                {d.overdue_installments > 0 && <span className="badge danger" style={{ marginLeft: 6 }}>{d.overdue_installments} atrasada(s)</span>}
              </p>
              <div className="form-actions" style={{ justifyContent: "flex-start" }}>
                <Button size="small" variant="primary" loading={paying === d.id} onClick={() => pay(d)}>Paguei a parcela {d.paid_installments + 1}</Button>
                <Button size="small" variant="ghost" onClick={() => setEditing(d)}>Editar</Button>
              </div>
            </section>
          );
        })}
      </div>
      {done.length > 0 && (
        <section className="panel" style={{ marginTop: 16 }}>
          <h2 style={{ marginBottom: 8 }}>Quitadas</h2>
          <ul className="list">
            {done.map((d) => (
              <li key={d.id} className="row"><div className="main-col"><div className="title">{d.name}</div><div className="sub">{d.installments_total} parcelas · {brl(d.total_cents)}</div></div><span className="badge">Quitada</span></li>
            ))}
          </ul>
        </section>
      )}
      {editing && (
        <Sheet title={editing === "new" ? "Nova dívida" : `Editar ${editing.name}`} onClose={() => { setEditing(null); if (params.get("nova")) setParams({}, { replace: true }); }}>
          <DebtForm debt={editing === "new" ? undefined : editing} onDone={() => { setEditing(null); setParams({}, { replace: true }); }} />
        </Sheet>
      )}
    </>
  );
}
