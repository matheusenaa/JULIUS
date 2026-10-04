import { CalendarClock, FileText, LayoutDashboard, MessageCircle, Sparkles } from "lucide-react";
import { useState, type ReactNode } from "react";
import { useNavigate } from "react-router";

import { Mark, TAGLINE } from "../components/Brand";
import { Button, Field } from "../components/ui";
import { api, errorMessage } from "../lib/api";
import { parseMoney, setCurrency, todayIso } from "../lib/format";
import { invalidateFinance, queryClient, useCategories, useMe } from "../lib/queries";
import type { Account, User } from "../lib/types";

const STEPS = ["Moeda", "Conta", "Salário", "Categorias", "Objetivo", "Pronto"];

function Step({ title, text, children }: { title: string; text?: string; children: ReactNode }) {
  return (
    <div className="form">
      <h2>{title}</h2>
      {text && <p className="muted">{text}</p>}
      {children}
    </div>
  );
}

export default function Onboarding() {
  const navigate = useNavigate();
  const me = useMe().data;
  const categories = useCategories().data ?? [];
  const [step, setStep] = useState(0);
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const [currency, setCurrencyState] = useState(me?.settings.currency ?? "BRL");
  const [account, setAccount] = useState({ name: "Conta corrente", kind: "checking", balance: "" });
  const [accountId, setAccountId] = useState<string | null>(null);
  const [salary, setSalary] = useState({ amount: "", day: "5" });
  const [goal, setGoal] = useState({ name: "Reserva de emergência", amount: "", date: "" });

  async function next(action?: () => Promise<unknown>) {
    setError(null);
    if (action) {
      setBusy(true);
      try {
        await action();
      } catch (err) {
        setError(errorMessage(err));
        setBusy(false);
        return;
      }
      setBusy(false);
    }
    setStep((s) => s + 1);
  }

  async function finish() {
    const user = await api<User>("/api/auth/me", { method: "PATCH", body: { onboarded: true } });
    queryClient.setQueryData(["me"], user);
    invalidateFinance();
    navigate("/", { replace: true });
  }

  const parents = categories.filter((c) => c.kind === "expense" && !c.parent_id);

  return (
    <main className="auth">
      <div className="auth-card" style={{ width: "min(100%, 480px)" }}>
        <div style={{ display: "flex", alignItems: "center", gap: 10 }}>
          <Mark size={34} />
          <span className="muted small" style={{ flex: 1 }}>{TAGLINE}</span>
          {step < STEPS.length - 1 && (
            <button className="link" style={{ background: "none", border: 0, cursor: "pointer" }} onClick={finish}>
              Pular configuração
            </button>
          )}
        </div>
        <div className="steps" aria-label={`Passo ${step + 1} de ${STEPS.length}`}>
          {STEPS.map((s, i) => <i key={s} className={i <= step ? "done" : ""} title={s} />)}
        </div>

        {step === 0 && (
          <Step title={`Bem-vindo${me ? `, ${me.name.split(" ")[0]}` : ""}!`} text="Em 1 minuto o JULIUS fica pronto. Tudo pode ser alterado depois.">
            <Field label="Em que moeda você controla seu dinheiro?">
              <select className="select" value={currency} onChange={(e) => setCurrencyState(e.target.value as typeof currency)}>
                <option value="BRL">Real (R$)</option>
                <option value="USD">Dólar (US$)</option>
                <option value="EUR">Euro (€)</option>
              </select>
            </Field>
            <Button variant="primary" block loading={busy} onClick={() => next(async () => { await api("/api/auth/me", { method: "PATCH", body: { currency } }); setCurrency(currency); })}>Continuar</Button>
          </Step>
        )}

        {step === 1 && (
          <Step title="Sua conta principal" text="Onde seu dinheiro fica hoje e quanto tem nela agora. Você pode cadastrar outras contas e cartões depois.">
            <div className="form-row">
              <Field label="Nome"><input className="input" value={account.name} onChange={(e) => setAccount({ ...account, name: e.target.value })} /></Field>
              <Field label="Tipo">
                <select className="select" value={account.kind} onChange={(e) => setAccount({ ...account, kind: e.target.value })}>
                  <option value="checking">Conta corrente</option>
                  <option value="savings">Poupança</option>
                  <option value="wallet">Carteira digital</option>
                  <option value="cash">Dinheiro</option>
                </select>
              </Field>
            </div>
            <Field label="Saldo de hoje" hint="Use “-” se estiver negativo.">
              <input className="input num" inputMode="decimal" placeholder="0,00" value={account.balance} onChange={(e) => setAccount({ ...account, balance: e.target.value })} />
            </Field>
            <Button variant="primary" block loading={busy} onClick={() => next(async () => {
              const neg = account.balance.trim().startsWith("-");
              const cents = account.balance.trim() ? parseMoney(account.balance.replace("-", "")) : 0;
              if (cents === null) throw new Error("Saldo inválido. Ex.: 1.500,00");
              const acc = await api<Account>("/api/accounts", { body: { name: account.name.trim() || "Conta", kind: account.kind, initial_balance_cents: neg ? -cents : cents } });
              setAccountId(acc.id);
              await api("/api/auth/me", { method: "PATCH", body: { default_account_id: acc.id } });
            })}>Salvar e continuar</Button>
          </Step>
        )}

        {step === 2 && (
          <Step title="Você recebe salário?" text="O JULIUS mostra quando ele vai entrar e quanto sobra depois das contas. Ele só conta como recebido quando você confirmar.">
            <div className="form-row">
              <Field label="Valor líquido"><input className="input num" inputMode="decimal" placeholder="0,00" value={salary.amount} onChange={(e) => setSalary({ ...salary, amount: e.target.value })} /></Field>
              <Field label="Todo dia"><input className="input" type="number" min={1} max={31} value={salary.day} onChange={(e) => setSalary({ ...salary, day: e.target.value })} /></Field>
            </div>
            <div className="form-actions">
              <Button variant="ghost" onClick={() => next()}>Pular</Button>
              <Button variant="primary" loading={busy} onClick={() => next(async () => {
                const cents = parseMoney(salary.amount);
                if (!cents) throw new Error("Informe o valor ou toque em Pular.");
                const day = Math.min(31, Math.max(1, Number(salary.day) || 5));
                const now = new Date();
                const start = new Date(now.getFullYear(), now.getMonth() + (now.getDate() > day ? 1 : 0), Math.min(day, 28));
                await api("/api/recurrences", { body: {
                  type: "income", account_id: accountId, description: "Salário", amount_cents: cents, frequency: "monthly", day_of_month: day,
                  start_date: `${start.getFullYear()}-${String(start.getMonth() + 1).padStart(2, "0")}-${String(start.getDate()).padStart(2, "0")}`,
                  category_id: categories.find((c) => c.name === "Salário")?.id ?? null, is_fixed: true,
                } });
              })}>Salvar</Button>
            </div>
          </Step>
        )}

        {step === 3 && (
          <Step title="Suas categorias" text="Já criamos categorias comuns. Dá para renomear, apagar e criar as suas em Categorias — e o JULIUS aprende com suas correções.">
            <div className="chips">{parents.map((c) => <span key={c.id} className="chip" aria-pressed="false">{c.name}</span>)}</div>
            <Button variant="primary" block onClick={() => next()}>Está bom assim</Button>
          </Step>
        )}

        {step === 4 && (
          <Step title="Um objetivo?" text="Ex.: reserva de emergência, viagem, trocar de carro. O JULIUS mostra quanto guardar por mês.">
            <Field label="Nome"><input className="input" value={goal.name} onChange={(e) => setGoal({ ...goal, name: e.target.value })} /></Field>
            <div className="form-row">
              <Field label="Quero juntar"><input className="input num" inputMode="decimal" placeholder="0,00" value={goal.amount} onChange={(e) => setGoal({ ...goal, amount: e.target.value })} /></Field>
              <Field label="Até"><input className="input" type="date" min={todayIso()} value={goal.date} onChange={(e) => setGoal({ ...goal, date: e.target.value })} /></Field>
            </div>
            <div className="form-actions">
              <Button variant="ghost" onClick={() => next()}>Pular</Button>
              <Button variant="primary" loading={busy} onClick={() => next(async () => {
                const cents = parseMoney(goal.amount);
                if (!cents) throw new Error("Informe o valor ou toque em Pular.");
                await api("/api/goals", { body: { name: goal.name.trim() || "Meta", target_cents: cents, target_date: goal.date || null } });
              })}>Salvar</Button>
            </div>
          </Step>
        )}

        {step === 5 && (
          <Step title="Pronto! Conheça o JULIUS">
            <ul className="list">
              {[
                [Sparkles, "Início", "Escreva “gastei 45 no mercado” e confirme. Simples assim."],
                [LayoutDashboard, "Visão geral", "Saldo, gráficos, calendário e como estará seu dinheiro nos próximos dias."],
                [CalendarClock, "Futuros", "Salário, contas e parcelas — com o saldo depois de cada um."],
                [FileText, "Documentos", "Foto ou PDF de uma conta: o JULIUS lê e você confirma."],
                [MessageCircle, "Assistente", "“Quanto vou gastar até o fim do mês?” — respostas com seus dados reais."],
              ].map(([Icon, title, text]) => {
                const I = Icon as typeof Sparkles;
                return (
                  <li key={title as string} className="row">
                    <span className="cat-dot" aria-hidden="true"><I size={18} /></span>
                    <div className="main-col"><div className="title">{title as string}</div><div className="sub" style={{ whiteSpace: "normal" }}>{text as string}</div></div>
                  </li>
                );
              })}
            </ul>
            <Button variant="accent" block onClick={finish}>Começar a usar</Button>
          </Step>
        )}

        {error && <div className="alert danger" role="alert">{error}</div>}
      </div>
    </main>
  );
}
