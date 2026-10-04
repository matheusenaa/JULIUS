import { createTransaction, deleteTransaction, flushOutbox, keepMine, localDb, updateTransaction } from "./offline";

const body = { type: "expense" as const, account_id: "a1", amount_cents: 1000, occurred_on: "2026-10-03", description: "Café" };
const tx = { id: "11111111-1111-1111-1111-111111111111", version: 3, description: "Café", amount_cents: 1000 };

function setOnline(value: boolean) {
  Object.defineProperty(navigator, "onLine", { configurable: true, get: () => value });
}

function mockFetch(handler: (url: string, init: RequestInit) => Response | Promise<Response>) {
  const calls: { url: string; method: string; body: unknown }[] = [];
  vi.stubGlobal("fetch", async (url: string, init: RequestInit = {}) => {
    calls.push({ url, method: init.method ?? "GET", body: init.body ? JSON.parse(String(init.body)) : undefined });
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

it("sem internet: guarda a criação com id gerado no aparelho", async () => {
  setOnline(false);
  const calls = mockFetch(() => json({}));
  const r = await createTransaction(body);
  expect(r.queued).toBe(true);
  expect(calls).toHaveLength(0);
  const [item] = await localDb.outbox.toArray();
  expect(item.op).toBe("create");
  expect(item.entityId).toMatch(/^[0-9a-f-]{36}$/);
  expect(item.status).toBe("pending");
});

it("falha de rede durante o envio também vai para a fila", async () => {
  setOnline(true);
  mockFetch(() => {
    throw new TypeError("Failed to fetch");
  });
  expect((await createTransaction(body)).queued).toBe(true);
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
  expect(posts.map((c) => (c.body as { id: string }).id)).toEqual(queued.map((q) => q.entityId));
  expect(await localDb.outbox.count()).toBe(0);
});

it("edição offline leva a versão em que foi feita", async () => {
  setOnline(false);
  await updateTransaction(tx, { amount_cents: 1500 });
  setOnline(true);
  const calls = mockFetch((url) => (url.includes("health") ? json({}) : json({ ...tx, version: 4 })));
  await flushOutbox();
  const patch = calls.find((c) => c.method === "PATCH")!;
  expect(patch.url).toBe(`/api/transactions/${tx.id}`);
  expect(patch.body).toEqual({ version: 3, amount_cents: 1500 });
});

it("conflito de versão: nada é sobrescrito e o usuário decide", async () => {
  setOnline(false);
  await updateTransaction(tx, { amount_cents: 1100 });
  setOnline(true);
  const server = { ...tx, version: 5, amount_cents: 1200 };
  mockFetch((url) =>
    url.includes("health") ? json({}) : json({ error: { code: "version_conflict", message: "Alterado em outro aparelho", details: { current: server } } }, 409),
  );
  await flushOutbox();
  const [item] = await localDb.outbox.toArray();
  expect(item.status).toBe("conflict");
  expect(item.server?.amount_cents).toBe(1200);

  const calls = mockFetch((url) => (url.includes("health") ? json({}) : json({ ...server, version: 6, amount_cents: 1100 })));
  await keepMine(item.id);
  const patch = calls.find((c) => c.method === "PATCH")!;
  expect(patch.body).toEqual({ version: 5, amount_cents: 1100 }); // reaplicada sobre a versão atual
  expect(await localDb.outbox.count()).toBe(0);
});

it("editar ou excluir algo ainda não enviado altera a própria fila", async () => {
  setOnline(false);
  const r = await createTransaction(body);
  const id = r.queued ? r.id : "";
  await updateTransaction({ id, version: 0, description: "Café", amount_cents: 1000 }, { amount_cents: 1800, description: "Café grande" });
  let items = await localDb.outbox.toArray();
  expect(items).toHaveLength(1);
  expect((items[0].body as { amount_cents: number }).amount_cents).toBe(1800);
  await deleteTransaction({ id, description: "Café grande", amount_cents: 1800 });
  items = await localDb.outbox.toArray();
  expect(items).toHaveLength(0); // nunca chegou ao servidor
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

it("se a conexão cair no meio, mantém o restante na fila como pendente", async () => {
  setOnline(false);
  await createTransaction(body);
  await deleteTransaction(tx);
  setOnline(true);
  mockFetch(() => {
    throw new TypeError("Failed to fetch");
  });
  expect(await flushOutbox()).toBe(0);
  const items = await localDb.outbox.toArray();
  expect(items.every((i) => i.status === "pending")).toBe(true);
});
