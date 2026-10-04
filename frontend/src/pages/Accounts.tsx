import { CreditCard, Landmark, Plus, Wallet } from "lucide-react";
import { useState, type FormEvent } from "react";
import { useQuery } from "@tanstack/react-query";

import { useToast } from "../components/Toast";
import { TransactionForm } from "../components/TransactionForm";
import { Button, EmptyState, ErrorState, Field, Progress, Sheet, Skeleton } from "../components/ui";
import { api, errorMessage } from "../lib/api";
import { ACCOUNT_KIND_LABEL, brl, centsToInput, fullDate, monthLabel, todayIso } from "../lib/format";
import { invalidateFinance, useAccounts } from "../lib/queries";
import type { Account, AccountKind, Invoice } from "../lib/types";

function parseSigned(s: string): number | null {
  const neg = s.trim().startsWith("-");
  const clean = s.replace(/[R$\s-]/g, "");
  if (!clean) return 0;
  const normalized = clean.includes(",") ? clean.replace(/\./g, "").replace(",", ".") : clean;
  if (!/^\d+(\.\d{1,2})?$/.test(normalized)) return null;
  const cents = Math.round(Number(normalized) * 100);
  return neg ? -cents : cents;
}

function AccountForm({ account, onDone }: { account?: Account; onDone: () => void }) {
  const toast = useToast();
  const [name, setName] = useState(account?.name ?? "");
  const [kind, setKind] = useState<AccountKind>(account?.kind ?? "checking");
  const startCents = account?.initial_balance_cents ?? 0;
  const [initial, setInitial] = useState((startCents < 0 ? "-" : "") + centsToInput(Math.abs(startCents)));
  const [limit, setLimit] = useState(centsToInput(account?.credit_limit_cents));
  const [closing, setClosing] = useState(String(account?.closing_day ?? ""));
  const [due, setDue] = useState(String(account?.due_day ?? ""));
  const [includeInTotal, setIncludeInTotal] = useState(account?.include_in_total ?? true);
  const [error, setError] = useState<string | null>(null);
  const [saving, setSaving] = useState(false);
  const [confirmArchive, setConfirmArchive] = useState(false);
  const isCard = kind === "credit_card";

  async function submit(e: FormEvent) {
    e.preventDefault();
    const initialCents = parseSigned(initial);
    if (!name.trim()) return setError("Dê um nome à conta.");
    if (initialCents === null) return setError("Saldo inicial inválido. Ex.: 1.500,00");
    if (isCard && (!Number(closing) || !Number(due))) return setError("Informe o dia de fechamento e o de vencimento do cartão.");
    const limitCents = limit ? parseSigned(limit) : null;
    const body = {
      name: name.trim(),
      initial_balance_cents: isCard ? 0 : initialCents,
      include_in_total: includeInTotal,
      ...(isCard ? { credit_limit_cents: limitCents, closing_day: Number(closing), due_day: Number(due) } : {}),
    };
    setSaving(true);
    setError(null);
    try {
      if (account) await api(`/api/accounts/${account.id}`, { method: "PATCH", body });
      else await api("/api/accounts", { body: { ...body, kind } });
      invalidateFinance();
      toast(account ? "Conta atualizada." : "Conta criada.");
      onDone();
    } catch (err) {
      setError(errorMessage(err));
    } finally {
      setSaving(false);
    }
  }

  async function archive() {
    if (!account) return;
    try {
      await api(`/api/accounts/${account.id}`, { method: "DELETE" });
      invalidateFinance();
      toast("Conta arquivada. O histórico foi preservado.");
      onDone();
    } catch (err) {
      setError(errorMessage(err));
    }
  }

  return (
    <form className="form" onSubmit={submit}>
      <Field label="Nome">
        <input className="input" value={name} maxLength={60} onChange={(e) => setName(e.target.value)} placeholder="Ex.: Nubank, Carteira" />
      </Field>
      {!account && (
        <Field label="Tipo">
          <select className="select" value={kind} onChange={(e) => setKind(e.target.value as AccountKind)}>
            {Object.entries(ACCOUNT_KIND_LABEL).map(([k, v]) => (
              <option key={k} value={k}>
                {v}
              </option>
            ))}
          </select>
        </Field>
      )}
      {isCard ? (
        <>
          <Field label="Limite (R$)" hint="Opcional">
            <input className="input" inputMode="decimal" value={limit} onChange={(e) => setLimit(e.target.value)} />
          </Field>
          <div className="form-row">
            <Field label="Dia do fechamento" hint="Compras a partir deste dia vão para a próxima fatura">
              <input className="input" type="number" min={1} max={31} value={closing} onChange={(e) => setClosing(e.target.value)} />
            </Field>
            <Field label="Dia do vencimento">
              <input className="input" type="number" min={1} max={31} value={due} onChange={(e) => setDue(e.target.value)} />
            </Field>
          </div>
        </>
      ) : (
        <Field label="Saldo inicial (R$)" hint="Quanto havia na conta quando você começou a usar o JULIUS. Use “-” se negativo.">
          <input className="input" inputMode="decimal" value={initial} onChange={(e) => setInitial(e.target.value)} placeholder="0,00" />
        </Field>
      )}
      {!isCard && (
        <label className="check">
          <input type="checkbox" checked={includeInTotal} onChange={(e) => setIncludeInTotal(e.target.checked)} />
          Somar no saldo disponível
        </label>
      )}
      {error && <div className="alert danger">{error}</div>}
      <div className="form-actions">
        {account && !confirmArchive && (
          <Button type="button" variant="danger" style={{ marginRight: "auto" }} onClick={() => setConfirmArchive(true)}>
            Arquivar
          </Button>
        )}
        {account && confirmArchive && (
          <Button type="button" variant="danger" style={{ marginRight: "auto" }} onClick={archive}>
            Confirmar: arquivar conta
          </Button>
        )}
        <Button type="submit" variant="primary" loading={saving}>
          Salvar
        </Button>
      </div>
    </form>
  );
}

function Invoices({ card, onPay }: { card: Account; onPay: (inv: Invoice) => void }) {
  const { data, isLoading, error } = useQuery({
    queryKey: ["accounts", card.id, "invoices"],
    queryFn: () => api<Invoice[]>(`/api/accounts/${card.id}/invoices`),
  });
  if (isLoading) return <Skeleton lines={2} />;
  if (error) return <p className="small" style={{ color: "var(--danger)" }}>{errorMessage(error)}</p>;
  const open = (data ?? []).filter((i) => i.remaining_cents > 0 || i.due_date >= todayIso()).slice(0, 6);
  if (!open.length) return <p className="small muted">Nenhuma fatura em aberto.</p>;
  return (
    <ul className="list">
      {open.map((inv) => (
        <li key={inv.invoice_month} className="row">
          <div className="main-col">
            <div className="title">Fatura de {monthLabel(inv.invoice_month).toLowerCase()}</div>
            <div className="sub">
              Vence {fullDate(inv.due_date)} · total {brl(inv.total_cents)}
            </div>
          </div>
          {inv.remaining_cents > 0 ? (
            <>
              <span className="num">{brl(inv.remaining_cents)}</span>
              <Button size="small" onClick={() => onPay(inv)}>
                Pagar
              </Button>
            </>
          ) : (
            <span className="badge green">Paga</span>
          )}
        </li>
      ))}
    </ul>
  );
}

export default function Accounts() {
  const { data, isLoading, error, refetch } = useAccounts();
  const [editing, setEditing] = useState<Account | "new" | null>(null);
  const [paying, setPaying] = useState<{ card: Account; inv: Invoice } | null>(null);
  const accounts = (data ?? []).filter((a) => a.kind !== "credit_card");
  const cards = (data ?? []).filter((a) => a.kind === "credit_card");
  const total = accounts.filter((a) => a.include_in_total).reduce((s, a) => s + a.balance_cents, 0);

  return (
    <>
      <div className="page-head">
        <div>
          <h1>Contas e cartões</h1>
          <p>Disponível somando as contas: {brl(total)}</p>
        </div>
        <Button variant="primary" onClick={() => setEditing("new")}>
          <Plus size={16} /> Nova conta ou cartão
        </Button>
      </div>
      {isLoading && <Skeleton lines={4} />}
      {error && !data && <ErrorState message={errorMessage(error)} onRetry={() => refetch()} />}

      {data && (
        <div className="grid cols-2">
          <section className="panel">
            <h2 style={{ marginBottom: 8 }}>
              <Landmark size={17} style={{ verticalAlign: -3 }} /> Contas
            </h2>
            {accounts.length === 0 ? (
              <EmptyState icon={Wallet} title="Nenhuma conta" />
            ) : (
              <ul className="list">
                {accounts.map((a) => (
                  <li key={a.id} className="row clickable" tabIndex={0} role="button" onClick={() => setEditing(a)} onKeyDown={(e) => e.key === "Enter" && setEditing(a)}>
                    <span className="cat-dot">
                      <Wallet size={18} />
                    </span>
                    <div className="main-col">
                      <div className="title">{a.name}</div>
                      <div className="sub">
                        {ACCOUNT_KIND_LABEL[a.kind]}
                        {!a.include_in_total && " · fora do total"}
                      </div>
                    </div>
                    <span className="num" style={a.balance_cents < 0 ? { color: "var(--danger)" } : undefined}>
                      {brl(a.balance_cents)}
                    </span>
                  </li>
                ))}
              </ul>
            )}
          </section>

          <section>
            {cards.length === 0 ? (
              <div className="panel">
                <EmptyState
                  icon={CreditCard}
                  title="Nenhum cartão de crédito"
                  text="Cadastre seus cartões para controlar faturas, limite e compras parceladas."
                  action={
                    <Button size="small" onClick={() => setEditing("new")}>
                      Cadastrar cartão
                    </Button>
                  }
                />
              </div>
            ) : (
              cards.map((c) => (
                <div key={c.id} className="panel">
                  <div className="panel-head">
                    <h2>
                      <CreditCard size={17} style={{ verticalAlign: -3 }} /> {c.name}
                    </h2>
                    <Button size="small" variant="ghost" onClick={() => setEditing(c)}>
                      Editar
                    </Button>
                  </div>
                  {c.credit_limit_cents ? (
                    <div style={{ display: "grid", gap: 6, marginBottom: 16 }}>
                      <Progress ratio={(c.used_cents ?? 0) / c.credit_limit_cents} label="Limite usado" />
                      <div className="small muted num" style={{ display: "flex", justifyContent: "space-between" }}>
                        <span>Usado {brl(c.used_cents)}</span>
                        <span>Disponível {brl(c.available_cents)}</span>
                      </div>
                    </div>
                  ) : (
                    <p className="small muted" style={{ marginBottom: 12 }}>
                      Usado: {brl(c.used_cents)} (limite não informado)
                    </p>
                  )}
                  <p className="small muted" style={{ marginBottom: 8 }}>
                    Fecha dia {c.closing_day} · vence dia {c.due_day}
                  </p>
                  <Invoices card={c} onPay={(inv) => setPaying({ card: c, inv })} />
                </div>
              ))
            )}
          </section>
        </div>
      )}

      {editing && (
        <Sheet title={editing === "new" ? "Nova conta ou cartão" : `Editar ${editing.name}`} onClose={() => setEditing(null)}>
          <AccountForm account={editing === "new" ? undefined : editing} onDone={() => setEditing(null)} />
        </Sheet>
      )}
      {paying && (
        <Sheet title={`Pagar fatura — ${paying.card.name}`} onClose={() => setPaying(null)}>
          <p className="small muted" style={{ marginBottom: 16 }}>
            O pagamento é registrado como transferência da conta para o cartão — não conta como despesa de novo, pois as compras já foram
            registradas.
          </p>
          <TransactionForm
            initial={{
              type: "transfer",
              amount_cents: paying.inv.remaining_cents,
              description: `Pagamento fatura ${paying.card.name}`,
              to_account_id: paying.card.id,
              account_id: accounts[0]?.id,
            }}
            onDone={() => setPaying(null)}
          />
        </Sheet>
      )}
    </>
  );
}
