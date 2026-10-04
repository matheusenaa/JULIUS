import { AlertTriangle, ArrowLeftRight, CloudUpload } from "lucide-react";
import { useState } from "react";

import { dayLabel, isOverdue, PAYMENT_LABEL, STATUS_LABEL } from "../lib/format";
import { useAccounts, useCategories } from "../lib/queries";
import type { Transaction } from "../lib/types";
import { TransactionForm } from "./TransactionForm";
import { Amount, CategoryIcon, Sheet } from "./ui";

export function TransactionRow({ tx, onOpen }: { tx: Transaction; onOpen?: (tx: Transaction) => void }) {
  const categories = useCategories().data ?? [];
  const accounts = useAccounts().data ?? [];
  const cat = categories.find((c) => c.id === tx.category_id);
  const parent = cat?.parent_id ? categories.find((c) => c.id === cat.parent_id) : null;
  const account = accounts.find((a) => a.id === tx.account_id);
  const to = accounts.find((a) => a.id === tx.to_account_id);
  const sub = [
    tx.type === "transfer" ? `${account?.name ?? "?"} → ${to?.name ?? "?"}` : cat ? cat.name : "Sem categoria",
    tx.type !== "transfer" && account?.name,
    tx.payment_method && tx.type !== "transfer" && PAYMENT_LABEL[tx.payment_method],
  ]
    .filter(Boolean)
    .join(" · ");

  return (
    <li
      className={`row ${onOpen ? "clickable" : ""}`}
      onClick={onOpen ? () => onOpen(tx) : undefined}
      onKeyDown={onOpen ? (e) => (e.key === "Enter" || e.key === " ") && onOpen(tx) : undefined}
      tabIndex={onOpen ? 0 : undefined}
      role={onOpen ? "button" : undefined}
      aria-label={onOpen ? `Editar ${tx.description}` : undefined}
    >
      {tx.type === "transfer" ? (
        <span className="cat-dot" aria-hidden="true">
          <ArrowLeftRight size={18} />
        </span>
      ) : (
        <CategoryIcon category={cat} parent={parent} />
      )}
      <div className="main-col">
        <div className="title" style={tx.status === "canceled" ? { textDecoration: "line-through", opacity: 0.6 } : undefined}>
          {tx.description}
        </div>
        <div className="sub">{sub}</div>
      </div>
      <div style={{ textAlign: "right" }}>
        <Amount cents={tx.amount_cents} type={tx.type} />
        <div style={{ display: "flex", gap: 4, justifyContent: "flex-end", marginTop: 2 }}>
          {tx._queued && (
            <span className="badge warn">
              <CloudUpload size={11} /> fila
            </span>
          )}
          {isOverdue(tx) ? (
            <span className="badge danger">
              <AlertTriangle size={11} /> atrasado
            </span>
          ) : tx.status !== "paid" ? (
            <span className={`badge ${STATUS_LABEL[tx.status]?.tone ?? ""}`}>{STATUS_LABEL[tx.status]?.label.toLowerCase()}</span>
          ) : null}
          {tx.debt_installment && <span className="badge">dívida</span>}
          {tx.is_fixed && <span className="badge">fixa</span>}
          {tx.installment_total && (
            <span className="badge">
              {tx.installment_number}/{tx.installment_total}
            </span>
          )}
        </div>
      </div>
    </li>
  );
}

/** Lista agrupada por dia, com edição em folha/modal. */
export function TransactionList({ items, grouped = true }: { items: Transaction[]; grouped?: boolean }) {
  const [editing, setEditing] = useState<Transaction | null>(null);
  const groups: [string, Transaction[]][] = [];
  for (const tx of items) {
    const last = groups[groups.length - 1];
    if (grouped && last && last[0] === tx.occurred_on) last[1].push(tx);
    else groups.push([tx.occurred_on, [tx]]);
  }
  return (
    <>
      {groups.map(([day, txs]) => (
        <section key={day + txs[0].id}>
          {grouped && <div className="group-title">{dayLabel(day)}</div>}
          <ul className="list">
            {txs.map((tx) => (
              <TransactionRow key={tx.id} tx={tx} onOpen={tx._queued ? undefined : setEditing} />
            ))}
          </ul>
        </section>
      ))}
      {editing && (
        <Sheet title="Editar lançamento" onClose={() => setEditing(null)}>
          <TransactionForm editing={editing} onDone={() => setEditing(null)} />
        </Sheet>
      )}
    </>
  );
}
