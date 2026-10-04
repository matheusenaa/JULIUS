import { AlertTriangle, CalendarClock, CheckCircle2, Info, ListOrdered, Sparkles } from "lucide-react";
import { useState } from "react";
import { Link } from "react-router";

import { NewEntrySheet, QuickTab } from "../components/NewEntry";
import { useToast } from "../components/Toast";
import type { FormInitial } from "../components/TransactionForm";
import { TransactionList } from "../components/TransactionList";
import { Amount, Button, EmptyState, ErrorState, Progress, Skeleton } from "../components/ui";
import { api, errorMessage } from "../lib/api";
import { brl, monthLabel, shortDate } from "../lib/format";
import { invalidateFinance, useDashboard, useMe } from "../lib/queries";
import type { Dashboard as D, UpcomingItem } from "../lib/types";

function Upcoming({ items }: { items: UpcomingItem[] }) {
  const toast = useToast();
  const [busy, setBusy] = useState<string | null>(null);

  async function settle(item: UpcomingItem) {
    const key = item.kind + item.id + item.date;
    setBusy(key);
    try {
      if (item.kind === "recurrence") {
        await api(`/api/recurrences/${item.id}/confirm`, { body: { occurrence_date: item.date } });
      } else if (item.kind === "pending") {
        const tx = await api<{ version: number }>(`/api/transactions/${item.id}`);
        await api(`/api/transactions/${item.id}`, { method: "PATCH", body: { version: tx.version, status: "paid" } });
      }
      invalidateFinance();
      toast(`${item.description} marcado como ${item.type === "income" ? "recebido" : "pago"}.`);
    } catch (err) {
      toast(errorMessage(err), { kind: "error" });
    } finally {
      setBusy(null);
    }
  }

  if (!items.length)
    return <p className="muted small">Nada vencendo nos próximos 15 dias. Cadastre suas contas fixas em “Fixas e recorrentes”.</p>;
  return (
    <ul className="list">
      {items.slice(0, 7).map((i) => (
        <li key={i.kind + i.id + i.date} className="row">
          <div className="main-col">
            <div className="title">{i.description}</div>
            <div className="sub">
              {i.overdue ? <span style={{ color: "var(--danger)" }}>Venceu {shortDate(i.date)}</span> : `Vence ${shortDate(i.date)}`}
              {i.kind === "invoice" && " · fatura"}
            </div>
          </div>
          <Amount cents={i.amount_cents} type={i.type} />
          {i.kind === "invoice" ? (
            <Link className="btn small" to="/contas">
              Ver
            </Link>
          ) : (
            <Button size="small" loading={busy === i.kind + i.id + i.date} onClick={() => settle(i)} aria-label={`Marcar ${i.description} como pago`}>
              <CheckCircle2 size={15} /> {i.type === "income" ? "Recebi" : "Paguei"}
            </Button>
          )}
        </li>
      ))}
    </ul>
  );
}

function CategoryBars({ data }: { data: D["categories"] }) {
  if (!data.length) return <p className="muted small">Sem despesas neste mês ainda.</p>;
  const max = data[0].total_cents;
  return (
    <ul className="list" style={{ display: "grid", gap: 14 }}>
      {data.slice(0, 6).map((c) => (
        <li key={c.category_id ?? "none"}>
          <div style={{ display: "flex", justifyContent: "space-between", fontSize: "0.9rem", marginBottom: 4 }}>
            <span>{c.name}</span>
            <span className="num">
              {brl(c.total_cents)} <span className="muted small">· {Math.round(c.share * 100)}%</span>
            </span>
          </div>
          <div className="progress" aria-hidden="true">
            <i style={{ width: `${(c.total_cents / max) * 100}%` }} />
          </div>
        </li>
      ))}
    </ul>
  );
}

export default function Dashboard() {
  const me = useMe().data;
  const { data, isLoading, error, refetch } = useDashboard();
  const [correction, setCorrection] = useState<FormInitial | null>(null);

  const firstName = me?.name.split(" ")[0] ?? "";
  return (
    <>
      <div className="page-head">
        <div>
          <h1>Olá{firstName ? `, ${firstName}` : ""}</h1>
          <p>{data ? monthLabel(data.today) : " "}</p>
        </div>
      </div>

      <section className="panel" aria-label="Lançamento rápido" style={{ marginBottom: 16 }}>
        <QuickTab autoFocus={false} onDone={() => undefined} onCorrect={setCorrection} />
      </section>

      {isLoading && (
        <div className="panel">
          <Skeleton lines={4} />
        </div>
      )}
      {error && !data && <ErrorState message={errorMessage(error)} onRetry={() => refetch()} />}

      {data && (
        <>
          <section className="hero" aria-label="Resumo">
            <div>
              <div className="label">Saldo disponível hoje</div>
              <div className="big num">{brl(data.balance_cents)}</div>
            </div>
            <div className="hero-stats">
              <div>
                <div className="label">Entrou no mês</div>
                <div className="value num">{brl(data.month.income_cents)}</div>
              </div>
              <div>
                <div className="label">Saiu no mês</div>
                <div className="value num">{brl(data.month.expense_cents)}</div>
              </div>
              <div title="Estimativa: saldo atual + previstos e recorrentes − faturas que vencem até o fim do mês">
                <div className="label">Previsto p/ fim do mês*</div>
                <div className="value num">{brl(data.projection.projected_cents)}</div>
              </div>
            </div>
          </section>

          {data.insights.length > 0 && (
            <div style={{ marginBottom: 16 }}>
              {data.insights.map((i) => (
                <div key={i.text} className={`alert ${i.level === "danger" ? "danger" : i.level === "warning" ? "warning" : ""}`}>
                  {i.level === "info" ? <Info size={18} /> : <AlertTriangle size={18} />}
                  <span>{i.text}</span>
                </div>
              ))}
            </div>
          )}

          {data.recent.length === 0 ? (
            <section className="panel">
              <EmptyState
                icon={Sparkles}
                title="Vamos começar"
                text="Registre seu primeiro gasto acima, do jeito que você falaria: “gastei 45 no mercado”. Depois cadastre suas contas, cartões e despesas fixas."
                action={
                  <div className="chips" style={{ justifyContent: "center" }}>
                    <Link className="btn small" to="/contas">
                      Cadastrar contas
                    </Link>
                    <Link className="btn small" to="/recorrentes">
                      Despesas fixas
                    </Link>
                  </div>
                }
              />
            </section>
          ) : (
            <>
              <div className="grid cols-2">
                <section className="panel">
                  <div className="panel-head">
                    <h2>
                      <CalendarClock size={17} style={{ verticalAlign: -3 }} /> Próximos vencimentos
                    </h2>
                    <Link to="/recorrentes">Ver todos</Link>
                  </div>
                  <Upcoming items={data.upcoming} />
                </section>
                <section className="panel">
                  <div className="panel-head">
                    <h2>Para onde foi o dinheiro</h2>
                    <Link to="/relatorios">Relatório</Link>
                  </div>
                  <CategoryBars data={data.categories} />
                  <div className="stat-row" style={{ marginTop: 20 }}>
                    <div className="stat">
                      <div className="label">Despesas fixas</div>
                      <div className="value num">{brl(data.month.fixed_cents)}</div>
                    </div>
                    <div className="stat">
                      <div className="label">Despesas variáveis</div>
                      <div className="value num">{brl(data.month.variable_cents)}</div>
                    </div>
                  </div>
                </section>
              </div>

              <div className="grid cols-3-1" style={{ marginTop: 16 }}>
                <section className="panel">
                  <div className="panel-head">
                    <h2>Últimas movimentações</h2>
                    <Link to="/lancamentos">
                      <ListOrdered size={14} style={{ verticalAlign: -2 }} /> Histórico
                    </Link>
                  </div>
                  <TransactionList items={data.recent} />
                </section>
                <div>
                  {data.goals.length > 0 && (
                    <section className="panel">
                      <div className="panel-head">
                        <h2>Meta</h2>
                        <Link to="/planejamento">Metas</Link>
                      </div>
                      {data.goals.slice(0, 2).map((g) => (
                        <div key={g.id} style={{ display: "grid", gap: 6, marginBottom: 14 }}>
                          <strong>{g.name}</strong>
                          <Progress ratio={g.progress_cents / g.target_cents} label={`Progresso da meta ${g.name}`} />
                          <span className="small muted num">
                            {brl(g.progress_cents)} de {brl(g.target_cents)}
                          </span>
                        </div>
                      ))}
                    </section>
                  )}
                  {data.cards.length > 0 && (
                    <section className="panel">
                      <div className="panel-head">
                        <h2>Cartões</h2>
                        <Link to="/contas">Faturas</Link>
                      </div>
                      {data.cards.map((c) => (
                        <div key={c.id} className="row">
                          <div className="main-col">
                            <div className="title">{c.name}</div>
                            <div className="sub">{c.next_due ? `Próximo vencimento ${shortDate(c.next_due)}` : "Sem fatura em aberto"}</div>
                          </div>
                          <span className="num">{brl(c.open_cents)}</span>
                        </div>
                      ))}
                    </section>
                  )}
                  {data.budgets.length > 0 && (
                    <section className="panel">
                      <div className="panel-head">
                        <h2>Orçamentos</h2>
                        <Link to="/planejamento">Ajustar</Link>
                      </div>
                      {data.budgets.slice(0, 4).map((b) => (
                        <div key={b.id} style={{ display: "grid", gap: 6, marginBottom: 12 }}>
                          <div style={{ display: "flex", justifyContent: "space-between", fontSize: "0.9rem" }}>
                            <span>{b.name}</span>
                            <span className="num muted">
                              {brl(b.spent_cents)} / {brl(b.amount_cents)}
                            </span>
                          </div>
                          <Progress ratio={b.ratio} label={`Orçamento ${b.name}`} />
                        </div>
                      ))}
                    </section>
                  )}
                </div>
              </div>
              <p className="small muted" style={{ marginTop: 16 }}>
                * Estimativa calculada pelo sistema com base nos lançamentos previstos, recorrências e faturas. Não é garantia.
              </p>
            </>
          )}
        </>
      )}

      {correction && <NewEntrySheet initialForm={correction} onClose={() => setCorrection(null)} />}
    </>
  );
}
