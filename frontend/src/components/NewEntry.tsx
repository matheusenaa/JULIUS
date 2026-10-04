import { Camera, Loader2, Send, Sparkles } from "lucide-react";
import { useState, type FormEvent } from "react";

import { api, ApiError, errorMessage } from "../lib/api";
import { brl, dayLabel, FREQUENCY_LABEL, PAYMENT_LABEL, TYPE_LABEL } from "../lib/format";
import { createTransaction, useOnline } from "../lib/offline";
import { invalidateFinance, useAccounts, useAiStatus, useCategories } from "../lib/queries";
import type { Proposal, Transaction } from "../lib/types";
import { useToast } from "./Toast";
import { TransactionForm, type FormInitial } from "./TransactionForm";
import { Button, CategoryIcon, Sheet } from "./ui";

type Tab = "quick" | "manual" | "receipt";

const EXAMPLES = ["gastei 45 no mercado", "recebi 3200 de salário", "comprei um tênis de 600 em 3x", "internet 100 todo mês dia 15"];

function proposalToInitial(p: Proposal): FormInitial {
  return {
    type: p.type,
    amount_cents: p.amount_cents ?? undefined,
    occurred_on: p.occurred_on,
    description: p.description,
    category_id: p.category_id,
    account_id: p.account_id ?? undefined,
    to_account_id: p.to_account_id,
    payment_method: p.payment_method,
    status: p.status,
    is_fixed: p.is_fixed,
    installments: p.installments,
    notes: p.notes ?? undefined,
  };
}

function ProposalCard({ p }: { p: Proposal }) {
  const categories = useCategories().data ?? [];
  const accounts = useAccounts().data ?? [];
  const cat = categories.find((c) => c.id === p.category_id);
  const parent = cat?.parent_id ? categories.find((c) => c.id === cat.parent_id) : null;
  const account = accounts.find((a) => a.id === p.account_id);
  const toAccount = accounts.find((a) => a.id === p.to_account_id);
  return (
    <div className="proposal" aria-live="polite">
      <div style={{ display: "flex", alignItems: "center", gap: 12 }}>
        <CategoryIcon category={cat} parent={parent} />
        <div style={{ flex: 1 }}>
          <div className="small muted">
            {TYPE_LABEL[p.type]}
            {p.status === "pending" && " prevista"}
            {p.installments > 1 && ` · ${p.installments}x`}
          </div>
          <div className={`amount num ${p.type === "income" ? "income" : ""}`}>
            {p.amount_cents ? brl(p.amount_cents) : "Valor não identificado"}
          </div>
        </div>
      </div>
      <div className="small">
        <strong>{p.description}</strong>
        {" · "}
        {cat ? (parent && parent.name !== cat.name ? `${parent.name} › ${cat.name}` : cat.name) : p.type === "transfer" ? "Transferência" : "Sem categoria"}
      </div>
      <div className="small muted">
        {dayLabel(p.occurred_on)}
        {account && ` · ${account.name}`}
        {toAccount && ` → ${toAccount.name}`}
        {p.payment_method && ` · ${PAYMENT_LABEL[p.payment_method]}`}
      </div>
      {p.installments > 1 && p.amount_cents && (
        <div className="small muted">Total de {brl(p.amount_cents)} dividido em {p.installments} parcelas pelo sistema.</div>
      )}
      {p.learned && <span className="badge green">Categoria aprendida com suas correções</span>}
      {p.ai_error && <span className="badge warn">IA indisponível — interpretado localmente</span>}
    </div>
  );
}

export function QuickTab({ onDone, onCorrect, autoFocus = true }: { onDone: () => void; onCorrect: (i: FormInitial) => void; autoFocus?: boolean }) {
  const toast = useToast();
  const online = useOnline();
  const [text, setText] = useState("");
  const [loading, setLoading] = useState(false);
  const [saving, setSaving] = useState(false);
  const [proposal, setProposal] = useState<Proposal | null>(null);
  const [error, setError] = useState<string | null>(null);

  async function interpret(e: FormEvent) {
    e.preventDefault();
    if (!text.trim()) return;
    if (!online) {
      onCorrect({ description: text.trim() });
      toast("Sem internet: preencha os campos; o lançamento será sincronizado depois.");
      return;
    }
    setLoading(true);
    setError(null);
    setProposal(null);
    try {
      setProposal(await api<Proposal>("/api/quick-input/parse", { body: { text } }));
    } catch (err) {
      if (err instanceof ApiError && err.offline) onCorrect({ description: text.trim() });
      else setError(errorMessage(err));
    } finally {
      setLoading(false);
    }
  }

  async function confirm(asRecurrence = false) {
    if (!proposal || !proposal.amount_cents || !proposal.account_id) return;
    setSaving(true);
    setError(null);
    try {
      if (asRecurrence && proposal.recurrence && proposal.type !== "transfer") {
        await api("/api/recurrences", {
          body: {
            type: proposal.type,
            account_id: proposal.account_id,
            category_id: proposal.category_id,
            description: proposal.description,
            amount_cents: proposal.amount_cents,
            payment_method: proposal.payment_method,
            is_fixed: true,
            frequency: proposal.recurrence.frequency,
            day_of_month: proposal.recurrence.frequency === "monthly" ? proposal.recurrence.day_of_month : null,
            start_date: proposal.occurred_on,
          },
        });
        invalidateFinance();
        toast(`Recorrência criada: ${proposal.description}. Ela aparecerá nos próximos vencimentos.`);
      } else {
        const result = await createTransaction({
          ...proposalToInitial(proposal),
          type: proposal.type,
          amount_cents: proposal.amount_cents,
          account_id: proposal.account_id,
          occurred_on: proposal.occurred_on,
          description: proposal.description,
          source: proposal.engine === "ai" ? "ai" : "quick_input",
        });
        invalidateFinance();
        toast(result.queued ? "Salvo no aparelho; será sincronizado." : "Lançamento registrado.");
      }
      setText("");
      setProposal(null);
      onDone();
    } catch (err) {
      setError(errorMessage(err));
    } finally {
      setSaving(false);
    }
  }

  const incomplete = proposal && (!proposal.amount_cents || proposal.missing.length > 0);
  return (
    <div>
      <form className="quick" onSubmit={interpret}>
        <input
          aria-label="O que aconteceu?"
          placeholder="O que aconteceu? Ex.: gastei 50 no almoço"
          value={text}
          maxLength={500}
          onChange={(e) => setText(e.target.value)}
          autoFocus={autoFocus}
        />
        <Button type="submit" variant="accent" className="icon" aria-label="Interpretar" loading={loading}>
          {!loading && <Send size={18} />}
        </Button>
      </form>

      {!proposal && !loading && (
        <div className="chips examples" style={{ marginTop: 12 }}>
          {EXAMPLES.map((ex) => (
            <button key={ex} type="button" className="chip" onClick={() => setText(ex)}>
              {ex}
            </button>
          ))}
        </div>
      )}

      {error && (
        <div className="alert danger" role="alert" style={{ marginTop: 12 }}>
          {error}
        </div>
      )}

      {proposal && (
        <>
          <ProposalCard p={proposal} />
          {incomplete && (
            <div className="alert warning" style={{ marginTop: 12 }}>
              Faltam informações ({proposal.amount_cents ? "conta" : "valor"}). Toque em “Corrigir” para completar.
            </div>
          )}
          <div className="form-actions" style={{ marginTop: 16 }}>
            <Button variant="ghost" onClick={() => setProposal(null)}>
              Ignorar
            </Button>
            <Button onClick={() => onCorrect(proposalToInitial(proposal))}>Corrigir</Button>
            {proposal.recurrence && !incomplete && (
              <Button onClick={() => confirm(true)} disabled={saving}>
                Criar recorrência ({FREQUENCY_LABEL[proposal.recurrence.frequency].toLowerCase()}
                {proposal.recurrence.frequency === "monthly" ? `, dia ${proposal.recurrence.day_of_month}` : ""})
              </Button>
            )}
            <Button variant="primary" onClick={() => confirm(false)} loading={saving} disabled={!!incomplete}>
              Confirmar
            </Button>
          </div>
        </>
      )}
    </div>
  );
}

function ReceiptTab({ onDone }: { onDone: () => void }) {
  const toast = useToast();
  const ai = useAiStatus().data;
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [result, setResult] = useState<{ attachmentId: string; proposal: Proposal | null } | null>(null);

  async function upload(file: File) {
    setLoading(true);
    setError(null);
    setResult(null);
    const form = new FormData();
    form.append("file", file);
    try {
      const r = await api<{ attachment: { id: string }; proposal: Proposal | null; error: string | null }>("/api/receipts/scan", { form });
      setResult({ attachmentId: r.attachment.id, proposal: r.proposal });
      if (r.error) setError(r.error);
    } catch (err) {
      setError(errorMessage(err));
    } finally {
      setLoading(false);
    }
  }

  async function linked(tx?: Transaction) {
    if (tx && result) {
      await api(`/api/attachments/${result.attachmentId}`, { method: "PATCH", body: { transaction_id: tx.id } }).catch(() =>
        toast("Lançamento salvo, mas o comprovante não foi anexado.", { kind: "error" }),
      );
    }
    onDone();
  }

  return (
    <div className="form">
      {ai && !ai.enabled && (
        <div className="alert">
          A leitura automática precisa de um provedor de IA configurado no servidor (ex.: Gemini, gratuito). Sem ele, o
          comprovante é guardado e você preenche os dados.
        </div>
      )}
      <label className="btn block" style={{ minHeight: 96, borderStyle: "dashed" }}>
        {loading ? <Loader2 className="spin" /> : <Camera />}
        {loading ? "Lendo comprovante…" : "Tirar foto ou escolher arquivo"}
        <input
          type="file"
          accept="image/jpeg,image/png,image/webp,application/pdf"
          capture="environment"
          hidden
          disabled={loading}
          onChange={(e) => e.target.files?.[0] && upload(e.target.files[0])}
        />
      </label>
      <p className="small muted">JPG, PNG, WEBP ou PDF até 8 MB. Confira sempre os dados antes de confirmar.</p>
      {error && <div className="alert warning">{error}</div>}
      {result && (
        <>
          {result.proposal && <ProposalCard p={result.proposal} />}
          <TransactionForm
            key={result.attachmentId}
            initial={result.proposal ? proposalToInitial(result.proposal) : undefined}
            source="ocr"
            onDone={linked}
          />
        </>
      )}
    </div>
  );
}

export function NewEntrySheet({ onClose, initialForm }: { onClose: () => void; initialForm?: FormInitial }) {
  const [tab, setTab] = useState<Tab>(initialForm ? "manual" : "quick");
  const [initial, setInitial] = useState<FormInitial | undefined>(initialForm);
  return (
    <Sheet title="Novo lançamento" onClose={onClose}>
      <div className="segmented" role="tablist" style={{ marginBottom: 20 }}>
        <button role="tab" aria-pressed={tab === "quick"} aria-selected={tab === "quick"} onClick={() => setTab("quick")}>
          <Sparkles size={14} style={{ verticalAlign: -2 }} /> Rápido
        </button>
        <button
          role="tab"
          aria-pressed={tab === "manual"}
          aria-selected={tab === "manual"}
          onClick={() => {
            setInitial(undefined);
            setTab("manual");
          }}
        >
          Manual
        </button>
        <button role="tab" aria-pressed={tab === "receipt"} aria-selected={tab === "receipt"} onClick={() => setTab("receipt")}>
          Comprovante
        </button>
      </div>
      {tab === "quick" && (
        <QuickTab
          onDone={onClose}
          onCorrect={(i) => {
            setInitial(i);
            setTab("manual");
          }}
        />
      )}
      {tab === "manual" && <TransactionForm key={JSON.stringify(initial ?? {})} initial={initial} source={initial ? "quick_input" : "manual"} onDone={onClose} />}
      {tab === "receipt" && <ReceiptTab onDone={onClose} />}
    </Sheet>
  );
}
