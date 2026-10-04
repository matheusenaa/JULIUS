import { Plus } from "lucide-react";
import { useState, type FormEvent } from "react";

import { useToast } from "../components/Toast";
import { Button, CategoryIcon, ErrorState, Field, Sheet, Skeleton } from "../components/ui";
import { api, errorMessage } from "../lib/api";
import { invalidateFinance, queryClient, useCategories } from "../lib/queries";
import type { Category } from "../lib/types";

type Editing = { category?: Category; parent?: Category; kind: "expense" | "income" };

function CategoryForm({ editing, onDone }: { editing: Editing; onDone: () => void }) {
  const toast = useToast();
  const [name, setName] = useState(editing.category?.name ?? "");
  const [error, setError] = useState<string | null>(null);
  const [saving, setSaving] = useState(false);
  const [confirmDelete, setConfirmDelete] = useState(false);

  const refresh = () => {
    queryClient.invalidateQueries({ queryKey: ["categories"] });
    invalidateFinance();
  };

  async function submit(e: FormEvent) {
    e.preventDefault();
    if (!name.trim()) return setError("Informe o nome.");
    setSaving(true);
    try {
      if (editing.category) await api(`/api/categories/${editing.category.id}`, { method: "PATCH", body: { name: name.trim() } });
      else await api("/api/categories", { body: { name: name.trim(), kind: editing.kind, parent_id: editing.parent?.id ?? null } });
      refresh();
      toast("Categoria salva.");
      onDone();
    } catch (err) {
      setError(errorMessage(err));
    } finally {
      setSaving(false);
    }
  }

  async function remove() {
    try {
      await api(`/api/categories/${editing.category!.id}`, { method: "DELETE" });
      refresh();
      toast("Categoria excluída.");
      onDone();
    } catch (err) {
      setError(errorMessage(err));
    }
  }

  return (
    <form className="form" onSubmit={submit}>
      {editing.parent && <p className="small muted">Subcategoria de {editing.parent.name}</p>}
      <Field label="Nome">
        <input className="input" value={name} maxLength={60} onChange={(e) => setName(e.target.value)} />
      </Field>
      {confirmDelete && (
        <div className="alert warning">
          Os lançamentos desta categoria{editing.category?.parent_id ? "" : " e de suas subcategorias"} ficarão “sem categoria”. Nenhum lançamento é apagado.
        </div>
      )}
      {error && <div className="alert danger">{error}</div>}
      <div className="form-actions">
        {editing.category && (
          <Button type="button" variant="danger" style={{ marginRight: "auto" }} onClick={() => (confirmDelete ? remove() : setConfirmDelete(true))}>
            {confirmDelete ? "Confirmar exclusão" : "Excluir"}
          </Button>
        )}
        <Button type="submit" variant="primary" loading={saving}>
          Salvar
        </Button>
      </div>
    </form>
  );
}

export default function Categories() {
  const { data, isLoading, error, refetch } = useCategories();
  const [kind, setKind] = useState<"expense" | "income">("expense");
  const [editing, setEditing] = useState<Editing | null>(null);
  const parents = (data ?? []).filter((c) => c.kind === kind && !c.parent_id);

  return (
    <>
      <div className="page-head">
        <div>
          <h1>Categorias</h1>
          <p>Organize do seu jeito. O JULIUS aprende com suas correções.</p>
        </div>
        <Button variant="primary" onClick={() => setEditing({ kind })}>
          <Plus size={16} /> Nova categoria
        </Button>
      </div>
      <div className="segmented" style={{ maxWidth: 320, marginBottom: 16 }}>
        <button aria-pressed={kind === "expense"} onClick={() => setKind("expense")}>
          Despesas
        </button>
        <button aria-pressed={kind === "income"} onClick={() => setKind("income")}>
          Receitas
        </button>
      </div>
      {isLoading && <Skeleton lines={6} />}
      {error && !data && <ErrorState message={errorMessage(error)} onRetry={() => refetch()} />}
      <div className="grid cols-2">
        {parents.map((p) => {
          const children = (data ?? []).filter((c) => c.parent_id === p.id);
          return (
            <section key={p.id} className="panel" style={{ marginTop: 0 }}>
              <div className="panel-head" style={{ marginBottom: children.length ? 8 : 0 }}>
                <button className="row clickable" style={{ border: 0, background: "none", padding: 0, flex: 1 }} onClick={() => setEditing({ category: p, kind })}>
                  <CategoryIcon category={p} />
                  <strong>{p.name}</strong>
                </button>
                <Button size="small" variant="ghost" onClick={() => setEditing({ parent: p, kind })} aria-label={`Nova subcategoria em ${p.name}`}>
                  <Plus size={15} /> Sub
                </Button>
              </div>
              {children.length > 0 && (
                <div className="chips">
                  {children.map((c) => (
                    <button key={c.id} className="chip" onClick={() => setEditing({ category: c, parent: p, kind })}>
                      {c.name}
                    </button>
                  ))}
                </div>
              )}
            </section>
          );
        })}
      </div>
      {editing && (
        <Sheet title={editing.category ? "Editar categoria" : editing.parent ? "Nova subcategoria" : "Nova categoria"} onClose={() => setEditing(null)}>
          <CategoryForm editing={editing} onDone={() => setEditing(null)} />
        </Sheet>
      )}
    </>
  );
}
