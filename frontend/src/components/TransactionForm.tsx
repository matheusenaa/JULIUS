import { useEffect, useState, type FormEvent } from "react";

import { api, ApiError, errorMessage } from "../lib/api";
import { centsToInput, PAYMENT_LABEL, parseMoney, todayIso, TYPE_LABEL } from "../lib/format";
import { createTransaction, deleteTransaction, updateTransaction } from "../lib/offline";
import { invalidateFinance, useAccounts, useCategories } from "../lib/queries";
import type { Account, Category, PaymentMethod, Transaction, TransactionInput, TxStatus, TxType } from "../lib/types";
import { useToast } from "./Toast";
import { Button, Field } from "./ui";

export function CategorySelect({
  categories,
  kind,
  value,
  onChange,
  id,
}: {
  categories: Category[];
  kind: "income" | "expense";
  value: string;
  onChange: (v: string) => void;
  id?: string;
}) {
  const parents = categories.filter((c) => c.kind === kind && !c.parent_id);
  return (
    <select id={id} className="select" value={value} onChange={(e) => onChange(e.target.value)}>
      <option value="">Sem categoria</option>
      {parents.map((p) => {
        const children = categories.filter((c) => c.parent_id === p.id);
        return children.length ? (
          <optgroup key={p.id} label={p.name}>
            <option value={p.id}>{p.name} (geral)</option>
            {children.map((c) => (
              <option key={c.id} value={c.id}>
                {c.name}
              </option>
            ))}
          </optgroup>
        ) : (
          <option key={p.id} value={p.id}>
            {p.name}
          </option>
        );
      })}
    </select>
  );
}

export function AccountSelect({
  accounts,
  value,
  onChange,
  exclude,
}: {
  accounts: Account[];
  value: string;
  onChange: (v: string) => void;
  exclude?: string;
}) {
  return (
    <select className="select" value={value} onChange={(e) => onChange(e.target.value)} required>
      <option value="" disabled>
        Selecione
      </option>
      {accounts
        .filter((a) => a.id !== exclude)
        .map((a) => (
          <option key={a.id} value={a.id}>
            {a.name}
          </option>
        ))}
    </select>
  );
}

export type FormInitial = Partial<TransactionInput> & { version?: number; id?: string };

interface Props {
  initial?: FormInitial;
  editing?: Transaction;
  source?: string;
  onDone: (tx?: Transaction) => void;
}

export function TransactionForm({ initial, editing, source = "manual", onDone }: Props) {
  const toast = useToast();
  const accounts = useAccounts().data ?? [];
  const categories = useCategories().data ?? [];
  const base = editing ?? initial ?? {};

  const [type, setType] = useState<TxType>(base.type ?? "expense");
  const [amount, setAmount] = useState(centsToInput(base.amount_cents));
  const [description, setDescription] = useState(base.description ?? "");
  const [date, setDate] = useState(base.occurred_on ?? todayIso());
  const [accountId, setAccountId] = useState(base.account_id ?? accounts.find((a) => a.kind !== "credit_card")?.id ?? "");
  const [toAccountId, setToAccountId] = useState(base.to_account_id ?? "");
  const [categoryId, setCategoryId] = useState(base.category_id ?? "");
  const [payment, setPayment] = useState<PaymentMethod | "">(base.payment_method ?? "");
  const [status, setStatus] = useState<TxStatus>(base.status ?? "paid");
  const [isFixed, setIsFixed] = useState(base.is_fixed ?? false);
  const [installments, setInstallments] = useState(String((initial?.installments ?? 1) || 1));
  const [notes, setNotes] = useState(base.notes ?? "");
  const [errors, setErrors] = useState<Record<string, string>>({});
  const [formError, setFormError] = useState<string | null>(null);
  const [saving, setSaving] = useState(false);
  const [confirmDelete, setConfirmDelete] = useState(false);

  useEffect(() => {
    if (!accountId && accounts.length) setAccountId((accounts.find((a) => a.kind !== "credit_card") ?? accounts[0]).id);
  }, [accounts, accountId]);

  const account = accounts.find((a) => a.id === accountId);
  const isCard = account?.kind === "credit_card";

  async function submit(e: FormEvent) {
    e.preventDefault();
    const cents = parseMoney(amount);
    const errs: Record<string, string> = {};
    if (!cents) errs.amount = "Informe um valor maior que zero. Ex.: 45,90";
    if (!description.trim()) errs.description = "Descreva o lançamento.";
    if (!accountId) errs.account = "Escolha a conta.";
    if (type === "transfer" && (!toAccountId || toAccountId === accountId)) errs.to = "Escolha uma conta de destino diferente.";
    const n = Number(installments);
    if (type === "expense" && (!Number.isInteger(n) || n < 1 || n > 120)) errs.installments = "Entre 1 e 120 parcelas.";
    setErrors(errs);
    if (Object.keys(errs).length) return;

    setSaving(true);
    setFormError(null);
    try {
      if (editing) {
        const result = await updateTransaction(editing, {
          amount_cents: cents,
          description: description.trim(),
          occurred_on: date,
          account_id: accountId,
          ...(type === "transfer" ? { to_account_id: toAccountId } : { category_id: categoryId || null }),
          payment_method: payment || null,
          status,
          is_fixed: isFixed,
          notes: notes.trim() || null,
        });
        invalidateFinance();
        toast(result.queued ? "Sem internet: alteração salva no aparelho e enviada quando a conexão voltar." : "Alterações salvas.");
        onDone(result.tx);
      } else {
        const body: TransactionInput = {
          id: initial?.id,
          type,
          amount_cents: cents!,
          description: description.trim(),
          occurred_on: date,
          account_id: accountId,
          to_account_id: type === "transfer" ? toAccountId : null,
          category_id: type === "transfer" ? null : categoryId || null,
          payment_method: payment || null,
          status,
          is_fixed: isFixed,
          installments: type === "expense" ? n : 1,
          notes: notes.trim() || null,
          source,
        };
        const result = await createTransaction(body);
        invalidateFinance();
        if (result.queued) toast("Sem internet: lançamento salvo no aparelho. Será sincronizado automaticamente.");
        else toast(n > 1 ? `Compra registrada em ${n} parcelas.` : "Lançamento registrado.");
        onDone(result.queued ? undefined : result.tx);
      }
    } catch (err) {
      if (err instanceof ApiError && err.code === "version_conflict") {
        invalidateFinance();
        setFormError("Este lançamento foi alterado em outro aparelho. Feche e abra novamente para ver a versão atual.");
      } else if (err instanceof ApiError && err.details && err.code === "validation") {
        setFormError(errorMessage(err));
      } else {
        setFormError(errorMessage(err));
      }
    } finally {
      setSaving(false);
    }
  }

  async function remove(scope: "one" | "plan") {
    if (!editing) return;
    setSaving(true);
    try {
      const result = await deleteTransaction(editing, scope);
      invalidateFinance();
      toast(result.queued ? "Sem internet: a exclusão será enviada quando a conexão voltar." : "Lançamento excluído.", {
        action:
          scope === "one" && !result.queued
            ? {
                label: "Desfazer",
                run: () =>
                  api(`/api/transactions/${editing.id}/restore`, { method: "POST" })
                    .then(invalidateFinance)
                    .catch(() => toast("Não foi possível desfazer.", { kind: "error" })),
              }
            : undefined,
      });
      onDone();
    } catch (err) {
      setFormError(errorMessage(err));
    } finally {
      setSaving(false);
    }
  }

  const kind = type === "income" ? "income" : "expense";
  return (
    <form className="form" onSubmit={submit} noValidate>
      {!editing && (
        <div className="segmented" role="group" aria-label="Tipo">
          {(["expense", "income", "transfer"] as TxType[]).map((t) => (
            <button
              key={t}
              type="button"
              aria-pressed={type === t}
              onClick={() => {
                setType(t);
                setCategoryId("");
              }}
            >
              {TYPE_LABEL[t]}
            </button>
          ))}
        </div>
      )}

      <div className="form-row">
        <Field label="Valor (R$)" error={errors.amount}>
          <input
            className="input num"
            inputMode="decimal"
            placeholder="0,00"
            value={amount}
            onChange={(e) => setAmount(e.target.value)}
            aria-invalid={!!errors.amount}
            autoFocus={!editing}
          />
        </Field>
        <Field label="Data">
          <input className="input" type="date" value={date} onChange={(e) => setDate(e.target.value)} required />
        </Field>
      </div>

      <Field label="Descrição" error={errors.description}>
        <input
          className="input"
          value={description}
          maxLength={200}
          placeholder={type === "income" ? "Ex.: Salário" : "Ex.: Mercado"}
          onChange={(e) => setDescription(e.target.value)}
          aria-invalid={!!errors.description}
        />
      </Field>

      <div className="form-row">
        <Field label={type === "transfer" ? "De" : "Conta ou cartão"} error={errors.account}>
          <AccountSelect accounts={accounts} value={accountId} onChange={setAccountId} />
        </Field>
        {type === "transfer" ? (
          <Field label="Para" error={errors.to}>
            <AccountSelect accounts={accounts} value={toAccountId} onChange={setToAccountId} exclude={accountId} />
          </Field>
        ) : (
          <Field label="Categoria">
            <CategorySelect categories={categories} kind={kind} value={categoryId} onChange={setCategoryId} />
          </Field>
        )}
      </div>

      {type !== "transfer" && (
        <div className="form-row">
          <Field label="Forma de pagamento">
            <select className="select" value={isCard ? "credit" : payment} disabled={isCard} onChange={(e) => setPayment(e.target.value as PaymentMethod)}>
              <option value="">Não informar</option>
              {Object.entries(PAYMENT_LABEL).map(([k, v]) => (
                <option key={k} value={k}>
                  {v}
                </option>
              ))}
            </select>
          </Field>
          {type === "expense" && !editing ? (
            <Field label="Parcelas" error={errors.installments} hint={Number(installments) > 1 ? "O valor informado é o TOTAL da compra." : undefined}>
              <input className="input" type="number" min={1} max={120} value={installments} onChange={(e) => setInstallments(e.target.value)} />
            </Field>
          ) : (
            <div />
          )}
        </div>
      )}

      <div className="chips" role="group" aria-label="Situação">
        <button type="button" className="chip" aria-pressed={status === "paid"} onClick={() => setStatus("paid")}>
          {type === "income" ? "Recebido" : "Pago / realizado"}
        </button>
        <button type="button" className="chip" aria-pressed={status === "pending"} onClick={() => setStatus("pending")}>
          Previsto
        </button>
        <button type="button" className="chip" aria-pressed={status === "confirmed"} onClick={() => setStatus("confirmed")}
          title="Ex.: boleto agendado, valor já certo">
          Confirmado
        </button>
        {editing && (
          <button type="button" className="chip" aria-pressed={status === "canceled"} onClick={() => setStatus("canceled")}
            title="Não vai mais acontecer; fica no histórico mas não entra em saldos">
            Cancelado
          </button>
        )}
        {type !== "transfer" && (
          <label className="check" style={{ marginLeft: 4 }}>
            <input type="checkbox" checked={isFixed} onChange={(e) => setIsFixed(e.target.checked)} />
            {type === "income" ? "Receita fixa" : "Despesa fixa"}
          </label>
        )}
      </div>

      <Field label="Observação (opcional)">
        <textarea className="textarea" value={notes} maxLength={2000} onChange={(e) => setNotes(e.target.value)} />
      </Field>

      {formError && (
        <div className="alert danger" role="alert">
          {formError}
        </div>
      )}

      <div className="form-actions">
        {editing && !confirmDelete && (
          <Button type="button" variant="danger" onClick={() => setConfirmDelete(true)} style={{ marginRight: "auto" }}>
            Excluir
          </Button>
        )}
        {editing && confirmDelete && (
          <div className="chips" style={{ marginRight: "auto" }}>
            <Button type="button" variant="danger" size="small" loading={saving} onClick={() => remove("one")}>
              Confirmar exclusão
            </Button>
            {editing.installment_plan_id && (
              <Button type="button" variant="danger" size="small" onClick={() => remove("plan")}>
                Excluir esta e as próximas parcelas
              </Button>
            )}
            <Button type="button" size="small" variant="ghost" onClick={() => setConfirmDelete(false)}>
              Cancelar
            </Button>
          </div>
        )}
        <Button type="submit" variant="primary" loading={saving}>
          {editing ? "Salvar" : "Registrar"}
        </Button>
      </div>
    </form>
  );
}
