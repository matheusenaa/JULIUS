/**
 * Fila de lançamentos feitos sem internet (IndexedDB via Dexie).
 *
 * Cada lançamento recebe um UUID gerado no aparelho. O servidor trata esse id como
 * chave de idempotência: reenviar o mesmo item nunca duplica. Itens rejeitados pelo
 * servidor (ex.: conta excluída) ficam marcados como "falhou" para o usuário revisar —
 * nada é descartado silenciosamente.
 */
import Dexie, { liveQuery, type Table } from "dexie";
import { useEffect, useState } from "react";

import { api, ApiError } from "./api";
import type { Transaction, TransactionInput } from "./types";

export interface OutboxItem {
  id: string;
  body: TransactionInput & { id: string };
  createdAt: number;
  status: "pending" | "failed";
  error?: string;
}

class JuliusDB extends Dexie {
  outbox!: Table<OutboxItem, string>;
  constructor() {
    super("julius");
    this.version(1).stores({ outbox: "id, createdAt, status" });
  }
}

export const localDb = new JuliusDB();

function uuid(): string {
  return crypto.randomUUID();
}

export type CreateResult = { queued: false; tx: Transaction } | { queued: true; id: string };

/** Cria um lançamento; sem conexão, guarda na fila e sincroniza depois. */
export async function createTransaction(input: TransactionInput): Promise<CreateResult> {
  const body = { ...input, id: input.id ?? uuid() };
  if (navigator.onLine) {
    try {
      const tx = await api<Transaction>("/api/transactions", { body });
      return { queued: false, tx };
    } catch (err) {
      if (!(err instanceof ApiError && err.offline)) throw err;
    }
  }
  await localDb.outbox.put({ id: body.id, body, createdAt: Date.now(), status: "pending" });
  return { queued: true, id: body.id };
}

let flushing: Promise<number> | null = null;

/** Envia a fila em ordem. Retorna quantos itens foram sincronizados. */
export function flushOutbox(): Promise<number> {
  if (flushing) return flushing;
  flushing = (async () => {
    let sent = 0;
    const items = await localDb.outbox.where("status").equals("pending").sortBy("createdAt");
    for (const item of items) {
      try {
        await api("/api/transactions", { body: item.body });
        await localDb.outbox.delete(item.id);
        sent++;
      } catch (err) {
        if (err instanceof ApiError && (err.offline || err.status === 401 || err.status >= 500)) break;
        await localDb.outbox.update(item.id, {
          status: "failed",
          error: err instanceof ApiError ? err.message : "Erro desconhecido",
        });
      }
    }
    return sent;
  })().finally(() => {
    flushing = null;
  });
  return flushing;
}

export async function retryItem(id: string) {
  await localDb.outbox.update(id, { status: "pending", error: undefined });
  return flushOutbox();
}

export async function discardItem(id: string) {
  await localDb.outbox.delete(id);
}

export function useOutbox(): OutboxItem[] {
  const [items, setItems] = useState<OutboxItem[]>([]);
  useEffect(() => {
    const sub = liveQuery(() => localDb.outbox.orderBy("createdAt").toArray()).subscribe({
      next: setItems,
      error: () => setItems([]),
    });
    return () => sub.unsubscribe();
  }, []);
  return items;
}

export function useOnline(): boolean {
  const [online, setOnline] = useState(navigator.onLine);
  useEffect(() => {
    const on = () => setOnline(true);
    const off = () => setOnline(false);
    window.addEventListener("online", on);
    window.addEventListener("offline", off);
    return () => {
      window.removeEventListener("online", on);
      window.removeEventListener("offline", off);
    };
  }, []);
  return online;
}
