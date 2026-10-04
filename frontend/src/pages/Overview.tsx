import { AlertTriangle, ArrowDownLeft, ArrowUpRight, CalendarDays, ChevronLeft, ChevronRight, Info, Table2 } from "lucide-react";
import { useMemo, useState } from "react";
import { Link } from "react-router";
import { Area, Bar, BarChart, CartesianGrid, ComposedChart, Line, ReferenceLine, ResponsiveContainer, Tooltip, XAxis, YAxis } from "recharts";

import { Button, ErrorState, Progress, Skeleton } from "../components/ui";
import { errorMessage } from "../lib/api";
import { brl, fullDate, monthLabel, shortDate, shortMonth, STATUS_LABEL, todayIso } from "../lib/format";
import { useOverview } from "../lib/queries";
import type { CalendarDay, Overview as O, TimelineEvent } from "../lib/types";

const axisMoney = (cents: number) => {
  const reais = cents / 100;
  if (Math.abs(reais) < 1000) return String(Math.round(reais));
  return `${(reais / 1000).toLocaleString("pt-BR", { maximumFractionDigits: 1 })}k`;
};

const KIND_LABEL: Record<string, string> = { transaction: "Lançamento", recurrence: "Recorrente", invoice: "Fatura", debt: "Dívida" };

function Kpi({ label, value, hint, tone }: { label: string; value: string; hint?: string; tone?: "in" | "out" | "warn" }) {
  const color = tone === "in" ? "var(--income)" : tone === "warn" ? "var(--danger)" : undefined;
  return (
    <div className="panel stat" style={{ marginTop: 0 }}>
      <div className="label">{label}</div>
      <div className="value num" style={color ? { color } : undefined}>
        {value}
      </div>
      {hint && <div className="small muted">{hint}</div>}
    </div>
  );
}

function BalanceChart({ ov }: { ov: O }) {
  const [asTable, setAsTable] = useState(false);
  // Uma série só (saldo); realizado em linha cheia e projeção tracejada, com legenda textual
  const data = useMemo(() => {
    const hist = ov.history.slice(-60).map((p) => ({ date: p.date, real: p.balance_cents, proj: null as number | null }));
    const last = hist[hist.length - 1];
    if (last) last.proj = last.real;
    const proj = ov.projection.slice(1).map((p) => ({ date: p.date, real: null as number | null, proj: p.balance_cents }));
    return [...hist, ...proj];
  }, [ov]);
  const hasNegative = data.some((d) => (d.real ?? 0) < 0 || (d.proj ?? 0) < 0);
  return (
    <section className="panel">
      <div className="panel-head">
        <h2>Saldo: últimos 60 dias e próximos {ov.horizon_days}</h2>
        <Button size="small" variant="ghost" onClick={() => setAsTable((v) => !v)} aria-pressed={asTable}>
          <Table2 size={15} /> {asTable ? "Gráfico" : "Tabela"}
        </Button>
      </div>
      <div className="chips small" style={{ marginBottom: 8 }}>
        <span className="check">
          <svg width="22" height="8" aria-hidden="true"><line x1="0" y1="4" x2="22" y2="4" stroke="var(--chart-line)" strokeWidth="2" /></svg> Realizado
        </span>
        <span className="check">
          <svg width="22" height="8" aria-hidden="true"><line x1="0" y1="4" x2="22" y2="4" stroke="var(--chart-line)" strokeWidth="2" strokeDasharray="4 3" /></svg> Projeção (estimativa)
        </span>
      </div>
      {asTable ? (
        <div style={{ maxHeight: 300, overflow: "auto" }}>
          <table className="table">
            <thead><tr><th>Dia</th><th className="right">Saldo</th><th>Tipo</th></tr></thead>
            <tbody>
              {data.filter((_, i) => i % 3 === 0 || i === data.length - 1).map((d) => (
                <tr key={d.date}><td>{fullDate(d.date)}</td><td className="right num">{brl(d.real ?? d.proj)}</td><td>{d.real !== null ? "Realizado" : "Projeção"}</td></tr>
              ))}
            </tbody>
          </table>
        </div>
      ) : (
        <div style={{ width: "100%", height: 240 }} role="img" aria-label="Linha do saldo realizado e projetado">
          <ResponsiveContainer>
            <ComposedChart data={data} margin={{ top: 8, right: 8, left: -10, bottom: 0 }}>
              <CartesianGrid vertical={false} stroke="var(--line)" />
              <XAxis dataKey="date" tickFormatter={shortDate} tick={{ fill: "var(--ink-3)", fontSize: 12 }} axisLine={false} tickLine={false} minTickGap={28} />
              <YAxis tickFormatter={axisMoney} tick={{ fill: "var(--ink-3)", fontSize: 12 }} axisLine={false} tickLine={false} width={48} />
              {hasNegative && <ReferenceLine y={0} stroke="var(--danger)" strokeDasharray="2 3" />}
              <ReferenceLine x={todayIso()} stroke="var(--ink-3)" strokeDasharray="2 3" label={{ value: "hoje", fill: "var(--ink-3)", fontSize: 11, position: "insideTopLeft" }} />
              <Tooltip
                formatter={(v, name) => [brl(Number(v)), name === "real" ? "Saldo" : "Saldo projetado"]}
                labelFormatter={(l) => fullDate(String(l))}
                contentStyle={{ background: "var(--surface)", border: "1px solid var(--line)", borderRadius: 12 }}
              />
              <Area isAnimationActive={false} type="monotone" dataKey="real" stroke="var(--chart-line)" strokeWidth={2} fill="var(--green-soft)" connectNulls={false} dot={false} activeDot={{ r: 5 }} />
              <Line isAnimationActive={false} type="monotone" dataKey="proj" stroke="var(--chart-line)" strokeWidth={2} strokeDasharray="5 4" dot={false} activeDot={{ r: 5 }} connectNulls={false} />
            </ComposedChart>
          </ResponsiveContainer>
        </div>
      )}
    </section>
  );
}

export function TimelineList({ events, start, limit = 12 }: { events: TimelineEvent[]; start: number; limit?: number }) {
  if (!events.length) return <p className="small muted">Nenhum compromisso no período. Cadastre contas e salário em Futuros.</p>;
  return (
    <ol className="list" aria-label="Próximos compromissos em ordem">
      <li className="row" style={{ paddingTop: 0 }}>
        <span className="cat-dot" aria-hidden="true">=</span>
        <div className="main-col"><div className="title">Saldo hoje</div></div>
        <strong className="num">{brl(start)}</strong>
      </li>
      {events.slice(0, limit).map((e) => {
        const status = STATUS_LABEL[e.status];
        return (
          <li key={`${e.kind}${e.ref_id}${e.date}${e.description}`} className="row">
            <span className="cat-dot" aria-hidden="true" style={{ color: e.flow === "in" ? "var(--income)" : "var(--ink-2)" }}>
              {e.flow === "in" ? <ArrowDownLeft size={17} /> : <ArrowUpRight size={17} />}
            </span>
            <div className="main-col">
              <div className="title">{e.description}</div>
              <div className="sub">
                {shortDate(e.date)} · {KIND_LABEL[e.kind]}
                {e.status !== "pending" && status && <span className={`badge ${status.tone}`} style={{ marginLeft: 6 }}>{e.status === "overdue" && <AlertTriangle size={10} />} {status.label}</span>}
              </div>
            </div>
            <div style={{ textAlign: "right" }}>
              <div className={`num ${e.flow === "in" ? "income" : ""}`}>{e.flow === "in" ? "+" : "−"} {brl(e.amount_cents)}</div>
              <div className="small muted num" title="Saldo projetado depois deste compromisso">= {brl(e.balance_after)}</div>
            </div>
          </li>
        );
      })}
    </ol>
  );
}

function Calendar({ days, month, onMonth }: { days: CalendarDay[]; month: string; onMonth: (m: string) => void }) {
  const [selected, setSelected] = useState<string | null>(null);
  const first = new Date(`${month}-01T12:00:00`);
  const offset = (first.getDay() + 6) % 7; // semana começa na segunda
  const today = todayIso();
  const shift = (delta: number) => {
    const d = new Date(first);
    d.setMonth(d.getMonth() + delta);
    onMonth(`${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, "0")}`);
    setSelected(null);
  };
  const sel = days.find((d) => d.date === selected);
  return (
    <section className="panel">
      <div className="panel-head">
        <h2><CalendarDays size={17} style={{ verticalAlign: -3 }} /> Calendário</h2>
        <div style={{ display: "flex", alignItems: "center", gap: 4 }}>
          <Button size="small" variant="ghost" className="icon" aria-label="Mês anterior" onClick={() => shift(-1)}><ChevronLeft size={16} /></Button>
          <span className="small" style={{ minWidth: 120, textAlign: "center" }}>{monthLabel(`${month}-01`)}</span>
          <Button size="small" variant="ghost" className="icon" aria-label="Próximo mês" onClick={() => shift(1)}><ChevronRight size={16} /></Button>
        </div>
      </div>
      <div className="calendar" role="grid" aria-label="Calendário financeiro">
        {["S", "T", "Q", "Q", "S", "S", "D"].map((d, i) => <div key={i} className="cal-head" aria-hidden="true">{d}</div>)}
        {Array.from({ length: offset }, (_, i) => <div key={`e${i}`} />)}
        {days.map((d) => {
          const future = d.events.reduce((s, e) => s + (e.flow === "in" ? e.amount_cents : -e.amount_cents), 0);
          const late = d.events.some((e) => e.status === "overdue");
          const has = d.in_cents || d.out_cents || d.events.length;
          return (
            <button
              key={d.date}
              role="gridcell"
              className={`cal-day ${d.date === today ? "today" : ""} ${selected === d.date ? "selected" : ""}`}
              onClick={() => setSelected(d.date === selected ? null : d.date)}
              aria-label={`${fullDate(d.date)}${has ? ": tem movimentações" : ""}`}
            >
              <span className="n">{Number(d.date.slice(8))}</span>
              {d.in_cents > 0 && <span className="dot in" title="Entrou">+</span>}
              {d.out_cents > 0 && <span className="dot out" title="Saiu">−</span>}
              {d.events.length > 0 && <span className={`dot plan ${late ? "late" : ""}`} title="Previsto">{future >= 0 ? "↑" : "↓"}</span>}
            </button>
          );
        })}
      </div>
      <p className="small muted" style={{ marginTop: 8 }}>+ entrou · − saiu · ↑↓ previsto. Toque em um dia para ver.</p>
      {sel && (
        <div className="proposal" style={{ marginTop: 8 }}>
          <strong>{fullDate(sel.date)}</strong>
          {sel.in_cents > 0 && <span className="small">Entrou: <span className="num income">{brl(sel.in_cents)}</span></span>}
          {sel.out_cents > 0 && <span className="small">Saiu: <span className="num">{brl(sel.out_cents)}</span></span>}
          {sel.events.map((e, i) => (
            <span key={i} className="small">
              {e.flow === "in" ? "+" : "−"} {brl(e.amount_cents)} · {e.description} {e.status === "overdue" && <span className="badge danger">atrasado</span>}
            </span>
          ))}
          {!sel.in_cents && !sel.out_cents && !sel.events.length && <span className="small muted">Nada neste dia.</span>}
        </div>
      )}
    </section>
  );
}

function MonthlyChart({ data }: { data: O["monthly"] }) {
  return (
    <section className="panel">
      <h2 style={{ marginBottom: 8 }}>Receitas × despesas (6 meses)</h2>
      <div className="chips small" style={{ marginBottom: 8 }}>
        <span className="check"><i style={{ width: 12, height: 12, borderRadius: 3, background: "var(--chart-in)" }} /> Receitas</span>
        <span className="check"><i style={{ width: 12, height: 12, borderRadius: 3, background: "var(--chart-out)" }} /> Despesas</span>
      </div>
      <div style={{ width: "100%", height: 200 }} role="img" aria-label="Barras de receitas e despesas por mês">
        <ResponsiveContainer>
          <BarChart data={data} barGap={2} margin={{ top: 4, right: 4, left: -10, bottom: 0 }}>
            <CartesianGrid vertical={false} stroke="var(--line)" />
            <XAxis dataKey="month" tickFormatter={shortMonth} tick={{ fill: "var(--ink-3)", fontSize: 12 }} axisLine={false} tickLine={false} />
            <YAxis tickFormatter={axisMoney} tick={{ fill: "var(--ink-3)", fontSize: 12 }} axisLine={false} tickLine={false} width={48} />
            <Tooltip
              formatter={(v, n) => [brl(Number(v)), n === "income" ? "Receitas" : "Despesas"]}
              labelFormatter={(l) => monthLabel(String(l))}
              cursor={{ fill: "var(--surface-2)" }}
              contentStyle={{ background: "var(--surface)", border: "1px solid var(--line)", borderRadius: 12 }}
            />
            <Bar isAnimationActive={false} dataKey="income" fill="var(--chart-in)" radius={[4, 4, 0, 0]} maxBarSize={26} />
            <Bar isAnimationActive={false} dataKey="expense" fill="var(--chart-out)" radius={[4, 4, 0, 0]} maxBarSize={26} />
          </BarChart>
        </ResponsiveContainer>
      </div>
    </section>
  );
}

export default function Overview() {
  const [days, setDays] = useState(30);
  const [month, setMonth] = useState(todayIso().slice(0, 7));
  const { data: ov, isLoading, error, refetch } = useOverview(days, month);

  return (
    <>
      <div className="page-head">
        <div>
          <h1>Visão geral</h1>
          <p>Sua situação hoje e para onde ela vai</p>
        </div>
        <div className="segmented" aria-label="Horizonte da projeção">
          {[30, 60, 90].map((d) => (
            <button key={d} aria-pressed={days === d} onClick={() => setDays(d)}>{d} dias</button>
          ))}
        </div>
      </div>
      {isLoading && <div className="panel"><Skeleton lines={6} /></div>}
      {error && !ov && <ErrorState message={errorMessage(error)} onRetry={() => refetch()} />}
      {ov && (
        <>
          <div className="kpis">
            <Kpi label="Saldo agora" value={brl(ov.kpis.balance_cents)} />
            <Kpi label="Entrou no mês" value={brl(ov.kpis.month_income_cents)} tone="in" />
            <Kpi label="Saiu no mês" value={brl(ov.kpis.month_expense_cents)} />
            <Kpi label="Fim do mês (estimativa)" value={brl(ov.kpis.projected_month_end_cents)} tone={ov.kpis.projected_month_end_cents < 0 ? "warn" : undefined} />
            <Kpi label={`A pagar em ${days} dias`} value={brl(ov.kpis.to_pay_cents)} hint={ov.kpis.overdue_count ? `${ov.kpis.overdue_count} atrasado(s)` : undefined} tone={ov.kpis.overdue_count ? "warn" : undefined} />
            <Kpi label={`A receber em ${days} dias`} value={brl(ov.kpis.to_receive_cents)} tone="in" />
            <Kpi label="Dívidas restantes" value={brl(ov.kpis.debts_remaining_cents)} />
            <Kpi label="Parcelamentos restantes" value={brl(ov.kpis.installments_remaining_cents)} />
          </div>

          {ov.alerts.length > 0 && (
            <div style={{ margin: "16px 0" }}>
              {ov.alerts.slice(0, 5).map((a) => (
                <div key={a.text} className={`alert ${a.level === "danger" ? "danger" : a.level === "warning" ? "warning" : ""}`}>
                  {a.level === "info" ? <Info size={18} /> : <AlertTriangle size={18} />}
                  <span>{a.text}</span>
                </div>
              ))}
            </div>
          )}

          <div className="grid cols-3-1" style={{ marginTop: 16 }}>
            <BalanceChart ov={ov} />
            <section className="panel" style={{ marginTop: 0 }}>
              <h2 style={{ marginBottom: 8 }}>Se tudo acontecer como previsto</h2>
              <p className="small muted" style={{ marginBottom: 12 }}>Calculado pelo JULIUS a partir dos compromissos cadastrados.</p>
              <div className="stat"><div className="label">Hoje</div><div className="value num">{brl(ov.timeline.start_balance_cents)}</div></div>
              <div className="stat" style={{ marginTop: 12 }}><div className="label">Em {days} dias</div><div className="value num">{brl(ov.timeline.end_balance_cents)}</div></div>
              <div className="stat" style={{ marginTop: 12 }}>
                <div className="label">Menor saldo no caminho</div>
                <div className="value num" style={ov.timeline.lowest.balance_cents < 0 ? { color: "var(--danger)" } : undefined}>{brl(ov.timeline.lowest.balance_cents)}</div>
                <div className="small muted">em {fullDate(ov.timeline.lowest.date)}</div>
              </div>
            </section>
          </div>

          <div className="grid cols-2" style={{ marginTop: 16 }}>
            <section className="panel" style={{ marginTop: 0 }}>
              <div className="panel-head">
                <h2>Próximos compromissos</h2>
                <Link to="/futuros">Ver todos</Link>
              </div>
              <TimelineList events={ov.timeline.events} start={ov.timeline.start_balance_cents} />
            </section>
            <Calendar days={ov.calendar} month={month} onMonth={setMonth} />
          </div>

          <div className="grid cols-2" style={{ marginTop: 16 }}>
            <MonthlyChart data={ov.monthly} />
            <section className="panel" style={{ marginTop: 0 }}>
              <div className="panel-head"><h2>Gastos por categoria (mês)</h2><Link to="/relatorios">Relatório</Link></div>
              {ov.categories.length === 0 && <p className="small muted">Sem despesas neste mês.</p>}
              <ul className="list" style={{ display: "grid", gap: 12 }}>
                {ov.categories.slice(0, 6).map((c) => (
                  <li key={c.category_id ?? "none"}>
                    <div style={{ display: "flex", justifyContent: "space-between", fontSize: "0.9rem", marginBottom: 4 }}>
                      <span>{c.name}</span>
                      <span className="num">{brl(c.total_cents)} <span className="muted small">· {Math.round(c.share * 100)}%</span></span>
                    </div>
                    <div className="progress" aria-hidden="true"><i style={{ width: `${(c.total_cents / ov.categories[0].total_cents) * 100}%` }} /></div>
                  </li>
                ))}
              </ul>
            </section>
          </div>

          <div className="grid cols-3" style={{ marginTop: 16 }}>
            <section className="panel" style={{ marginTop: 0 }}>
              <div className="panel-head"><h2>Dívidas</h2><Link to="/dividas">Gerenciar</Link></div>
              {ov.debts.length === 0 && <p className="small muted">Nenhuma dívida em aberto.</p>}
              {ov.debts.map((d) => (
                <div key={d.id} style={{ display: "grid", gap: 6, marginBottom: 14 }}>
                  <div style={{ display: "flex", justifyContent: "space-between" }}>
                    <strong>{d.name}</strong>
                    <span className="num">{brl(d.remaining_cents)}</span>
                  </div>
                  <Progress ratio={1 - d.remaining_installments / d.installments_total} label={`Progresso de ${d.name}`} />
                  <span className="small muted">
                    {d.remaining_installments} de {d.installments_total} parcelas restantes{d.next_due ? ` · próxima ${shortDate(d.next_due)}` : ""}
                    {d.situation === "atrasada" && <span className="badge danger" style={{ marginLeft: 6 }}>atrasada</span>}
                  </span>
                </div>
              ))}
            </section>
            <section className="panel" style={{ marginTop: 0 }}>
              <h2 style={{ marginBottom: 8 }}>Parcelamentos</h2>
              {ov.installments.length === 0 && <p className="small muted">Nenhuma compra parcelada em andamento.</p>}
              <ul className="list">
                {ov.installments.slice(0, 6).map((p) => (
                  <li key={p.id} className="row">
                    <div className="main-col">
                      <div className="title">{p.description}</div>
                      <div className="sub">{p.remaining_installments} de {p.installments} restantes{p.next_date ? ` · próxima ${shortDate(p.next_date)}` : ""}</div>
                    </div>
                    <span className="num">{brl(p.remaining_cents)}</span>
                  </li>
                ))}
              </ul>
            </section>
            <section className="panel" style={{ marginTop: 0 }}>
              <div className="panel-head"><h2>Recorrentes e metas</h2><Link to="/recorrentes">Ver</Link></div>
              <div className="stat-row">
                <div className="stat"><div className="label">Entram por mês</div><div className="value num income">{brl(ov.recurring.monthly_in_cents)}</div></div>
                <div className="stat"><div className="label">Saem por mês</div><div className="value num">{brl(ov.recurring.monthly_out_cents)}</div></div>
              </div>
              {ov.goals.slice(0, 2).map((g) => (
                <div key={g.id} style={{ display: "grid", gap: 6, marginTop: 14 }}>
                  <strong>{g.name}</strong>
                  <Progress ratio={g.progress_cents / g.target_cents} label={`Meta ${g.name}`} />
                  <span className="small muted num">{brl(g.progress_cents)} de {brl(g.target_cents)}</span>
                </div>
              ))}
            </section>
          </div>
        </>
      )}
    </>
  );
}
