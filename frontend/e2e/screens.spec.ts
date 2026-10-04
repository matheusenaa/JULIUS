import { test } from "@playwright/test";

const OUT = process.env.SHOTS_DIR ?? "test-results/screens";

test("capturas de tela", async ({ page }, info) => {
  await page.goto("/criar-conta");
  await page.getByLabel("Seu nome").fill("Ana Teste");
  await page.getByLabel("E-mail").fill(`shot-${Date.now()}-${info.project.name}@teste.com`);
  await page.getByLabel("Senha").fill("senha-forte-123");
  await page.getByRole("button", { name: "Criar conta" }).click();
  await page.getByRole("heading", { name: "Olá, Ana" }).waitFor();

  const api = async (path: string, body: unknown) => {
    const csrf = (await page.context().cookies()).find((c) => c.name === "julius_csrf")!.value;
    const r = await page.request.post(path, { data: body, headers: { "X-CSRF-Token": csrf } });
    if (!r.ok()) throw new Error(`${path}: ${r.status()} ${await r.text()}`);
    return r.json();
  };
  const cats: { id: string; name: string }[] = await (await page.request.get("/api/categories")).json();
  const cat = (n: string) => cats.find((c) => c.name === n)!.id;
  const bank = await api("/api/accounts", { name: "Banco Inter", kind: "checking", initial_balance_cents: 250000 });
  await api("/api/accounts", { name: "Nubank", kind: "credit_card", credit_limit_cents: 500000, closing_day: 25, due_day: 5 });
  const d = (offset: number) => {
    const x = new Date();
    x.setDate(x.getDate() + offset);
    // data LOCAL (toISOString usaria UTC e viraria "amanhã" à noite no Brasil)
    return `${x.getFullYear()}-${String(x.getMonth() + 1).padStart(2, "0")}-${String(x.getDate()).padStart(2, "0")}`;
  };
  const tx = (description: string, cents: number, category: string, offset: number, type = "expense") =>
    api("/api/transactions", { type, account_id: bank.id, amount_cents: cents, occurred_on: d(offset), description, category_id: cat(category) });
  await tx("Salário", 520000, "Salário", -2, "income");
  await tx("Supermercado Extra", 38790, "Mercado", -1);
  await tx("Posto Shell", 15000, "Combustível", 0);
  await tx("Cinema", 6400, "Cinema", 0);
  await tx("Farmácia", 4590, "Farmácia", -1);
  await api("/api/recurrences", { type: "expense", account_id: bank.id, description: "Aluguel", amount_cents: 120000, start_date: d(-40), day_of_month: 10, category_id: cat("Aluguel") });
  await api("/api/recurrences", { type: "expense", account_id: bank.id, description: "Internet", amount_cents: 10000, start_date: d(-40), day_of_month: 15, category_id: cat("Internet") });
  await page.request.put("/api/budgets", {
    data: { category_id: cat("Alimentação"), amount_cents: 45000 },
    headers: { "X-CSRF-Token": (await page.context().cookies()).find((c) => c.name === "julius_csrf")!.value },
  });
  await api("/api/goals", { name: "Reserva de emergência", target_cents: 1500000, saved_cents: 420000, target_date: d(300) });

  for (const [name, path] of [
    ["inicio", "/"],
    ["lancamentos", "/lancamentos"],
    ["relatorios", "/relatorios"],
    ["contas", "/contas"],
    ["recorrentes", "/recorrentes"],
  ] as const) {
    await page.goto(path);
    await page.locator("h1").first().waitFor();
    await page.waitForTimeout(900);
    await page.screenshot({ path: `${OUT}/${info.project.name}-${name}.png`, fullPage: true });
  }
  await page.goto("/");
  await page.getByLabel("O que aconteceu?").first().fill("comprei uma camisa por 150");
  await page.getByRole("button", { name: "Interpretar" }).first().click();
  await page.getByText("Roupas").first().waitFor();
  await page.screenshot({ path: `${OUT}/${info.project.name}-quick.png` });
  await page.goto("/assistente");
  await page.getByLabel("Sua pergunta").fill("Quanto ainda posso gastar este mês?");
  await page.getByRole("button", { name: "Enviar" }).click();
  await page.getByText(/estimativa/i).first().waitFor();
  await page.screenshot({ path: `${OUT}/${info.project.name}-assistente.png` });
});
