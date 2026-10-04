import { del } from "idb-keyval";

import { localDb } from "./offline";
import { queryClient } from "./queries";

export const CACHE_KEY = "julius-query-cache";

/** Ao sair: remove do aparelho o cache de dados financeiros e a fila offline. */
export async function clearLocalData() {
  queryClient.clear();
  await Promise.allSettled([del(CACHE_KEY), localDb.outbox.clear()]);
}

export async function pendingOutboxCount(): Promise<number> {
  return localDb.outbox.count().catch(() => 0);
}
