import { ChevronLeft, ChevronRight, Filter, Inbox, Search } from "lucide-react";
import { useMemo, useState } from "react";
import { useSearchParams } from "react-router";

import { CategorySelect } from "../components/TransactionForm";
import { TransactionList } from "../components/TransactionList";
import { Button, EmptyState, ErrorState, Field, Skeleton } from "../components/ui";
import { errorMessage } from "../lib/api";
import { brl, monthLabel, PAYMENT_LABEL, parseMoney } from "../lib/format";
import { useOutbox } from "../lib/offline";
import { useAccounts, useCategories, useTransactions, type TxFilters } from "../lib/queries";
import type { Transaction, TransactionInput } from "../lib/types";

function monthBounds(ym: string) {
  const [y, m] = ym.split("-").map(Number);
  const last = new Date(y, m, 0).getDate();
  return { start: `${ym}-01`, end: `${ym}-${String(last).padStart(2, "0")}` };
}

function shiftMonth(ym: string, delta: number) {
  const [y, m] = ym.split("-").map(Number);
  const d = new Date(y, m - 1 + delta, 1);
  return `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, "0")}`;
}

const now = new Date();
const CURRENT_YM = `${now.getFullYear()}-${String(now.getMonth() + 1).padStart(2, "0")}`;

export default function Transactions() {
  const [params, setParams] = useSearchParams();
  const [showFilters, setShowFilters] = useState(false);
  const [search, setSearch] = useState(params.get("q") ?? "");
  const accounts = useAccounts().data ?? [];
  const categories = useCategories().data ?? [];
  const outbox = useOutbox();

  const ym = params.get("mes") ?? CURRENT_YM;
  const allTime = params.get("mes") === "todos";
  const set = (key: string, value: string | null) => {
    const next = new URLSearchParams(params);
    if (value) next.set(key, value);
    else next.delete(key);
    if (key !== "page") next.delete("page");
    setParams(next, { replace: true });
  };

  const filters: TxFilters = {
    ...(allTime ? {} : monthBounds(ym)),
    type: params.get("tipo") ?? undefined,
    account_id: params.get("conta") ?? undefined,
    category_id: params.get("categoria") ?? undefined,
    payment_method: params.get("pagamento") ?? undefined,
    status: params.get("situacao") ?? undefined,
    q: params.get("q") ?? undefined,
    min_cents: params.get("min") ? Number(params.get("min")) : undefined,
    max_cents: params.get("max") ? Number(params.get("max")) : undefined,
    recurring: params.get("recorrentes") === "1" || undefined,
    uncategorized: params.get("sem_categoria") === "1" || undefined,
    page: Number(params.get("page") ?? 1),
  };
  const { data, isLoading, error, refetch, isFetching } = useTransactions(filters);

  const queued: Transaction[] = useMemo(
    () =>
      outbox
        .filter((o) => o.op === "create") // edições/exclusões pendentes aparecem em Ajustes → Sincronização
        .map((o) => {
          const b = o.body as TransactionInput;
          return {
            ...b,
            id: o.entityId,
            status: b.status ?? "paid",
            to_account_id: b.to_account_id ?? null,
            notes: b.notes ?? null,
            category_id: b.category_id ?? null,
            payment_method: b.payment_method ?? null,
            is_fixed: !!b.is_fixed,
            source: b.source ?? "manual",
            invoice_month: null,
            recurrence_id: null,
            installment_plan_id: null,
            installment_number: null,
            installment_total: b.installments && b.installments > 1 ? b.installments : null,
            version: 0,
            created_at: "",
            updated_at: "",
            _queued: true,
          };
        }),
    [outbox],
  );

  const activeFilters = ["tipo", "conta", "categoria", "pagamento", "situacao", "min", "max", "recorrentes", "sem_categoria"].filter((k) => params.get(k)).length;
  const totalPages = data ? Math.max(1, Math.ceil(data.total / data.page_size)) : 1;
  const kindForCategory = params.get("tipo") === "income" ? "income" : "expense";

  return (
    <>
      <div className="page-head">
        <div>
          <h1>Lançamentos</h1>
          <p>Histórico completo das suas movimentações</p>
        </div>
      </div>

      <div className="panel" style={{ marginBottom: 16 }}>
        <div style={{ display: "flex", alignItems: "center", gap: 8, flexWrap: "wrap" }}>
          {!allTime && (
            <>
              <Button variant="ghost" className="icon" aria-label="Mês anterior" onClick={() => set("mes", shiftMonth(ym, -1))}>
                <ChevronLeft size={18} />
              </Button>
              <strong style={{ minWidth: 150, textAlign: "center" }}>{monthLabel(`${ym}-01`)}</strong>
              <Button variant="ghost" className="icon" aria-label="Próximo mês" onClick={() => set("mes", shiftMonth(ym, 1))}>
                <ChevronRight size={18} />
              </Button>
            </>
          )}
          <button className="chip" aria-pressed={allTime} onClick={() => set("mes", allTime ? null : "todos")}>
            Todo o período
          </button>
          <form
            className="quick"
            style={{ flex: "1 1 220px", padding: "2px 2px 2px 12px" }}
            onSubmit={(e) => {
              e.preventDefault();
              set("q", search.trim() || null);
            }}
          >
            <Search size={16} className="muted" aria-hidden="true" />
            <input aria-label="Buscar na descrição" placeholder="Buscar descrição" value={search} onChange={(e) => setSearch(e.target.value)} style={{ minHeight: 38 }} />
          </form>
          <Button variant={activeFilters ? "primary" : undefined} onClick={() => setShowFilters((v) => !v)} aria-expanded={showFilters}>
            <Filter size={16} /> Filtros{activeFilters ? ` (${activeFilters})` : ""}
          </Button>
        </div>

        <div className="chips" style={{ marginTop: 12 }}>
          {[
            ["", "Tudo"],
            ["expense", "Despesas"],
            ["income", "Receitas"],
            ["transfer", "Transferências"],
          ].map(([v, l]) => (
            <button key={l} className="chip" aria-pressed={(params.get("tipo") ?? "") === v} onClick={() => set("tipo", v || null)}>
              {l}
            </button>
          ))}
        </div>

        {showFilters && (
          <div className="form" style={{ marginTop: 16 }}>
            <div className="form-row">
              <Field label="Conta ou cartão">
                <select className="select" value={params.get("conta") ?? ""} onChange={(e) => set("conta", e.target.value || null)}>
                  <option value="">Todas</option>
                  {accounts.map((a) => (
                    <option key={a.id} value={a.id}>
                      {a.name}
                    </option>
                  ))}
                </select>
              </Field>
              <Field label="Categoria">
                <CategorySelect categories={categories} kind={kindForCategory} value={params.get("categoria") ?? ""} onChange={(v) => set("categoria", v || null)} />
              </Field>
            </div>
            <div className="form-row">
              <Field label="Forma de pagamento">
                <select className="select" value={params.get("pagamento") ?? ""} onChange={(e) => set("pagamento", e.target.value || null)}>
                  <option value="">Todas</option>
                  {Object.entries(PAYMENT_LABEL).map(([k, v]) => (
                    <option key={k} value={k}>
                      {v}
                    </option>
                  ))}
                </select>
              </Field>
              <Field label="Situação">
                <select className="select" value={params.get("situacao") ?? ""} onChange={(e) => set("situacao", e.target.value || null)}>
                  <option value="">Todas</option>
                  <option value="paid">Realizados</option>
                  <option value="pending">Previstos</option>
                </select>
              </Field>
            </div>
            <div className="form-row">
              <Field label="Valor mínimo (R$)">
                <input className="input" inputMode="decimal" defaultValue={params.get("min") ? String(Number(params.get("min")) / 100) : ""} onBlur={(e) => set("min", parseMoney(e.target.value)?.toString() ?? null)} />
              </Field>
              <Field label="Valor máximo (R$)">
                <input className="input" inputMode="decimal" defaultValue={params.get("max") ? String(Number(params.get("max")) / 100) : ""} onBlur={(e) => set("max", parseMoney(e.target.value)?.toString() ?? null)} />
              </Field>
            </div>
            <div className="chips">
              <label className="check">
                <input type="checkbox" checked={params.get("recorrentes") === "1"} onChange={(e) => set("recorrentes", e.target.checked ? "1" : null)} />
                Só recorrentes e parcelados
              </label>
              <label className="check">
                <input type="checkbox" checked={params.get("sem_categoria") === "1"} onChange={(e) => set("sem_categoria", e.target.checked ? "1" : null)} />
                Só sem categoria
              </label>
              <Button variant="ghost" size="small" onClick={() => setParams(params.get("mes") ? { mes: params.get("mes")! } : {}, { replace: true })}>
                Limpar filtros
              </Button>
            </div>
          </div>
        )}
      </div>

      {data && (
        <div className="stat-row" style={{ marginBottom: 16 }}>
          <div className="panel stat">
            <div className="label">Entradas</div>
            <div className="value num income">{brl(data.income_cents)}</div>
          </div>
          <div className="panel stat" style={{ marginTop: 0 }}>
            <div className="label">Saídas</div>
            <div className="value num">{brl(data.expense_cents)}</div>
          </div>
          <div className="panel stat" style={{ marginTop: 0 }}>
            <div className="label">Resultado</div>
            <div className="value num">{brl(data.income_cents - data.expense_cents)}</div>
          </div>
        </div>
      )}

      <section className="panel" aria-busy={isFetching}>
        {queued.length > 0 && filters.page === 1 && (
          <>
            <div className="group-title">Aguardando sincronização</div>
            <TransactionList items={queued} grouped={false} />
          </>
        )}
        {isLoading && <Skeleton lines={6} />}
        {error && !data && <ErrorState message={errorMessage(error)} onRetry={() => refetch()} />}
        {data && data.items.length === 0 && (
          <EmptyState icon={Inbox} title="Nenhum lançamento encontrado" text={activeFilters || filters.q ? "Tente remover alguns filtros." : "Use o botão “Novo lançamento” para registrar."} />
        )}
        {data && data.items.length > 0 && <TransactionList items={data.items} />}
        {data && totalPages > 1 && (
          <div className="form-actions" style={{ justifyContent: "center", marginTop: 16 }}>
            <Button size="small" disabled={filters.page! <= 1} onClick={() => set("page", String(filters.page! - 1))}>
              Anterior
            </Button>
            <span className="small muted" style={{ alignSelf: "center" }}>
              Página {filters.page} de {totalPages} · {data.total} lançamentos
            </span>
            <Button size="small" disabled={filters.page! >= totalPages} onClick={() => set("page", String(filters.page! + 1))}>
              Próxima
            </Button>
          </div>
        )}
      </section>
    </>
  );
}
