import { ChevronRight, Download, LogOut, RefreshCw, Trash2, Upload } from "lucide-react";
import { useState, type FormEvent } from "react";
import { Link } from "react-router";

import { NAV } from "../components/AppShell";
import { useToast } from "../components/Toast";
import { Button, Field } from "../components/ui";
import { api, errorMessage } from "../lib/api";
import { brl, fullDate } from "../lib/format";
import { discardItem, retryItem, useOutbox } from "../lib/offline";
import { clearLocalData, pendingOutboxCount } from "../lib/session";
import { invalidateFinance, queryClient, useAccounts, useAiStatus, useAudit, useMe } from "../lib/queries";
import { getTheme, setTheme, type Theme } from "../lib/theme";
import type { User } from "../lib/types";

function Profile({ me }: { me: User }) {
  const toast = useToast();
  const accounts = useAccounts().data ?? [];
  const [name, setName] = useState(me.name);
  const [defaultAccount, setDefaultAccount] = useState(me.settings.default_account_id ?? "");
  const [saving, setSaving] = useState(false);

  async function save(e: FormEvent) {
    e.preventDefault();
    setSaving(true);
    try {
      await api("/api/auth/me", { method: "PATCH", body: { name: name.trim(), default_account_id: defaultAccount || null } });
      queryClient.invalidateQueries({ queryKey: ["me"] });
      toast("Perfil salvo.");
    } catch (err) {
      toast(errorMessage(err), { kind: "error" });
    } finally {
      setSaving(false);
    }
  }

  return (
    <form className="form" onSubmit={save}>
      <div className="form-row">
        <Field label="Nome">
          <input className="input" value={name} maxLength={80} onChange={(e) => setName(e.target.value)} />
        </Field>
        <Field label="E-mail">
          <input className="input" value={me.email} disabled />
        </Field>
      </div>
      <Field label="Conta padrão para lançamentos rápidos">
        <select className="select" value={defaultAccount} onChange={(e) => setDefaultAccount(e.target.value)}>
          <option value="">Automática</option>
          {accounts.map((a) => (
            <option key={a.id} value={a.id}>
              {a.name}
            </option>
          ))}
        </select>
      </Field>
      <div className="form-actions">
        <Button type="submit" loading={saving}>
          Salvar perfil
        </Button>
      </div>
    </form>
  );
}

function Password() {
  const toast = useToast();
  const [current, setCurrent] = useState("");
  const [next, setNext] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [saving, setSaving] = useState(false);
  async function submit(e: FormEvent) {
    e.preventDefault();
    if (next.length < 10) return setError("A nova senha precisa ter pelo menos 10 caracteres.");
    setSaving(true);
    setError(null);
    try {
      await api("/api/auth/password", { body: { current_password: current, new_password: next } });
      setCurrent("");
      setNext("");
      toast("Senha alterada. Outros aparelhos foram desconectados.");
    } catch (err) {
      setError(errorMessage(err));
    } finally {
      setSaving(false);
    }
  }
  return (
    <form className="form" onSubmit={submit}>
      <div className="form-row">
        <Field label="Senha atual">
          <input className="input" type="password" autoComplete="current-password" value={current} onChange={(e) => setCurrent(e.target.value)} />
        </Field>
        <Field label="Nova senha" hint="Mínimo de 10 caracteres">
          <input className="input" type="password" autoComplete="new-password" value={next} onChange={(e) => setNext(e.target.value)} />
        </Field>
      </div>
      {error && <div className="alert danger">{error}</div>}
      <div className="form-actions">
        <Button type="submit" loading={saving}>
          Alterar senha
        </Button>
      </div>
    </form>
  );
}

function SyncQueue() {
  const items = useOutbox();
  const toast = useToast();
  if (!items.length) return <p className="small muted">Tudo sincronizado. Lançamentos feitos sem internet aparecem aqui até serem enviados.</p>;
  return (
    <ul className="list">
      {items.map((i) => (
        <li key={i.id} className="row">
          <div className="main-col">
            <div className="title">
              {i.body.description} · {brl(i.body.amount_cents)}
            </div>
            <div className="sub" style={i.status === "failed" ? { color: "var(--danger)" } : undefined}>
              {i.status === "failed" ? `Não aceito pelo servidor: ${i.error}` : `Aguardando conexão · ${fullDate(i.body.occurred_on)}`}
            </div>
          </div>
          <Button size="small" variant="ghost" aria-label="Tentar enviar de novo" onClick={() => retryItem(i.id).then(invalidateFinance)}>
            <RefreshCw size={15} />
          </Button>
          <Button
            size="small"
            variant="ghost"
            aria-label="Descartar"
            onClick={() => {
              if (window.confirm(`Descartar "${i.body.description}"? Ele não foi salvo no servidor.`)) discardItem(i.id).then(() => toast("Item descartado."));
            }}
          >
            <Trash2 size={15} />
          </Button>
        </li>
      ))}
    </ul>
  );
}

function Backup() {
  const toast = useToast();
  const [busy, setBusy] = useState(false);
  async function restore(file: File) {
    if (!window.confirm("Restaurar este backup? Apenas registros que ainda não existem serão adicionados; nada será apagado.")) return;
    setBusy(true);
    const form = new FormData();
    form.append("file", file);
    try {
      const r = await api<{ inserted: Record<string, number> }>("/api/import/backup", { form });
      invalidateFinance();
      queryClient.invalidateQueries({ queryKey: ["categories"] });
      toast(`Backup restaurado: ${r.inserted.transactions ?? 0} lançamento(s) adicionados.`);
    } catch (err) {
      toast(errorMessage(err), { kind: "error" });
    } finally {
      setBusy(false);
    }
  }
  return (
    <div className="chips">
      <a className="btn" href="/api/export/transactions.csv">
        <Download size={16} /> Lançamentos (CSV / Excel)
      </a>
      <a className="btn" href="/api/export/backup.json">
        <Download size={16} /> Backup completo (JSON)
      </a>
      <label className="btn" aria-busy={busy}>
        <Upload size={16} /> Restaurar backup
        <input type="file" accept="application/json,.json" hidden onChange={(e) => e.target.files?.[0] && restore(e.target.files[0])} />
      </label>
    </div>
  );
}

function Audit() {
  const { data, isLoading } = useAudit();
  const [all, setAll] = useState(false);
  if (isLoading) return <p className="small muted">Carregando…</p>;
  const items = (data ?? []).slice(0, all ? 100 : 8);
  return (
    <>
      <ul className="list">
        {items.map((e) => (
          <li key={e.id} className="row">
            <div className="main-col">
              <div className="title" style={{ whiteSpace: "normal", fontWeight: 450 }}>
                {e.summary}
              </div>
              <div className="sub">{new Date(e.created_at).toLocaleString("pt-BR")}</div>
            </div>
          </li>
        ))}
      </ul>
      {!all && (data?.length ?? 0) > 8 && (
        <Button size="small" variant="ghost" onClick={() => setAll(true)}>
          Ver mais
        </Button>
      )}
    </>
  );
}

export default function Settings() {
  const me = useMe().data;
  const ai = useAiStatus().data;
  const [theme, setThemeState] = useState<Theme>(getTheme());

  async function logout() {
    const pending = await pendingOutboxCount();
    if (pending && !window.confirm(`${pending} lançamento(s) feitos sem internet ainda não foram enviados e serão perdidos ao sair. Sair mesmo assim?`)) return;
    try {
      await api("/api/auth/logout", { method: "POST" });
    } finally {
      await clearLocalData();
      window.location.href = "/entrar";
    }
  }

  return (
    <>
      <div className="page-head">
        <div>
          <h1>Ajustes</h1>
          <p>Perfil, segurança e seus dados</p>
        </div>
        <Button onClick={logout}>
          <LogOut size={16} /> Sair
        </Button>
      </div>

      <section className="panel">
        <h2 style={{ marginBottom: 16 }}>Perfil</h2>
        {me && <Profile me={me} />}
      </section>

      <section className="panel">
        <h2 style={{ marginBottom: 12 }}>Aparência</h2>
        <div className="segmented" style={{ maxWidth: 360 }}>
          {(
            [
              ["system", "Automático"],
              ["light", "Claro"],
              ["dark", "Escuro"],
            ] as [Theme, string][]
          ).map(([t, l]) => (
            <button
              key={t}
              aria-pressed={theme === t}
              onClick={() => {
                setTheme(t);
                setThemeState(t);
              }}
            >
              {l}
            </button>
          ))}
        </div>
      </section>

      <section className="panel" id="sincronizacao">
        <h2 style={{ marginBottom: 12 }}>Sincronização</h2>
        <SyncQueue />
      </section>

      <section className="panel">
        <h2 style={{ marginBottom: 4 }}>Seus dados</h2>
        <p className="small muted" style={{ marginBottom: 12 }}>
          Exporte quando quiser. O backup JSON pode ser restaurado em outra instalação do JULIUS.
        </p>
        <Backup />
      </section>

      <section className="panel">
        <h2 style={{ marginBottom: 8 }}>Inteligência artificial</h2>
        <p className="small">
          {ai?.enabled
            ? `Ativa (provedor: ${ai.provider}). Usada para interpretar textos, ler comprovantes e redigir conselhos — nunca para calcular valores.`
            : "Desativada. O JULIUS funciona normalmente com o interpretador local. Para ativar, configure AI_PROVIDER e a chave no servidor (veja o README)."}
        </p>
      </section>

      <section className="panel">
        <h2 style={{ marginBottom: 16 }}>Senha</h2>
        <Password />
      </section>

      <section className="panel">
        <h2 style={{ marginBottom: 8 }}>Histórico de alterações</h2>
        <Audit />
      </section>
    </>
  );
}

export function More() {
  return (
    <>
      <div className="page-head">
        <h1>Mais</h1>
      </div>
      <nav className="panel" aria-label="Mais opções">
        <ul className="list">
          {[...NAV.slice(4), { to: "/ajustes", label: "Ajustes", icon: NAV[0].icon }].map(({ to, label }) => (
            <li key={to}>
              <Link to={to} className="row" style={{ textDecoration: "none" }}>
                <span className="main-col title">{label}</span>
                <ChevronRight size={18} className="muted" />
              </Link>
            </li>
          ))}
        </ul>
      </nav>
    </>
  );
}
