/**
 * Fila de alterações feitas sem internet (IndexedDB via Dexie).
 *
 * Estados: pending → syncing → (removido = sincronizado)
 *          failed  → (retry) → pending
 *          conflict: o lançamento mudou em outro aparelho; o usuário escolhe a versão.
 *
 * Criações usam UUID gerado no aparelho (o servidor nunca duplica um reenvio).
 * Edições levam a versão em que foram feitas: se o servidor tiver outra, é conflito —
 * nada é sobrescrito em silêncio.
 */
import Dexie, { liveQuery, type Table } from "dexie";
import { useEffect, useState } from "react";

import { api, ApiError } from "./api";
import type { Transaction, TransactionInput } from "./types";

export type OutboxOp = "create" | "update" | "delete";
export type OutboxStatus = "pending" | "syncing" | "failed" | "conflict";

export interface OutboxItem {
  id: string; // id do item na fila
  op: OutboxOp;
  entityId: string; // id do lançamento
  body: (TransactionInput & { id?: string }) | Record<string, unknown>;
  baseVersion?: number;
  label: string;
  amountCents?: number;
  createdAt: number;
  status: OutboxStatus;
  error?: string;
  server?: Transaction; // versão do servidor em caso de conflito
  attempts: number;
}

class JuliusDB extends Dexie {
  outbox!: Table<OutboxItem, string>;
  constructor() {
    super("julius");
    this.version(1).stores({ outbox: "id, createdAt, status" });
    // v2: fila passa a ter edições/exclusões. Itens antigos eram sempre criações.
    this.version(2)
      .stores({ outbox: "id, createdAt, status, entityId" })
      .upgrade((tx) =>
        tx.table("outbox").toCollection().modify((item: Record<string, unknown>) => {
          const body = item.body as { id: string; description?: string; amount_cents?: number };
          item.op = "create";
          item.entityId = body.id;
          item.label = body.description ?? "Lançamento";
          item.amountCents = body.amount_cents;
          item.attempts = 0;
        }),
      );
  }
}

export const localDb = new JuliusDB();

const uuid = () => crypto.randomUUID();
const isOffline = (err: unknown) => err instanceof ApiError && err.offline;

export type CreateResult = { queued: false; tx: Transaction } | { queued: true; id: string };

/** Cria um lançamento; sem conexão, guarda na fila e sincroniza depois. */
export async function createTransaction(input: TransactionInput): Promise<CreateResult> {
  const body = { ...input, id: input.id ?? uuid() };
  if (navigator.onLine) {
    try {
      return { queued: false, tx: await api<Transaction>("/api/transactions", { body }) };
    } catch (err) {
      if (!isOffline(err)) throw err;
    }
  }
  await localDb.outbox.put({
    id: body.id, op: "create", entityId: body.id, body, label: body.description, amountCents: body.amount_cents,
    createdAt: Date.now(), status: "pending", attempts: 0,
  });
  return { queued: true, id: body.id };
}

/** Edita; sem conexão, guarda a alteração com a versão em que foi feita. */
export async function updateTransaction(
  tx: Pick<Transaction, "id" | "version" | "description" | "amount_cents">,
  changes: Record<string, unknown>,
): Promise<{ queued: boolean; tx?: Transaction }> {
  if (navigator.onLine) {
    try {
      return { queued: false, tx: await api<Transaction>(`/api/transactions/${tx.id}`, { method: "PATCH", body: { version: tx.version, ...changes } }) };
    } catch (err) {
      if (!isOffline(err)) throw err;
    }
  }
  // Ainda não enviado? Junta a edição à criação pendente (um único envio)
  const pendingCreate = await localDb.outbox.where("entityId").equals(tx.id).filter((i) => i.op === "create").first();
  if (pendingCreate) {
    await localDb.outbox.update(pendingCreate.id, { body: { ...pendingCreate.body, ...changes }, label: String(changes.description ?? pendingCreate.label) });
    return { queued: true };
  }
  await localDb.outbox.put({
    id: uuid(), op: "update", entityId: tx.id, body: changes, baseVersion: tx.version, label: tx.description,
    amountCents: (changes.amount_cents as number) ?? tx.amount_cents, createdAt: Date.now(), status: "pending", attempts: 0,
  });
  return { queued: true };
}

export async function deleteTransaction(tx: Pick<Transaction, "id" | "description" | "amount_cents">, scope = "one") {
  if (navigator.onLine) {
    try {
      await api(`/api/transactions/${tx.id}?scope=${scope}`, { method: "DELETE" });
      return { queued: false };
    } catch (err) {
      if (!isOffline(err)) throw err;
    }
  }
  const pendingCreate = await localDb.outbox.where("entityId").equals(tx.id).filter((i) => i.op === "create").first();
  if (pendingCreate) {
    await localDb.outbox.delete(pendingCreate.id); // nunca chegou ao servidor: basta descartar
    return { queued: true };
  }
  await localDb.outbox.put({
    id: uuid(), op: "delete", entityId: tx.id, body: { scope }, label: tx.description, amountCents: tx.amount_cents,
    createdAt: Date.now(), status: "pending", attempts: 0,
  });
  return { queued: true };
}

async function send(item: OutboxItem) {
  if (item.op === "create") return api("/api/transactions", { body: item.body });
  if (item.op === "update")
    return api(`/api/transactions/${item.entityId}`, { method: "PATCH", body: { version: item.baseVersion, ...item.body } });
  return api(`/api/transactions/${item.entityId}?scope=${(item.body as { scope?: string }).scope ?? "one"}`, { method: "DELETE" });
}

let flushing: Promise<number> | null = null;

/** Envia a fila em ordem. Retorna quantos itens foram sincronizados. */
export function flushOutbox(): Promise<number> {
  if (flushing) return flushing;
  flushing = (async () => {
    let sent = 0;
    const items = await localDb.outbox.where("status").equals("pending").sortBy("createdAt");
    for (const item of items) {
      await localDb.outbox.update(item.id, { status: "syncing" });
      try {
        await send(item);
        await localDb.outbox.delete(item.id); // sincronizado
        sent++;
      } catch (err) {
        const e = err instanceof ApiError ? err : null;
        if (!e || e.offline || e.status === 401 || e.status >= 500) {
          await localDb.outbox.update(item.id, { status: "pending", attempts: item.attempts + 1 });
          break; // sem conexão: tenta tudo de novo depois, na mesma ordem
        }
        if (e.code === "version_conflict") {
          const server = (e.details as { current?: Transaction } | undefined)?.current;
          await localDb.outbox.update(item.id, { status: "conflict", server, error: e.message });
        } else if (e.status === 404 && item.op === "delete") {
          await localDb.outbox.delete(item.id); // já não existia: objetivo atingido
        } else {
          await localDb.outbox.update(item.id, { status: "failed", error: e.message, attempts: item.attempts + 1 });
        }
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

/** Conflito: manter a minha alteração (reaplica sobre a versão atual do servidor). */
export async function keepMine(id: string) {
  const item = await localDb.outbox.get(id);
  if (!item?.server) return;
  await localDb.outbox.update(id, { status: "pending", baseVersion: item.server.version, server: undefined, error: undefined });
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
