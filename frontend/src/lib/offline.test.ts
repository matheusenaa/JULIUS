import { createTransaction, flushOutbox, localDb } from "./offline";

const body = { type: "expense" as const, account_id: "a1", amount_cents: 1000, occurred_on: "2026-10-03", description: "Café" };

function setOnline(value: boolean) {
  Object.defineProperty(navigator, "onLine", { configurable: true, get: () => value });
}

function mockFetch(handler: (url: string, init: RequestInit) => Response | Promise<Response>) {
  const calls: { url: string; body: unknown }[] = [];
  vi.stubGlobal("fetch", async (url: string, init: RequestInit = {}) => {
    calls.push({ url, body: init.body ? JSON.parse(String(init.body)) : undefined });
    return handler(url, init);
  });
  return calls;
}

const json = (data: unknown, status = 200) =>
  new Response(JSON.stringify(data), { status, headers: { "content-type": "application/json" } });

beforeEach(async () => {
  await localDb.outbox.clear();
  document.cookie = "julius_csrf=tok";
  vi.unstubAllGlobals();
});

it("sem internet: guarda na fila com id gerado no aparelho", async () => {
  setOnline(false);
  const calls = mockFetch(() => json({}));
  const r = await createTransaction(body);
  expect(r.queued).toBe(true);
  expect(calls).toHaveLength(0);
  const items = await localDb.outbox.toArray();
  expect(items).toHaveLength(1);
  expect(items[0].body.id).toMatch(/^[0-9a-f-]{36}$/);
});

it("falha de rede durante o envio também vai para a fila", async () => {
  setOnline(true);
  mockFetch(() => {
    throw new TypeError("Failed to fetch");
  });
  const r = await createTransaction(body);
  expect(r.queued).toBe(true);
  expect(await localDb.outbox.count()).toBe(1);
});

it("sincroniza em ordem e reenvia o MESMO id (idempotente)", async () => {
  setOnline(false);
  await createTransaction({ ...body, description: "primeiro" });
  await createTransaction({ ...body, description: "segundo" });
  const queued = await localDb.outbox.orderBy("createdAt").toArray();
  setOnline(true);
  const calls = mockFetch((url) => (url.includes("health") ? json({}) : json({ id: "x" }, 201)));
  expect(await flushOutbox()).toBe(2);
  const posts = calls.filter((c) => c.url === "/api/transactions");
  expect(posts.map((c) => (c.body as { description: string }).description)).toEqual(["primeiro", "segundo"]);
  expect(posts.map((c) => (c.body as { id: string }).id)).toEqual(queued.map((q) => q.id));
  expect(await localDb.outbox.count()).toBe(0);
});

it("item recusado pelo servidor fica marcado, nunca descartado", async () => {
  setOnline(false);
  await createTransaction(body);
  setOnline(true);
  mockFetch(() => json({ error: { code: "not_found", message: "Conta não encontrada(a)." } }, 404));
  expect(await flushOutbox()).toBe(0);
  const [item] = await localDb.outbox.toArray();
  expect(item.status).toBe("failed");
  expect(item.error).toContain("Conta");
});

it("se a conexão cair no meio, para e mantém o restante na fila", async () => {
  setOnline(false);
  await createTransaction(body);
  await createTransaction(body);
  setOnline(true);
  mockFetch(() => {
    throw new TypeError("Failed to fetch");
  });
  expect(await flushOutbox()).toBe(0);
  const items = await localDb.outbox.toArray();
  expect(items.every((i) => i.status === "pending")).toBe(true);
});
