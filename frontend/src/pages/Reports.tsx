import { ChevronLeft, ChevronRight, Download, Printer, Table2 } from "lucide-react";
import { useState } from "react";
import { Bar, BarChart, CartesianGrid, Line, LineChart, ResponsiveContainer, Tooltip, XAxis, YAxis } from "recharts";

import { Button, EmptyState, ErrorState, Skeleton } from "../components/ui";
import { errorMessage } from "../lib/api";
import { brl, fullDate, monthLabel, shortDate, shortMonth, todayIso } from "../lib/format";
import { useReport } from "../lib/queries";
import type { Report } from "../lib/types";

type Period = Report["period"];
const PERIODS: [Period, string][] = [
  ["day", "Dia"],
  ["week", "Semana"],
  ["month", "Mês"],
  ["year", "Ano"],
];
const PREV_LABEL: Record<Period, string> = { day: "dia anterior", week: "semana anterior", month: "mês anterior", year: "ano anterior" };

function shift(ref: string, period: Period, delta: number): string {
  const [y, m, d] = ref.split("-").map(Number);
  const date = new Date(y, m - 1, d);
  if (period === "day") date.setDate(date.getDate() + delta);
  if (period === "week") date.setDate(date.getDate() + 7 * delta);
  if (period === "month") date.setMonth(date.getMonth() + delta, 1);
  if (period === "year") date.setFullYear(date.getFullYear() + delta, 0, 1);
  return `${date.getFullYear()}-${String(date.getMonth() + 1).padStart(2, "0")}-${String(date.getDate()).padStart(2, "0")}`;
}

function title(r: Report): string {
  if (r.period === "day") return fullDate(r.start);
  if (r.period === "week") return `${shortDate(r.start)} a ${shortDate(r.end)}`;
  if (r.period === "month") return monthLabel(r.start);
  return r.start.slice(0, 4);
}

function Delta({ now, before, invert = false }: { now: number; before: number; invert?: boolean }) {
  if (!before) return <span className="small muted">sem dados no período anterior</span>;
  const pct = Math.round(((now - before) / before) * 100);
  const good = invert ? pct <= 0 : pct >= 0;
  return (
    <span className={`badge ${pct === 0 ? "" : good ? "green" : "pink"}`}>
      {pct > 0 ? "+" : ""}
      {pct}%
    </span>
  );
}

const axisMoney = (cents: number) => {
  const reais = cents / 100;
  if (Math.abs(reais) < 1000) return String(Math.round(reais));
  return `${(reais / 1000).toLocaleString("pt-BR", { maximumFractionDigits: 1 })}k`;
};

function ChartTooltip({ active, payload, label, period }: { active?: boolean; payload?: { dataKey: string; value: number }[]; label?: string; period: Period }) {
  if (!active || !payload?.length || !label) return null;
  return (
    <div className="panel" style={{ padding: "10px 12px", boxShadow: "var(--shadow-lg)" }}>
      <strong className="small">{period === "year" ? monthLabel(label) : fullDate(label)}</strong>
      {payload.map((p) => (
        <div key={p.dataKey} className="small" style={{ display: "flex", gap: 8, alignItems: "center" }}>
          <i style={{ width: 10, height: 10, borderRadius: 3, background: p.dataKey === "income" ? "var(--chart-in)" : "var(--chart-out)" }} />
          {p.dataKey === "income" ? "Entrou" : "Saiu"}: <span className="num">{brl(p.value)}</span>
        </div>
      ))}
    </div>
  );
}

function FlowChart({ r }: { r: Report }) {
  const [asTable, setAsTable] = useState(false);
  const data = r.series;
  return (
    <section className="panel">
      <div className="panel-head">
        <h2>Entradas e saídas</h2>
        <Button size="small" variant="ghost" onClick={() => setAsTable((v) => !v)} aria-pressed={asTable}>
          <Table2 size={15} /> {asTable ? "Ver gráfico" : "Ver tabela"}
        </Button>
      </div>
      <div className="chips small" style={{ marginBottom: 8 }} aria-hidden={asTable}>
        <span className="check">
          <i style={{ width: 12, height: 12, borderRadius: 3, background: "var(--chart-in)" }} /> Entrou
        </span>
        <span className="check">
          <i style={{ width: 12, height: 12, borderRadius: 3, background: "var(--chart-out)" }} /> Saiu
        </span>
      </div>
      {asTable ? (
        <div style={{ overflowX: "auto" }}>
          <table className="table">
            <thead>
              <tr>
                <th>{r.period === "year" ? "Mês" : "Dia"}</th>
                <th className="right">Entrou</th>
                <th className="right">Saiu</th>
              </tr>
            </thead>
            <tbody>
              {data
                .filter((d) => d.income || d.expense)
                .map((d) => (
                  <tr key={d.label}>
                    <td>{r.period === "year" ? monthLabel(d.label) : fullDate(d.label)}</td>
                    <td className="right num">{brl(d.income)}</td>
                    <td className="right num">{brl(d.expense)}</td>
                  </tr>
                ))}
            </tbody>
          </table>
        </div>
      ) : (
        <div style={{ width: "100%", height: 260 }} role="img" aria-label="Gráfico de barras de entradas e saídas no período">
          <ResponsiveContainer>
            <BarChart data={data} barGap={2} margin={{ top: 8, right: 4, left: -12, bottom: 0 }}>
              <CartesianGrid vertical={false} stroke="var(--line)" />
              <XAxis
                dataKey="label"
                tickFormatter={(v: string) => (r.period === "year" ? shortMonth(v) : v.slice(8, 10))}
                tick={{ fill: "var(--ink-3)", fontSize: 12 }}
                axisLine={false}
                tickLine={false}
                interval="preserveStartEnd"
                minTickGap={8}
              />
              <YAxis tickFormatter={axisMoney} tick={{ fill: "var(--ink-3)", fontSize: 12 }} axisLine={false} tickLine={false} width={48} />
              <Tooltip content={<ChartTooltip period={r.period} />} cursor={{ fill: "var(--surface-2)" }} />
              <Bar isAnimationActive={false} dataKey="income" fill="var(--chart-in)" radius={[4, 4, 0, 0]} maxBarSize={22} />
              <Bar isAnimationActive={false} dataKey="expense" fill="var(--chart-out)" radius={[4, 4, 0, 0]} maxBarSize={22} />
            </BarChart>
          </ResponsiveContainer>
        </div>
      )}
    </section>
  );
}

function ForecastChart({ r }: { r: Report }) {
  const f = r.forecast;
  if (!f.available || !f.points) {
    return (
      <section className="panel">
        <h2>Projeção de saldo</h2>
        <p className="muted small" style={{ marginTop: 8 }}>
          {f.reason ?? "Ainda não há dados suficientes para projetar."}
        </p>
      </section>
    );
  }
  const data = [{ month: todayIso().slice(0, 7) + "-01", balance_cents: f.current_cents }, ...f.points];
  const last = data[data.length - 1];
  return (
    <section className="panel">
      <div className="panel-head">
        <h2>Projeção de saldo</h2>
        <span className="badge warn">Estimativa</span>
      </div>
      <p className="small muted" style={{ marginBottom: 12 }}>
        Se o ritmo médio dos últimos {f.based_on_months} mês(es) continuar ({brl(f.avg_net_cents ?? 0)}/mês), o saldo seria de cerca de{" "}
        <strong className="num">{brl(last.balance_cents)}</strong> em {monthLabel(last.month).toLowerCase()}. Não é garantia.
      </p>
      <div style={{ width: "100%", height: 200 }} role="img" aria-label="Linha de projeção de saldo">
        <ResponsiveContainer>
          <LineChart data={data} margin={{ top: 8, right: 8, left: -12, bottom: 0 }}>
            <CartesianGrid vertical={false} stroke="var(--line)" />
            <XAxis dataKey="month" tickFormatter={shortMonth} tick={{ fill: "var(--ink-3)", fontSize: 12 }} axisLine={false} tickLine={false} />
            <YAxis tickFormatter={axisMoney} tick={{ fill: "var(--ink-3)", fontSize: 12 }} axisLine={false} tickLine={false} width={48} />
            <Tooltip
              formatter={(v) => [brl(Number(v)), "Saldo estimado"]}
              labelFormatter={(l) => monthLabel(String(l))}
              contentStyle={{ background: "var(--surface)", border: "1px solid var(--line)", borderRadius: 12 }}
            />
            <Line isAnimationActive={false} type="monotone" dataKey="balance_cents" stroke="var(--chart-line)" strokeWidth={2} strokeDasharray="5 4" dot={{ r: 4 }} activeDot={{ r: 6 }} />
          </LineChart>
        </ResponsiveContainer>
      </div>
    </section>
  );
}

export default function Reports() {
  const [period, setPeriod] = useState<Period>("month");
  const [ref, setRef] = useState(todayIso());
  const { data: r, isLoading, error, refetch } = useReport(period, ref);

  return (
    <>
      <div className="page-head">
        <div>
          <h1>Relatórios</h1>
          <p>Quanto entrou, quanto saiu e para onde foi</p>
        </div>
        <div className="chips">
          <a className="btn small" href="/api/export/transactions.csv">
            <Download size={15} /> Planilha (CSV)
          </a>
          <Button size="small" onClick={() => window.print()}>
            <Printer size={15} /> Imprimir / PDF
          </Button>
        </div>
      </div>

      <div className="panel" style={{ marginBottom: 16, display: "flex", gap: 12, flexWrap: "wrap", alignItems: "center" }}>
        <div className="segmented" style={{ flex: "1 1 260px" }}>
          {PERIODS.map(([p, l]) => (
            <button key={p} aria-pressed={period === p} onClick={() => setPeriod(p)}>
              {l}
            </button>
          ))}
        </div>
        <div style={{ display: "flex", alignItems: "center", gap: 4 }}>
          <Button variant="ghost" className="icon" aria-label="Período anterior" onClick={() => setRef(shift(ref, period, -1))}>
            <ChevronLeft size={18} />
          </Button>
          <strong style={{ minWidth: 140, textAlign: "center" }}>{r ? title(r) : "…"}</strong>
          <Button variant="ghost" className="icon" aria-label="Próximo período" onClick={() => setRef(shift(ref, period, 1))}>
            <ChevronRight size={18} />
          </Button>
        </div>
      </div>

      {isLoading && (
        <div className="panel">
          <Skeleton lines={5} />
        </div>
      )}
      {error && !r && <ErrorState message={errorMessage(error)} onRetry={() => refetch()} />}

      {r && (
        <>
          <div className="stat-row" style={{ marginBottom: 16 }}>
            <div className="panel stat">
              <div className="label">Entrou</div>
              <div className="value num">{brl(r.income_cents)}</div>
              <Delta now={r.income_cents} before={r.previous.income_cents} />
            </div>
            <div className="panel stat" style={{ marginTop: 0 }}>
              <div className="label">Saiu</div>
              <div className="value num">{brl(r.expense_cents)}</div>
              <Delta now={r.expense_cents} before={r.previous.expense_cents} invert />
            </div>
            <div className="panel stat" style={{ marginTop: 0 }}>
              <div className="label">{r.net_cents >= 0 ? "Sobrou" : "Faltou"}</div>
              <div className="value num">{brl(r.net_cents)}</div>
              <span className="small muted">
                {r.savings_rate !== null ? `${Math.round(r.savings_rate * 100)}% do que entrou` : `vs ${PREV_LABEL[r.period]}: ${brl(r.previous.net_cents)}`}
              </span>
            </div>
            <div className="panel stat" style={{ marginTop: 0 }}>
              <div className="label">Fixas · Variáveis</div>
              <div className="value num" style={{ fontSize: "1rem" }}>
                {brl(r.fixed_cents)} · {brl(r.variable_cents)}
              </div>
            </div>
          </div>

          {r.income_cents === 0 && r.expense_cents === 0 ? (
            <div className="panel">
              <EmptyState icon={Table2} title="Sem movimentações neste período" text="Escolha outro período ou registre lançamentos." />
            </div>
          ) : (
            <>
              {r.period !== "day" && <FlowChart r={r} />}
              <div className="grid cols-2" style={{ marginTop: 16 }}>
                <section className="panel">
                  <h2 style={{ marginBottom: 16 }}>Gastos por categoria</h2>
                  {r.by_category.length === 0 && <p className="muted small">Nenhuma despesa.</p>}
                  <ul className="list" style={{ display: "grid", gap: 14 }}>
                    {r.by_category.map((c) => (
                      <li key={c.category_id ?? "none"}>
                        <div style={{ display: "flex", justifyContent: "space-between", gap: 8, fontSize: "0.9rem", marginBottom: 4 }}>
                          <span>{c.name}</span>
                          <span className="num">
                            {brl(c.total_cents)} {!!c.previous_cents && <Delta now={c.total_cents} before={c.previous_cents} invert />}
                          </span>
                        </div>
                        <div className="progress" aria-hidden="true">
                          <i style={{ width: `${(c.total_cents / r.by_category[0].total_cents) * 100}%` }} />
                        </div>
                      </li>
                    ))}
                  </ul>
                </section>
                <section className="panel">
                  <h2 style={{ marginBottom: 8 }}>Maiores despesas</h2>
                  <ul className="list">
                    {r.top_expenses.map((t) => (
                      <li key={t.id} className="row">
                        <div className="main-col">
                          <div className="title">{t.description}</div>
                          <div className="sub">{fullDate(t.date)}</div>
                        </div>
                        <span className="num">{brl(t.amount_cents)}</span>
                      </li>
                    ))}
                  </ul>
                </section>
              </div>
            </>
          )}
          <div style={{ marginTop: 16 }}>
            <ForecastChart r={r} />
          </div>
        </>
      )}
    </>
  );
}
