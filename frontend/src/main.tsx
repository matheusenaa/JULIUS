import "@fontsource-variable/inter";
import "@fontsource-variable/fraunces";
import "./styles/tokens.css";
import "./styles/base.css";
import "./styles/components.css";

import { createAsyncStoragePersister } from "@tanstack/query-async-storage-persister";
import { PersistQueryClientProvider } from "@tanstack/react-query-persist-client";
import { del, get, set } from "idb-keyval";
import { StrictMode } from "react";
import { createRoot } from "react-dom/client";
import { registerSW } from "virtual:pwa-register";

import App from "./App";
import { ToastProvider } from "./components/Toast";
import { queryClient } from "./lib/queries";
import { CACHE_KEY } from "./lib/session";
import { applyTheme } from "./lib/theme";

applyTheme();
registerSW({ immediate: true });

// Cache de leitura no IndexedDB: o app abre com os últimos dados mesmo sem internet
const persister = createAsyncStoragePersister({
  key: CACHE_KEY,
  storage: {
    getItem: (k) => get(k).catch(() => null),
    setItem: (k, v) => set(k, v).catch(() => undefined),
    removeItem: (k) => del(k).catch(() => undefined),
  },
});

createRoot(document.getElementById("root")!).render(
  <StrictMode>
    <PersistQueryClientProvider
      client={queryClient}
      persistOptions={{ persister, maxAge: 1000 * 60 * 60 * 24 * 7, buster: "v1" }}
      // O cache do aparelho só serve para abrir rápido/offline; o servidor sempre confirma em seguida
      onSuccess={() => queryClient.invalidateQueries()}
    >
      <ToastProvider>
        <App />
      </ToastProvider>
    </PersistQueryClientProvider>
  </StrictMode>,
);
