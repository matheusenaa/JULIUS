import { Camera, CheckCircle2, FileText, Loader2, Trash2, Upload } from "lucide-react";
import { useState } from "react";

import { useToast } from "../components/Toast";
import { TransactionForm } from "../components/TransactionForm";
import { Button, EmptyState, ErrorState, Sheet, Skeleton } from "../components/ui";
import { api, errorMessage } from "../lib/api";
import { brl, DOC_KIND_LABEL, fullDate, shortDate } from "../lib/format";
import { compressImage } from "../lib/image";
import { invalidateFinance, queryClient, useAccounts, useCategories, useDocuments } from "../lib/queries";
import type { DocumentItem, Proposal, Transaction } from "../lib/types";

type Review = { doc: DocumentItem; proposal: (Proposal & { warnings?: string[] }) | null; error: string | null };

const STATUS = { review: "Para revisar", confirmed: "Confirmado", discarded: "Descartado", uploaded: "Enviado" } as const;

function refresh() {
  queryClient.invalidateQueries({ queryKey: ["documents"] });
  invalidateFinance();
}

function ReviewSheet({ review, onClose }: { review: Review; onClose: () => void }) {
  const toast = useToast();
  const categories = useCategories().data ?? [];
  const accounts = useAccounts().data ?? [];
  const { doc, proposal: p } = review;
  const [editing, setEditing] = useState(false);
  const [monthly, setMonthly] = useState(!!p?.recurrence);
  const [saving, setSaving] = useState(false);
  const cat = categories.find((c) => c.id === p?.category_id);
  const account = accounts.find((a) => a.id === p?.account_id);
  const incomplete = !p || !p.amount_cents || !p.account_id;

  async function confirm() {
    if (!p || incomplete) return;
    setSaving(true);
    try {
      const transaction = {
        type: p.type, amount_cents: p.amount_cents, occurred_on: p.occurred_on, description: p.description,
        category_id: p.category_id, account_id: p.account_id, payment_method: p.payment_method, status: p.status,
        is_fixed: monthly, notes: p.notes ?? null,
      };
      const next = new Date(`${p.occurred_on}T12:00:00`);
      next.setMonth(next.getMonth() + 1);
      const recurrence = monthly && p.recurrence
        ? {
            type: p.type, account_id: p.account_id, category_id: p.category_id, description: p.description,
            amount_cents: p.amount_cents, payment_method: p.payment_method, frequency: "monthly",
            day_of_month: p.recurrence.day_of_month, start_date: next.toISOString().slice(0, 10),
          }
        : null;
      await api(`/api/documents/${doc.id}/confirm`, { body: { transaction, recurrence } });
      refresh();
      toast(monthly ? "Lançado e programado para os próximos meses." : "Documento confirmado e lançado.");
      onClose();
    } catch (err) {
      toast(errorMessage(err), { kind: "error" });
    } finally {
      setSaving(false);
    }
  }

  async function discard() {
    await api(`/api/documents/${doc.id}/discard`, { method: "POST" }).catch(() => undefined);
    refresh();
    onClose();
  }

  async function linked(tx?: Transaction) {
    if (tx) {
      await api(`/api/attachments/${doc.id}`, { method: "PATCH", body: { transaction_id: tx.id } }).catch(() =>
        toast("Lançado, mas não foi possível vincular o documento.", { kind: "error" }),
      );
    }
    refresh();
    onClose();
  }

  return (
    <Sheet title={editing ? "Editar antes de lançar" : "Documento encontrado"} onClose={onClose}>
      {editing ? (
        <TransactionForm
          initial={p ? { type: p.type, amount_cents: p.amount_cents ?? undefined, occurred_on: p.occurred_on, description: p.description,
            category_id: p.category_id, account_id: p.account_id ?? undefined, payment_method: p.payment_method, status: p.status, notes: p.notes ?? undefined }
            : { description: doc.title ?? "" }}
          source="ocr"
          onDone={linked}
        />
      ) : (
        <div className="form">
          {review.error && <div className="alert warning">{review.error}</div>}
          {p?.warnings?.map((w) => <div key={w} className="alert warning">{w}</div>)}
          {p && (
            <div className="proposal">
              <div className="small muted">{DOC_KIND_LABEL[doc.kind]} · lido por {p.engine === "rules" ? "leitura automática" : p.engine === "ai" ? "IA" : "leitura automática + IA"}</div>
              <strong style={{ fontSize: "1.1rem" }}>{p.description}</strong>
              <div className="amount num">{p.amount_cents ? brl(p.amount_cents) : "Valor não identificado"}</div>
              <div className="small">
                {p.status === "pending" ? `Vence em ${fullDate(p.occurred_on)}` : `Data: ${fullDate(p.occurred_on)}`}
                {cat && ` · ${cat.name}`}{account && ` · ${account.name}`}
              </div>
              {doc.barcode && (
                <div className="small" style={{ wordBreak: "break-all" }}>
                  Linha digitável: <span className="num">{doc.barcode}</span>{" "}
                  {doc.barcode_valid ? <span className="badge green"><CheckCircle2 size={11} /> verificada</span> : <span className="badge warn">confira</span>}
                </div>
              )}
              {doc.beneficiary && <div className="small">Beneficiário: {doc.beneficiary}</div>}
              {doc.document_number && <div className="small">Nº do documento: {doc.document_number}</div>}
              {doc.pix_key && <div className="small">Chave Pix: {doc.pix_key}</div>}
            </div>
          )}
          {p?.recurrence && (
            <label className="check">
              <input type="checkbox" checked={monthly} onChange={(e) => setMonthly(e.target.checked)} />
              Repetir todo mês (dia {p.recurrence.day_of_month})?
            </label>
          )}
          <a className="link small" href={`/api/documents/${doc.id}/file`} target="_blank" rel="noreferrer">Ver arquivo original</a>
          <div className="form-actions">
            <Button variant="ghost" onClick={discard}>Cancelar</Button>
            {p ? (
              <>
                <Button onClick={() => setEditing(true)}>Editar</Button>
                <Button variant="primary" loading={saving} disabled={incomplete} onClick={confirm}>Confirmar</Button>
              </>
            ) : (
              <Button variant="primary" onClick={() => setEditing(true)}>Preencher manualmente</Button>
            )}
          </div>
        </div>
      )}
    </Sheet>
  );
}

export default function Documents() {
  const toast = useToast();
  const [filter, setFilter] = useState<string | undefined>(undefined);
  const { data, isLoading, error, refetch } = useDocuments(filter);
  const [uploading, setUploading] = useState(false);
  const [review, setReview] = useState<Review | null>(null);

  async function upload(original: File) {
    setUploading(true);
    try {
      const file = await compressImage(original);
      const form = new FormData();
      form.append("file", file);
      const r = await api<{ document: DocumentItem; proposal: Review["proposal"]; error: string | null }>("/api/documents", { form });
      queryClient.invalidateQueries({ queryKey: ["documents"] });
      setReview({ doc: r.document, proposal: r.proposal, error: r.error });
    } catch (err) {
      toast(errorMessage(err), { kind: "error" });
    } finally {
      setUploading(false);
    }
  }

  async function openReview(doc: DocumentItem) {
    try {
      const r = await api<{ document: DocumentItem; proposal: Review["proposal"]; error: string | null }>(`/api/documents/${doc.id}/analyze`, { method: "POST" });
      setReview({ doc: r.document, proposal: r.proposal, error: r.error });
    } catch (err) {
      toast(errorMessage(err), { kind: "error" });
    }
  }

  async function remove(doc: DocumentItem) {
    if (!window.confirm(`Excluir "${doc.title ?? doc.filename}"? O arquivo será apagado.`)) return;
    await api(`/api/documents/${doc.id}`, { method: "DELETE" }).catch((err) => toast(errorMessage(err), { kind: "error" }));
    refresh();
  }

  const input = (capture: boolean) => (
    <input
      type="file"
      accept="image/jpeg,image/png,image/webp,application/pdf"
      {...(capture ? { capture: "environment" as const } : {})}
      hidden
      disabled={uploading}
      onChange={(e) => {
        const f = e.target.files?.[0];
        e.target.value = "";
        if (f) upload(f);
      }}
    />
  );

  return (
    <>
      <div className="page-head">
        <div>
          <h1>Documentos</h1>
          <p>Contas, boletos, comprovantes e notas — o JULIUS lê e você confirma</p>
        </div>
      </div>
      <div className="grid cols-2" style={{ marginBottom: 16 }}>
        <label className="btn block" style={{ minHeight: 88, borderStyle: "dashed" }}>
          {uploading ? <Loader2 className="spin" /> : <Camera />} {uploading ? "Lendo documento…" : "Tirar foto"}
          {input(true)}
        </label>
        <label className="btn block" style={{ minHeight: 88, borderStyle: "dashed" }}>
          {uploading ? <Loader2 className="spin" /> : <Upload />} {uploading ? "Enviando…" : "Escolher arquivo (foto ou PDF)"}
          {input(false)}
        </label>
      </div>
      <p className="small muted" style={{ marginBottom: 12 }}>
        PDFs de contas e boletos são lidos mesmo sem IA (inclusive a linha digitável). Fotos precisam de IA configurada. Nada é lançado sem sua confirmação.
      </p>
      <div className="chips" style={{ marginBottom: 12 }}>
        {[[undefined, "Todos"], ["review", "Para revisar"], ["confirmed", "Confirmados"], ["discarded", "Descartados"]].map(([k, l]) => (
          <button key={l} className="chip" aria-pressed={filter === k} onClick={() => setFilter(k)}>{l}</button>
        ))}
      </div>
      <section className="panel">
        {isLoading && <Skeleton lines={4} />}
        {error && !data && <ErrorState message={errorMessage(error)} onRetry={() => refetch()} />}
        {data && data.items.length === 0 && <EmptyState icon={FileText} title="Nenhum documento" text="Tire uma foto de uma conta ou envie o PDF de um boleto." />}
        <ul className="list">
          {data?.items.map((d) => (
            <li key={d.id} className="row">
              <span className="cat-dot" aria-hidden="true"><FileText size={18} /></span>
              <div className="main-col">
                <div className="title">{d.title ?? d.filename}</div>
                <div className="sub">
                  {DOC_KIND_LABEL[d.kind]} · {shortDate(d.created_at)}
                  {d.due_date && ` · vence ${shortDate(d.due_date)}`}
                  <span className={`badge ${d.status === "confirmed" ? "green" : d.status === "review" ? "warn" : ""}`} style={{ marginLeft: 6 }}>{STATUS[d.status]}</span>
                </div>
              </div>
              {d.amount_cents != null && <span className="num">{brl(d.amount_cents)}</span>}
              {d.status === "review" && <Button size="small" onClick={() => openReview(d)}>Revisar</Button>}
              <a className="btn small ghost" href={`/api/documents/${d.id}/file`} target="_blank" rel="noreferrer">Abrir</a>
              <Button size="small" variant="ghost" className="icon" aria-label={`Excluir ${d.title ?? d.filename}`} onClick={() => remove(d)}><Trash2 size={15} /></Button>
            </li>
          ))}
        </ul>
      </section>
      {review && <ReviewSheet review={review} onClose={() => setReview(null)} />}
    </>
  );
}
