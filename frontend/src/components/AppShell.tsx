import {
  ChartColumn,
  CloudUpload,
  CreditCard,
  Ellipsis,
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

import { flushOutbox, useOnline, useOutbox } from "../lib/offline";
import { invalidateFinance, useAccounts, useCategories } from "../lib/queries";
import { NewEntrySheet } from "./NewEntry";
import { useToast } from "./Toast";
import { Button, Logo } from "./ui";

const NAV = [
  { to: "/", label: "Início", icon: LayoutDashboard, end: true },
  { to: "/lancamentos", label: "Lançamentos", icon: ListOrdered },
  { to: "/relatorios", label: "Relatórios", icon: ChartColumn },
  { to: "/assistente", label: "Assistente", icon: MessageCircle },
  { to: "/contas", label: "Contas e cartões", icon: CreditCard },
  { to: "/recorrentes", label: "Fixas e recorrentes", icon: Repeat },
  { to: "/planejamento", label: "Orçamentos e metas", icon: Target },
  { to: "/categorias", label: "Categorias", icon: Tags },
];

const MOBILE_NAV = [
  { to: "/", label: "Início", icon: LayoutDashboard, end: true },
  { to: "/lancamentos", label: "Lançamentos", icon: ListOrdered },
  { to: "/relatorios", label: "Relatórios", icon: ChartColumn },
  { to: "/assistente", label: "Assistente", icon: MessageCircle },
  { to: "/mais", label: "Mais", icon: Ellipsis },
];

export { NAV };

export function AppShell() {
  const [entryOpen, setEntryOpen] = useState(false);
  const { pathname } = useLocation();
  const online = useOnline();
  const outbox = useOutbox();
  const toast = useToast();
  const pending = outbox.filter((i) => i.status === "pending").length;
  const failed = outbox.filter((i) => i.status === "failed").length;

  // Contas e categorias ficam sempre em cache: são necessárias para lançar mesmo sem internet
  useAccounts();
  useCategories();

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
        {NAV.map(({ to, label, icon: Icon, end }) => (
          <NavLink key={to} to={to} end={end}>
            <Icon size={18} /> {label}
          </NavLink>
        ))}
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
