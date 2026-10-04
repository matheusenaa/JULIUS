import { useIsRestoring } from "@tanstack/react-query";
import { lazy, Suspense, useEffect, type ReactNode } from "react";
import { createBrowserRouter, Navigate, RouterProvider, useLocation, useRouteError } from "react-router";

import { AppShell } from "./components/AppShell";
import { Splash } from "./components/Brand";
import { ErrorState, Skeleton } from "./components/ui";
import { errorMessage } from "./lib/api";
import { queryClient, useMe } from "./lib/queries";
import { Login, Register } from "./pages/Auth";
import Dashboard from "./pages/Dashboard";

// Páginas menos usadas carregam sob demanda (abre mais rápido no celular)
const Transactions = lazy(() => import("./pages/Transactions"));
const Reports = lazy(() => import("./pages/Reports"));
const Assistant = lazy(() => import("./pages/Assistant"));
const Accounts = lazy(() => import("./pages/Accounts"));
const Recurrences = lazy(() => import("./pages/Recurrences"));
const Planning = lazy(() => import("./pages/Planning"));
const Categories = lazy(() => import("./pages/Categories"));
const Settings = lazy(() => import("./pages/Settings"));
const More = lazy(() => import("./pages/Settings").then((m) => ({ default: m.More })));
const Overview = lazy(() => import("./pages/Overview"));
const Futures = lazy(() => import("./pages/Futures"));
const Debts = lazy(() => import("./pages/Debts"));
const Documents = lazy(() => import("./pages/Documents"));
const Onboarding = lazy(() => import("./pages/Onboarding"));

function RequireAuth({ children }: { children: ReactNode }) {
  const { data: me, isLoading, isFetching, error, refetch } = useMe();
  const restoring = useIsRestoring();
  const location = useLocation();
  useEffect(() => {
    const onUnauthorized = () => queryClient.setQueryData(["me"], null);
    window.addEventListener("julius:unauthorized", onUnauthorized);
    return () => window.removeEventListener("julius:unauthorized", onUnauthorized);
  }, []);
  if (restoring || isLoading) return <Splash />;
  // Sem conexão mas com sessão em cache: segue usando o app offline
  if (error && me === undefined) return <ErrorState message={errorMessage(error)} onRetry={() => refetch()} />;
  // Cache local diz "deslogado", mas o servidor ainda está confirmando: espera antes de redirecionar
  if (!me && isFetching) return <Splash />;
  if (!me) return <Navigate to="/entrar" replace state={{ from: location.pathname + location.search }} />;
  return <>{children}</>;
}

function RedirectIfAuthed({ children }: { children: ReactNode }) {
  const { data: me, isLoading } = useMe();
  const restoring = useIsRestoring();
  const from = (useLocation().state as { from?: string } | null)?.from ?? "/";
  if (restoring || isLoading) return <Splash />;
  // Conta recém-criada vai para a configuração inicial; contas antigas não têm a marca e seguem direto
  if (me) return <Navigate to={me.settings.onboarded === false ? "/boas-vindas" : from} replace />;
  return <>{children}</>;
}

function RouteError() {
  const err = useRouteError();
  return (
    <main className="main">
      <ErrorState message={err instanceof Error ? "Ocorreu um erro inesperado nesta tela." : errorMessage(err)} onRetry={() => window.location.reload()} />
    </main>
  );
}

const page = (el: ReactNode) => <Suspense fallback={<Skeleton lines={5} />}>{el}</Suspense>;

const router = createBrowserRouter([
  { path: "/entrar", element: <RedirectIfAuthed><Login /></RedirectIfAuthed> },
  { path: "/criar-conta", element: <RedirectIfAuthed><Register /></RedirectIfAuthed> },
  { path: "/boas-vindas", element: <RequireAuth>{page(<Onboarding />)}</RequireAuth> },
  {
    path: "/",
    element: <RequireAuth><AppShell /></RequireAuth>,
    errorElement: <RouteError />,
    children: [
      { index: true, element: <Dashboard /> },
      { path: "visao-geral", element: page(<Overview />) },
      { path: "futuros", element: page(<Futures />) },
      { path: "dividas", element: page(<Debts />) },
      { path: "documentos", element: page(<Documents />) },
      { path: "lancamentos", element: page(<Transactions />) },
      { path: "relatorios", element: page(<Reports />) },
      { path: "assistente", element: page(<Assistant />) },
      { path: "contas", element: page(<Accounts />) },
      { path: "recorrentes", element: page(<Recurrences />) },
      { path: "planejamento", element: page(<Planning />) },
      { path: "categorias", element: page(<Categories />) },
      { path: "ajustes", element: page(<Settings />) },
      { path: "mais", element: page(<More />) },
      { path: "*", element: <Navigate to="/" replace /> },
    ],
  },
]);

export default function App() {
  return <RouterProvider router={router} />;
}
