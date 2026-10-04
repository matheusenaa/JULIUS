import { ChevronRight, CloudUpload, Download, LogOut, RefreshCw, Trash2, Upload } from "lucide-react";
import { useState, type FormEvent } from "react";
import { Link } from "react-router";

import { MOBILE_NAV, NAV } from "../components/AppShell";
import { useToast } from "../components/Toast";
import { CategorySelect } from "../components/TransactionForm";
import { Button, Field, Sheet } from "../components/ui";
import { api, errorMessage } from "../lib/api";
import { brl, fullDate, setCurrency, TYPE_LABEL } from "../lib/format";
import { discardItem, keepMine, retryItem, useOutbox } from "../lib/offline";
import { invalidateFinance, queryClient, useAccounts, useAiStatus, useAudit, useCategories, useMe, useSyncStatus } from "../lib/queries";
import { clearLocalData, pendingOutboxCount } from "../lib/session";
import { getTheme, setTheme, type Theme } from "../lib/theme";
import type { User } from "../lib/types";

async function saveSettings(body: Record<string, unknown>) {
  const user = await api<User>("/api/auth/me", { method: "PATCH", body });
  queryClient.setQueryData(["me"], user);
  return user;
}

function Section({ id, title, children, hint }: { id?: string; title: string; hint?: string; children: React.ReactNode }) {
  return (
    <section className="panel" id={id}>
      <h2 style={{ marginBottom: hint ? 4 : 16 }}>{title}</h2>
      {hint && <p className="small muted" style={{ marginBottom: 16 }}>{hint}</p>}
      {children}
    </section>
  );
}

function Profile({ me }: { me: User }) {
  const toast = useToast();
  const accounts = useAccounts().data ?? [];
  const [name, setName] = useState(me.name);
  const [defaultAccount, setDefaultAccount] = useState(me.settings.default_account_id ?? "");
  const [currency, setCurrencyState] = useState(me.settings.currency ?? "BRL");
  const [saving, setSaving] = useState(false);

  async function save(e: FormEvent) {
    e.preventDefault();
    setSaving(true);
    try {
      await saveSettings({ name: name.trim(), default_account_id: defaultAccount || null, currency });
      setCurrency(currency);
      invalidateFinance();
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
        <Field label="Nome"><input className="input" value={name} maxLength={80} onChange={(e) => setName(e.target.value)} /></Field>
        <Field label="E-mail"><input className="input" value={me.email} disabled /></Field>
      </div>
      <div className="form-row">
        <Field label="Moeda" hint="Só a forma de exibir; o JULIUS não converte valores entre moedas.">
          <select className="select" value={currency} onChange={(e) => setCurrencyState(e.target.value as typeof currency)}>
            <option value="BRL">Real (R$)</option>
            <option value="USD">Dólar (US$)</option>
            <option value="EUR">Euro (€)</option>
          </select>
        </Field>
        <Field label="Conta padrão para lançamentos rápidos">
          <select className="select" value={defaultAccount} onChange={(e) => setDefaultAccount(e.target.value)}>
            <option value="">Automática</option>
            {accounts.map((a) => <option key={a.id} value={a.id}>{a.name}</option>)}
          </select>
        </Field>
      </div>
      <Field label="Idioma"><input className="input" value="Português (Brasil)" disabled /></Field>
      <div className="form-actions"><Button type="submit" loading={saving}>Salvar perfil</Button></div>
    </form>
  );
}

function Notifications({ me }: { me: User }) {
  const toast = useToast();
  const supported = typeof window !== "undefined" && "Notification" in window;
  const [enabled, setEnabled] = useState(!!me.settings.notify_due);
  async function toggle(on: boolean) {
    if (on && supported && Notification.permission !== "granted") {
      const perm = await Notification.requestPermission();
      if (perm !== "granted") return toast("O navegador não permitiu notificações.", { kind: "error" });
    }
    setEnabled(on);
    await saveSettings({ notify_due: on }).catch((err) => toast(errorMessage(err), { kind: "error" }));
  }
  return (
    <>
      <label className="check">
        <input type="checkbox" checked={enabled} disabled={!supported} onChange={(e) => toggle(e.target.checked)} />
        Avisar no aparelho sobre contas que vencem hoje e amanhã
      </label>
      <p className="small muted">{supported ? "O aviso aparece uma vez por dia, quando o JULIUS é aberto." : "Este navegador não suporta notificações."} Alertas também aparecem no Início e na Visão geral.</p>
    </>
  );
}

function AISettings({ me }: { me: User }) {
  const toast = useToast();
  const ai = useAiStatus().data;
  const [instructions, setInstructions] = useState(me.settings.ai_custom_instructions ?? "");
  const set = (body: Record<string, unknown>, msg = "Preferência salva.") =>
    saveSettings(body).then(() => { queryClient.invalidateQueries({ queryKey: ["ai-status"] }); toast(msg); }).catch((err) => toast(errorMessage(err), { kind: "error" }));
  async function clear(path: string, msg: string) {
    if (!window.confirm(`${msg}? Isso não pode ser desfeito.`)) return;
    await api(path, { method: "DELETE" }).then(() => toast("Apagado.")).catch((err) => toast(errorMessage(err), { kind: "error" }));
  }
  return (
    <div className="form">
      <p className="small">
        {ai?.configured
          ? `Provedor configurado no servidor: ${ai.provider}${ai.agent ? " (com ferramentas)" : ""}. A IA interpreta textos, lê documentos e responde perguntas abertas — nunca calcula valores.`
          : "Nenhum provedor de IA configurado no servidor. O JULIUS funciona normalmente com o interpretador local (veja o README para ativar o Gemini gratuito)."}
      </p>
      <label className="check">
        <input type="checkbox" checked={me.settings.ai_enabled !== false} onChange={(e) => set({ ai_enabled: e.target.checked })} />
        Usar IA quando disponível
      </label>
      <label className="check">
        <input type="checkbox" checked={me.settings.ai_share_descriptions !== false} onChange={(e) => set({ ai_share_descriptions: e.target.checked })} />
        Enviar a descrição dos lançamentos para a IA (desligado: ela vê só categoria, data e valor)
      </label>
      <Field label="Instruções do seu agente (opcional)" hint="Cole aqui as instruções do agente que você criou no Gemini. Elas complementam as regras do JULIUS, sem permitir que a IA altere dados sem sua confirmação.">
        <textarea className="textarea" rows={4} maxLength={4000} value={instructions} onChange={(e) => setInstructions(e.target.value)} />
      </Field>
      <div className="form-actions" style={{ justifyContent: "space-between" }}>
        <div className="chips">
          <Button size="small" variant="ghost" onClick={() => clear("/api/assistant/history", "Apagar todo o histórico de conversas")}>Apagar conversas</Button>
          <Button size="small" variant="ghost" onClick={() => clear("/api/assistant/learning", "Apagar o que o JULIUS aprendeu com suas correções")}>Apagar aprendizado</Button>
        </div>
        <Button size="small" onClick={() => set({ ai_custom_instructions: instructions.trim() || null }, "Instruções salvas.")}>Salvar instruções</Button>
      </div>
    </div>
  );
}

function SyncCenter() {
  const toast = useToast();
  const items = useOutbox();
  const status = useSyncStatus().data;
  const [link, setLink] = useState({ remote_url: "", email: "", password: "" });
  const [busy, setBusy] = useState(false);
  const label = { pending: "Aguardando conexão", syncing: "Sincronizando…", failed: "Falhou", conflict: "Conflito" } as const;

  async function run(fn: () => Promise<unknown>, ok: string) {
    setBusy(true);
    try {
      await fn();
      queryClient.invalidateQueries({ queryKey: ["sync-status"] });
      invalidateFinance();
      toast(ok);
    } catch (err) {
      toast(errorMessage(err), { kind: "error" });
    } finally {
      setBusy(false);
    }
  }

  return (
    <div className="form">
      <h3>Este aparelho</h3>
      {items.length === 0 ? (
        <p className="small muted">Tudo sincronizado. O que você fizer sem internet aparece aqui até ser enviado.</p>
      ) : (
        <ul className="list">
          {items.map((i) => (
            <li key={i.id} className="row" style={{ flexWrap: "wrap" }}>
              <div className="main-col">
                <div className="title">{i.op === "create" ? "Novo" : i.op === "update" ? "Edição" : "Exclusão"}: {i.label}{i.amountCents ? ` · ${brl(i.amountCents)}` : ""}</div>
                <div className="sub" style={i.status === "failed" || i.status === "conflict" ? { color: "var(--danger)" } : undefined}>
                  {label[i.status]}{i.error ? ` — ${i.error}` : ""}
                </div>
              </div>
              {i.status === "conflict" && i.server && (
                <div style={{ width: "100%" }} className="proposal">
                  <span className="small">No servidor agora: <strong>{i.server.description}</strong> · {brl(i.server.amount_cents)} · {fullDate(i.server.occurred_on)}</span>
                  <div className="chips">
                    <Button size="small" onClick={() => keepMine(i.id).then(invalidateFinance)}>Manter a minha alteração</Button>
                    <Button size="small" variant="ghost" onClick={() => discardItem(i.id).then(invalidateFinance)}>Ficar com a do servidor</Button>
                  </div>
                </div>
              )}
              {i.status === "failed" && (
                <>
                  <Button size="small" variant="ghost" aria-label="Tentar de novo" onClick={() => retryItem(i.id).then(invalidateFinance)}><RefreshCw size={15} /></Button>
                  <Button size="small" variant="ghost" aria-label="Descartar" onClick={() => window.confirm(`Descartar "${i.label}"? Ele não foi salvo no servidor.`) && discardItem(i.id)}><Trash2 size={15} /></Button>
                </>
              )}
            </li>
          ))}
        </ul>
      )}

      <h3 style={{ marginTop: 8 }}>Instalação no computador ↔ servidor online</h3>
      {status?.linked ? (
        <>
          <p className="small">
            Vinculado a <strong>{status.remote_url}</strong> ({status.remote_email}).{" "}
            {status.last_sync_at ? `Última sincronização: ${new Date(status.last_sync_at).toLocaleString("pt-BR")}.` : "Ainda não sincronizado."}
            {status.pending > 0 && ` ${status.pending} alteração(ões) a enviar.`}
          </p>
          {status.last_error && <div className="alert warning">{status.last_error}</div>}
          {status.conflicts.map((c) => (
            <div key={c.id} className="proposal">
              <strong className="small">Mesmo registro alterado aqui e no servidor ({c.entity === "transactions" ? "lançamento" : c.entity})</strong>
              <span className="small">Aqui: {String(c.local.description ?? c.local.name ?? "")} {typeof c.local.amount_cents === "number" ? `· ${brl(c.local.amount_cents)}` : ""}</span>
              <span className="small">Servidor: {String(c.remote.description ?? c.remote.name ?? "")} {typeof c.remote.amount_cents === "number" ? `· ${brl(c.remote.amount_cents)}` : ""}</span>
              <div className="chips">
                <Button size="small" onClick={() => run(() => api(`/api/sync/conflicts/${c.id}/resolve`, { body: { choice: "local" } }), "Mantida a versão deste computador.")}>Manter a deste computador</Button>
                <Button size="small" variant="ghost" onClick={() => run(() => api(`/api/sync/conflicts/${c.id}/resolve`, { body: { choice: "remote" } }), "Mantida a versão do servidor.")}>Manter a do servidor</Button>
              </div>
            </div>
          ))}
          <div className="chips">
            <Button size="small" loading={busy} onClick={() => run(() => api("/api/sync/run", { method: "POST" }), "Sincronizado.")}><CloudUpload size={15} /> Sincronizar agora</Button>
            <Button size="small" variant="ghost" onClick={() => window.confirm("Desvincular? Os dados deste computador continuam aqui.") && run(() => api("/api/sync/unlink", { method: "POST" }), "Desvinculado.")}>Desvincular</Button>
          </div>
        </>
      ) : (
        <form className="form" onSubmit={(e) => { e.preventDefault(); run(() => api("/api/sync/link", { body: link }), "Vinculado e sincronizado."); }}>
          <p className="small muted">Use isto na versão instalada no computador para manter os dados iguais aos do celular e do servidor online.</p>
          <Field label="Endereço do servidor online"><input className="input" type="url" placeholder="https://seu-julius.onrender.com" value={link.remote_url} onChange={(e) => setLink({ ...link, remote_url: e.target.value })} required /></Field>
          <div className="form-row">
            <Field label="E-mail da conta online"><input className="input" type="email" value={link.email} onChange={(e) => setLink({ ...link, email: e.target.value })} required /></Field>
            <Field label="Senha"><input className="input" type="password" value={link.password} onChange={(e) => setLink({ ...link, password: e.target.value })} required /></Field>
          </div>
          <div className="form-actions"><Button type="submit" loading={busy}>Vincular e sincronizar</Button></div>
        </form>
      )}
    </div>
  );
}

type ImportItem = { occurred_on: string; amount_cents: number; type: string; description: string; category_id: string | null; import_ref: string; duplicate: boolean };

function StatementImport() {
  const toast = useToast();
  const accounts = (useAccounts().data ?? []);
  const categories = useCategories().data ?? [];
  const [accountId, setAccountId] = useState("");
  const [items, setItems] = useState<(ImportItem & { selected: boolean })[] | null>(null);
  const [busy, setBusy] = useState(false);

  async function preview(file: File) {
    if (!accountId) return toast("Escolha a conta do extrato primeiro.", { kind: "error" });
    setBusy(true);
    const form = new FormData();
    form.append("file", file);
    form.append("account_id", accountId);
    try {
      const r = await api<{ items: ImportItem[] }>("/api/import/statement/preview", { form });
      setItems(r.items.map((i) => ({ ...i, selected: !i.duplicate })));
    } catch (err) {
      toast(errorMessage(err), { kind: "error" });
    } finally {
      setBusy(false);
    }
  }

  async function confirm() {
    if (!items) return;
    setBusy(true);
    try {
      const chosen = items.filter((i) => i.selected).map(({ selected: _s, duplicate: _d, ...rest }) => rest);
      const r = await api<{ created: number; skipped: number }>("/api/import/statement/confirm", { body: { account_id: accountId, items: chosen } });
      invalidateFinance();
      toast(`${r.created} lançamento(s) importado(s)${r.skipped ? `, ${r.skipped} ignorado(s)` : ""}.`);
      setItems(null);
    } catch (err) {
      toast(errorMessage(err), { kind: "error" });
    } finally {
      setBusy(false);
    }
  }

  return (
    <div className="form">
      <div className="form-row">
        <Field label="Conta do extrato">
          <select className="select" value={accountId} onChange={(e) => setAccountId(e.target.value)}>
            <option value="">Selecione</option>
            {accounts.map((a) => <option key={a.id} value={a.id}>{a.name}</option>)}
          </select>
        </Field>
        <Field label="Arquivo (OFX ou CSV do banco)">
          <label className="btn" aria-busy={busy}>
            <Upload size={16} /> Escolher extrato
            <input type="file" accept=".ofx,.csv,.txt" hidden onChange={(e) => { const f = e.target.files?.[0]; e.target.value = ""; if (f) preview(f); }} />
          </label>
        </Field>
      </div>
      {items && (
        <Sheet title={`Prévia: ${items.length} lançamentos`} onClose={() => setItems(null)}>
          <p className="small muted" style={{ marginBottom: 8 }}>Nada foi gravado ainda. Duplicados (já importados) vêm desmarcados.</p>
          <ul className="list" style={{ maxHeight: "50dvh", overflowY: "auto" }}>
            {items.map((i, idx) => (
              <li key={i.import_ref} className="row" style={{ flexWrap: "wrap" }}>
                <input type="checkbox" aria-label={`Importar ${i.description}`} checked={i.selected} onChange={(e) => setItems(items.map((x, j) => (j === idx ? { ...x, selected: e.target.checked } : x)))} />
                <div className="main-col">
                  <div className="title">{i.description}</div>
                  <div className="sub">{fullDate(i.occurred_on)} · {TYPE_LABEL[i.type as "income"]} {i.duplicate && <span className="badge warn">já importado</span>}</div>
                </div>
                <span className={`num ${i.type === "income" ? "income" : ""}`}>{brl(i.amount_cents)}</span>
                <div style={{ width: "100%", paddingLeft: 28 }}>
                  <CategorySelect categories={categories} kind={i.type === "income" ? "income" : "expense"} value={i.category_id ?? ""}
                    onChange={(v) => setItems(items.map((x, j) => (j === idx ? { ...x, category_id: v || null } : x)))} />
                </div>
              </li>
            ))}
          </ul>
          <div className="form-actions" style={{ marginTop: 12 }}>
            <Button variant="primary" loading={busy} onClick={confirm}>Importar {items.filter((i) => i.selected).length} selecionados</Button>
          </div>
        </Sheet>
      )}
    </div>
  );
}

function DataExport() {
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
      <a className="btn" href="/api/export/transactions.xlsx"><Download size={16} /> Excel</a>
      <a className="btn" href="/api/export/transactions.csv"><Download size={16} /> CSV</a>
      <a className="btn" href="/api/export/report.pdf"><Download size={16} /> Relatório do mês (PDF)</a>
      <a className="btn" href="/api/export/backup.json"><Download size={16} /> Backup completo (JSON)</a>
      <label className="btn" aria-busy={busy}>
        <Upload size={16} /> Restaurar backup
        <input type="file" accept="application/json,.json" hidden onChange={(e) => e.target.files?.[0] && restore(e.target.files[0])} />
      </label>
    </div>
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
        <Field label="Senha atual"><input className="input" type="password" autoComplete="current-password" value={current} onChange={(e) => setCurrent(e.target.value)} /></Field>
        <Field label="Nova senha" hint="Mínimo de 10 caracteres"><input className="input" type="password" autoComplete="new-password" value={next} onChange={(e) => setNext(e.target.value)} /></Field>
      </div>
      {error && <div className="alert danger">{error}</div>}
      <div className="form-actions"><Button type="submit" loading={saving}>Alterar senha</Button></div>
    </form>
  );
}

function DeleteAccount() {
  const [open, setOpen] = useState(false);
  const [password, setPassword] = useState("");
  const [confirmText, setConfirmText] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  async function submit(e: FormEvent) {
    e.preventDefault();
    setBusy(true);
    try {
      await api("/api/auth/delete-account", { body: { password, confirm: confirmText } });
      await clearLocalData();
      window.location.href = "/criar-conta";
    } catch (err) {
      setError(errorMessage(err));
      setBusy(false);
    }
  }
  return (
    <>
      <p className="small muted" style={{ marginBottom: 12 }}>Apaga definitivamente sua conta, lançamentos, documentos e histórico. Faça um backup antes.</p>
      <Button variant="danger" onClick={() => setOpen(true)}>Excluir minha conta</Button>
      {open && (
        <Sheet title="Excluir conta definitivamente" onClose={() => setOpen(false)}>
          <form className="form" onSubmit={submit}>
            <div className="alert danger">Isso não pode ser desfeito. Todos os seus dados serão apagados do servidor.</div>
            <Field label="Sua senha"><input className="input" type="password" value={password} onChange={(e) => setPassword(e.target.value)} required /></Field>
            <Field label='Digite EXCLUIR para confirmar'><input className="input" value={confirmText} onChange={(e) => setConfirmText(e.target.value)} required /></Field>
            {error && <div className="alert danger">{error}</div>}
            <div className="form-actions"><Button type="submit" variant="danger" loading={busy} disabled={confirmText !== "EXCLUIR"}>Excluir tudo</Button></div>
          </form>
        </Sheet>
      )}
    </>
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
              <div className="title" style={{ whiteSpace: "normal", fontWeight: 450 }}>{e.summary}</div>
              <div className="sub">{new Date(e.created_at).toLocaleString("pt-BR")}</div>
            </div>
          </li>
        ))}
      </ul>
      {!all && (data?.length ?? 0) > 8 && <Button size="small" variant="ghost" onClick={() => setAll(true)}>Ver mais</Button>}
    </>
  );
}

export default function Settings() {
  const me = useMe().data;
  const [theme, setThemeState] = useState<Theme>(getTheme());

  async function logout() {
    const pending = await pendingOutboxCount();
    if (pending && !window.confirm(`${pending} alteração(ões) feitas sem internet ainda não foram enviadas e serão perdidas ao sair. Sair mesmo assim?`)) return;
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
        <div><h1>Ajustes</h1><p>Perfil, segurança, IA, sincronização e seus dados</p></div>
        <Button onClick={logout}><LogOut size={16} /> Sair</Button>
      </div>

      <Section title="Perfil">{me && <Profile me={me} />}</Section>

      <Section title="Contas, cartões e categorias">
        <div className="chips">
          <Link className="btn small" to="/contas">Contas e cartões</Link>
          <Link className="btn small" to="/categorias">Categorias</Link>
          <Link className="btn small" to="/recorrentes">Fixas e recorrentes</Link>
          <Link className="btn small" to="/boas-vindas">Refazer configuração inicial</Link>
        </div>
      </Section>

      <Section title="Aparência">
        <div className="segmented" style={{ maxWidth: 360 }}>
          {([["system", "Automático"], ["light", "Claro"], ["dark", "Escuro"]] as [Theme, string][]).map(([t, l]) => (
            <button key={t} aria-pressed={theme === t} onClick={() => { setTheme(t); setThemeState(t); }}>{l}</button>
          ))}
        </div>
      </Section>

      <Section title="Notificações">{me && <Notifications me={me} />}</Section>

      <Section title="Inteligência artificial e privacidade">{me && <AISettings me={me} />}</Section>

      <Section id="sincronizacao" title="Sincronização"><SyncCenter /></Section>

      <Section title="Importar extrato do banco" hint="OFX (recomendado) ou CSV. Você revisa antes; importar de novo não duplica.">
        <StatementImport />
      </Section>

      <Section title="Exportar e fazer backup" hint="Seus dados são seus: exporte quando quiser."><DataExport /></Section>

      <Section title="Senha"><Password /></Section>

      <Section title="Histórico de alterações"><Audit /></Section>

      <Section title="Excluir conta"><DeleteAccount /></Section>
    </>
  );
}

export function More() {
  const shown = new Set(MOBILE_NAV.map((n) => n.to));
  const items = [...NAV.filter((n) => !shown.has(n.to)), { to: "/ajustes", label: "Ajustes", icon: NAV[0].icon }];
  return (
    <>
      <div className="page-head"><h1>Mais</h1></div>
      <nav className="panel" aria-label="Mais opções">
        <ul className="list">
          {items.map(({ to, label, icon: Icon }) => (
            <li key={to}>
              <Link to={to} className="row" style={{ textDecoration: "none" }}>
                <span className="cat-dot" aria-hidden="true"><Icon size={18} /></span>
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
