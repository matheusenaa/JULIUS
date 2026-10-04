import { PiggyBank, Plus, Target } from "lucide-react";
import { useState, type FormEvent } from "react";

import { useToast } from "../components/Toast";
import { CategorySelect } from "../components/TransactionForm";
import { Button, EmptyState, ErrorState, Field, Progress, Sheet, Skeleton } from "../components/ui";
import { api, errorMessage } from "../lib/api";
import { brl, centsToInput, fullDate, parseMoney } from "../lib/format";
import { invalidateFinance, useAccounts, useBudgets, useCategories, useGoals } from "../lib/queries";
import type { BudgetStatus, GoalStatus } from "../lib/types";

function BudgetForm({ budget, onDone }: { budget?: BudgetStatus; onDone: () => void }) {
  const toast = useToast();
  const categories = useCategories().data ?? [];
  const [categoryId, setCategoryId] = useState(budget?.category_id ?? "");
  const [amount, setAmount] = useState(centsToInput(budget?.amount_cents));
  const [error, setError] = useState<string | null>(null);
  const [saving, setSaving] = useState(false);

  async function submit(e: FormEvent) {
    e.preventDefault();
    const cents = parseMoney(amount);
    if (!categoryId) return setError("Escolha a categoria.");
    if (!cents) return setError("Informe o limite mensal.");
    setSaving(true);
    try {
      await api("/api/budgets", { method: "PUT", body: { category_id: categoryId, amount_cents: cents } });
      invalidateFinance();
      toast("Orçamento salvo.");
      onDone();
    } catch (err) {
      setError(errorMessage(err));
    } finally {
      setSaving(false);
    }
  }

  async function remove() {
    if (!budget) return;
    try {
      await api(`/api/budgets/${budget.id}`, { method: "DELETE" });
      invalidateFinance();
      onDone();
    } catch (err) {
      setError(errorMessage(err));
    }
  }

  return (
    <form className="form" onSubmit={submit}>
      <Field label="Categoria">
        <CategorySelect categories={categories} kind="expense" value={categoryId} onChange={setCategoryId} />
      </Field>
      <Field label="Limite por mês (R$)">
        <input className="input" inputMode="decimal" value={amount} onChange={(e) => setAmount(e.target.value)} placeholder="0,00" />
      </Field>
      {error && <div className="alert danger">{error}</div>}
      <div className="form-actions">
        {budget && (
          <Button type="button" variant="danger" style={{ marginRight: "auto" }} onClick={remove}>
            Remover
          </Button>
        )}
        <Button type="submit" variant="primary" loading={saving}>
          Salvar
        </Button>
      </div>
    </form>
  );
}

function GoalForm({ goal, onDone }: { goal?: GoalStatus; onDone: () => void }) {
  const toast = useToast();
  const accounts = (useAccounts().data ?? []).filter((a) => a.kind !== "credit_card");
  const [name, setName] = useState(goal?.name ?? "");
  const [target, setTarget] = useState(centsToInput(goal?.target_cents));
  const [saved, setSaved] = useState(centsToInput(goal?.saved_cents));
  const [date, setDate] = useState(goal?.target_date ?? "");
  const [accountId, setAccountId] = useState(goal?.account_id ?? "");
  const [error, setError] = useState<string | null>(null);
  const [saving, setSaving] = useState(false);

  async function submit(e: FormEvent) {
    e.preventDefault();
    const targetCents = parseMoney(target);
    const savedCents = saved ? parseMoney(saved) : 0;
    if (!name.trim()) return setError("Dê um nome à meta.");
    if (!targetCents) return setError("Informe o valor da meta.");
    if (savedCents === null) return setError("Valor guardado inválido.");
    const body = { name: name.trim(), target_cents: targetCents, saved_cents: savedCents, target_date: date || null, account_id: accountId || null };
    setSaving(true);
    try {
      if (goal) await api(`/api/goals/${goal.id}`, { method: "PATCH", body });
      else await api("/api/goals", { body });
      invalidateFinance();
      toast("Meta salva.");
      onDone();
    } catch (err) {
      setError(errorMessage(err));
    } finally {
      setSaving(false);
    }
  }

  async function remove() {
    if (!goal) return;
    await api(`/api/goals/${goal.id}`, { method: "DELETE" }).catch((err) => setError(errorMessage(err)));
    invalidateFinance();
    onDone();
  }

  return (
    <form className="form" onSubmit={submit}>
      <Field label="Nome">
        <input className="input" value={name} maxLength={80} onChange={(e) => setName(e.target.value)} placeholder="Ex.: Reserva de emergência" />
      </Field>
      <div className="form-row">
        <Field label="Quero juntar (R$)">
          <input className="input" inputMode="decimal" value={target} onChange={(e) => setTarget(e.target.value)} />
        </Field>
        <Field label="Até (opcional)">
          <input className="input" type="date" value={date} onChange={(e) => setDate(e.target.value)} />
        </Field>
      </div>
      <Field label="Acompanhar pelo saldo da conta" hint="Opcional. Se escolher, o progresso é o saldo dessa conta.">
        <select className="select" value={accountId} onChange={(e) => setAccountId(e.target.value)}>
          <option value="">Não — informo manualmente</option>
          {accounts.map((a) => (
            <option key={a.id} value={a.id}>
              {a.name}
            </option>
          ))}
        </select>
      </Field>
      {!accountId && (
        <Field label="Já guardei (R$)">
          <input className="input" inputMode="decimal" value={saved} onChange={(e) => setSaved(e.target.value)} />
        </Field>
      )}
      {error && <div className="alert danger">{error}</div>}
      <div className="form-actions">
        {goal && (
          <Button type="button" variant="danger" style={{ marginRight: "auto" }} onClick={remove}>
            Remover
          </Button>
        )}
        <Button type="submit" variant="primary" loading={saving}>
          Salvar
        </Button>
      </div>
    </form>
  );
}

export default function Planning() {
  const budgets = useBudgets();
  const goals = useGoals();
  const [budgetSheet, setBudgetSheet] = useState<BudgetStatus | "new" | null>(null);
  const [goalSheet, setGoalSheet] = useState<GoalStatus | "new" | null>(null);

  return (
    <>
      <div className="page-head">
        <div>
          <h1>Orçamentos e metas</h1>
          <p>Limites por categoria e objetivos de economia</p>
        </div>
      </div>
      <div className="grid cols-2">
        <section className="panel">
          <div className="panel-head">
            <h2>Orçamento do mês</h2>
            <Button size="small" onClick={() => setBudgetSheet("new")}>
              <Plus size={15} /> Definir
            </Button>
          </div>
          {budgets.isLoading && <Skeleton />}
          {budgets.error && <ErrorState message={errorMessage(budgets.error)} onRetry={() => budgets.refetch()} />}
          {budgets.data?.length === 0 && <EmptyState icon={PiggyBank} title="Sem orçamentos" text="Defina um limite mensal para as categorias que mais pesam. O JULIUS avisa quando chegar a 80%." />}
          {budgets.data?.map((b) => (
            <button key={b.id} className="row clickable" style={{ width: "100%", background: "none", border: 0, textAlign: "left", display: "grid", gap: 6 }} onClick={() => setBudgetSheet(b)}>
              <div style={{ display: "flex", justifyContent: "space-between" }}>
                <strong>{b.name}</strong>
                <span className="num small">
                  {brl(b.spent_cents)} de {brl(b.amount_cents)}
                </span>
              </div>
              <Progress ratio={b.ratio} label={`Orçamento ${b.name}`} />
              <span className="small muted">
                {b.ratio >= 1 ? `Passou ${brl(b.spent_cents - b.amount_cents)} do limite` : `Restam ${brl(b.amount_cents - b.spent_cents)}`}
              </span>
            </button>
          ))}
        </section>

        <section className="panel">
          <div className="panel-head">
            <h2>Metas</h2>
            <Button size="small" onClick={() => setGoalSheet("new")}>
              <Plus size={15} /> Nova meta
            </Button>
          </div>
          {goals.isLoading && <Skeleton />}
          {goals.error && <ErrorState message={errorMessage(goals.error)} onRetry={() => goals.refetch()} />}
          {goals.data?.length === 0 && <EmptyState icon={Target} title="Nenhuma meta" text="Ex.: reserva de emergência, viagem, trocar de carro." />}
          {goals.data?.map((g) => (
            <button key={g.id} className="row clickable" style={{ width: "100%", background: "none", border: 0, textAlign: "left", display: "grid", gap: 6 }} onClick={() => setGoalSheet(g)}>
              <div style={{ display: "flex", justifyContent: "space-between" }}>
                <strong>{g.name}</strong>
                <span className="num small">{Math.round((g.progress_cents / g.target_cents) * 100)}%</span>
              </div>
              <Progress ratio={g.progress_cents / g.target_cents} label={`Meta ${g.name}`} />
              <span className="small muted">
                {brl(g.progress_cents)} de {brl(g.target_cents)}
                {g.target_date && ` · até ${fullDate(g.target_date)}`}
                {g.monthly_needed_cents ? ` · guardar ~${brl(g.monthly_needed_cents)}/mês` : ""}
              </span>
            </button>
          ))}
        </section>
      </div>

      {budgetSheet && (
        <Sheet title="Orçamento mensal" onClose={() => setBudgetSheet(null)}>
          <BudgetForm budget={budgetSheet === "new" ? undefined : budgetSheet} onDone={() => setBudgetSheet(null)} />
        </Sheet>
      )}
      {goalSheet && (
        <Sheet title={goalSheet === "new" ? "Nova meta" : "Editar meta"} onClose={() => setGoalSheet(null)}>
          <GoalForm goal={goalSheet === "new" ? undefined : goalSheet} onDone={() => setGoalSheet(null)} />
        </Sheet>
      )}
    </>
  );
}
