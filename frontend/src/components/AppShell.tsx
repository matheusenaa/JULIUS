import {
  CalendarClock,
  ChartColumn,
  CloudUpload,
  CreditCard,
  Ellipsis,
  FileText,
  HandCoins,
  House,
  LayoutDashboard,
  ListOrdered,
  MessageCircle,
  Plus,
  Repeat,
  Settings,
  Tags,
  Target,
  WifiOff,
} from "lucide-react";
import { useEffect, useState } from "react";
import { NavLink, Outlet, useLocation } from "react-router";

import { api } from "../lib/api";
import { brl, setCurrency, todayIso } from "../lib/format";
import { flushOutbox, useOnline, useOutbox } from "../lib/offline";
import { invalidateFinance, useAccounts, useCategories, useMe } from "../lib/queries";
import type { Timeline } from "../lib/types";
import { NewEntrySheet } from "./NewEntry";
import { useToast } from "./Toast";
import { Button, Logo } from "./ui";

type NavItem = { to: string; label: string; icon: typeof House; end?: boolean };

const NAV_GROUPS: { title: string; items: NavItem[] }[] = [
  {
    title: "Dia a dia",
    items: [
      { to: "/", label: "Início", icon: House, end: true },
      { to: "/visao-geral", label: "Visão geral", icon: LayoutDashboard },
      { to: "/lancamentos", label: "Lançamentos", icon: ListOrdered },
      { to: "/futuros", label: "Futuros", icon: CalendarClock },
      { to: "/assistente", label: "Assistente", icon: MessageCircle },
    ],
  },
  {
    title: "Organizar",
    items: [
      { to: "/contas", label: "Contas e cartões", icon: CreditCard },
      { to: "/dividas", label: "Dívidas", icon: HandCoins },
      { to: "/documentos", label: "Documentos", icon: FileText },
      { to: "/recorrentes", label: "Fixas e recorrentes", icon: Repeat },
      { to: "/planejamento", label: "Orçamentos e metas", icon: Target },
      { to: "/relatorios", label: "Relatórios", icon: ChartColumn },
      { to: "/categorias", label: "Categorias", icon: Tags },
    ],
  },
];
const NAV = NAV_GROUPS.flatMap((g) => g.items);

const MOBILE_NAV: NavItem[] = [
  { to: "/", label: "Início", icon: House, end: true },
  { to: "/visao-geral", label: "Visão", icon: LayoutDashboard },
  { to: "/futuros", label: "Futuros", icon: CalendarClock },
  { to: "/assistente", label: "Assistente", icon: MessageCircle },
  { to: "/mais", label: "Mais", icon: Ellipsis },
];

export { MOBILE_NAV, NAV };

export function AppShell() {
  const [entryOpen, setEntryOpen] = useState(false);
  const { pathname } = useLocation();
  const online = useOnline();
  const outbox = useOutbox();
  const toast = useToast();
  const pending = outbox.filter((i) => i.status === "pending" || i.status === "syncing").length;
  const failed = outbox.filter((i) => i.status === "failed" || i.status === "conflict").length;
  const me = useMe().data;

  // Contas e categorias ficam sempre em cache: são necessárias para lançar mesmo sem internet
  useAccounts();
  useCategories();

  useEffect(() => setCurrency(me?.settings.currency), [me?.settings.currency]);

  // Aviso do sistema (uma vez por dia) sobre contas que vencem hoje/amanhã, se o usuário ativou
  useEffect(() => {
    if (!me?.settings.notify_due || !online || !("Notification" in window) || Notification.permission !== "granted") return;
    let key = "";
    try {
      key = `julius-notified-${todayIso()}`;
      if (localStorage.getItem(key)) return;
    } catch {
      return;
    }
    api<Timeline>("/api/timeline?days=1")
      .then((tl) => {
        const due = tl.events.filter((e) => e.flow === "out" && e.status !== "scheduled");
        if (!due.length) return;
        const total = due.reduce((s, e) => s + e.amount_cents, 0);
        new Notification("JULIUS — contas a pagar", {
          body: `${due.length} conta(s) até amanhã: ${brl(total)}. ${due[0].description}${due.length > 1 ? " e outras" : ""}.`,
          icon: "/pwa-192x192.png",
        });
        try {
          localStorage.setItem(key, "1");
        } catch {
          /* sem armazenamento: pode avisar de novo */
        }
      })
      .catch(() => undefined);
  }, [me?.settings.notify_due, online]);

  // Sincroniza a fila offline ao abrir, ao reconectar e a cada 30 s
  useEffect(() => {
    if (!online) return;
    const sync = () =>
      flushOutbox().then((n) => {
        if (n > 0) {
          invalidateFinance();
          toast(`${n} lançamento(s) feitos offline foram sincronizados.`);
        }
      });
    sync();
    const timer = setInterval(sync, 30_000);
    return () => clearInterval(timer);
  }, [online, toast]);

  const syncBadge = (pending > 0 || failed > 0) && (
    <NavLink to="/ajustes#sincronizacao" className="badge warn" title="Lançamentos aguardando sincronização">
      <CloudUpload size={13} /> {pending + failed} {failed ? "com erro" : "na fila"}
    </NavLink>
  );

  return (
    <div className="shell">
      <aside className="sidebar" aria-label="Navegação principal">
        <div className="logo">
          <Logo />
        </div>
        <Button variant="accent" block onClick={() => setEntryOpen(true)} style={{ marginBottom: 16 }}>
          <Plus size={18} /> Novo lançamento
        </Button>
        <nav className="nav-scroll">
          {NAV_GROUPS.map((group) => (
            <div key={group.title}>
              <div className="nav-title">{group.title}</div>
              {group.items.map(({ to, label, icon: Icon, end }) => (
                <NavLink key={to} to={to} end={end}>
                  <Icon size={18} /> {label}
                </NavLink>
              ))}
            </div>
          ))}
        </nav>
        <div className="grow" />
        <NavLink to="/ajustes">
          <Settings size={18} /> Ajustes
        </NavLink>
      </aside>

      <div>
        {!online && (
          <div className="offline-bar" role="status">
            <WifiOff size={15} /> Sem internet. Você pode continuar lançando; tudo será sincronizado depois.
          </div>
        )}
        <header className="topbar">
          <Logo />
          {syncBadge}
        </header>
        <main className="main">
          <Outlet context={{ openEntry: () => setEntryOpen(true) }} />
        </main>
      </div>

      {/* No assistente o campo de pergunta ocupa a base da tela; o botão flutuante atrapalharia */}
      {pathname !== "/assistente" && (
        <button className="fab" onClick={() => setEntryOpen(true)} aria-label="Novo lançamento">
          <Plus size={26} />
        </button>
      )}
      <nav className="bottom-nav" aria-label="Navegação">
        {MOBILE_NAV.map(({ to, label, icon: Icon, end }) => (
          <NavLink key={to} to={to} end={end}>
            <Icon size={21} />
            {label}
          </NavLink>
        ))}
      </nav>

      {entryOpen && <NewEntrySheet onClose={() => setEntryOpen(false)} />}
    </div>
  );
}
