import { expect, test } from "@playwright/test";

import { register, trackConsole } from "./helpers";

test("cadastro, quick input, saldo e histórico", async ({ page }) => {
  const errors = trackConsole(page);
  await register(page);

  const quick = page.getByLabel("O que aconteceu?").first();
  await quick.fill("recebi meu salário de 3200");
  await page.getByRole("button", { name: "Interpretar" }).first().click();
  await expect(page.getByText("R$ 3.200,00").first()).toBeVisible();
  await page.getByRole("button", { name: "Confirmar" }).click();
  await expect(page.getByText("Lançamento registrado.")).toBeVisible();

  await quick.fill("gastei 45 reais no mercado");
  await page.getByRole("button", { name: "Interpretar" }).first().click();
  await expect(page.getByText("Alimentação › Mercado")).toBeVisible();
  await page.getByRole("button", { name: "Confirmar" }).click();

  // Saldo calculado pelo backend: 3200 − 45
  await expect(page.locator(".hero .big")).toHaveText(/3\.155,00/);
  await expect(page.getByRole("button", { name: /Editar Mercado/ })).toBeVisible();

  await page.goto("/lancamentos");
  await expect(page.getByRole("button", { name: /Editar Mercado/ })).toBeVisible();
  await page.getByLabel("Buscar na descrição").fill("salário");
  await page.getByLabel("Buscar na descrição").press("Enter");
  await expect(page.getByText("1 lançamentos").or(page.getByRole("button", { name: /Editar Salário/ }))).toBeVisible();
  await expect(page.getByRole("button", { name: /Editar Mercado/ })).toHaveCount(0);

  for (const path of ["/relatorios", "/assistente", "/contas", "/recorrentes", "/planejamento", "/categorias", "/ajustes"]) {
    await page.goto(path);
    await expect(page.locator("h1")).toBeVisible();
  }
  expect(errors).toEqual([]);
});

test("compra parcelada no cartão e correção de categoria", async ({ page }) => {
  await register(page);
  await page.goto("/contas");
  await page.getByRole("button", { name: "Nova conta ou cartão" }).click();
  await page.getByLabel("Nome").fill("Nubank");
  await page.getByLabel("Tipo").selectOption("credit_card");
  await page.getByLabel("Limite (R$)").fill("5000");
  await page.getByLabel("Dia do fechamento").fill("25");
  await page.getByLabel("Dia do vencimento").fill("5");
  await page.getByRole("button", { name: "Salvar" }).click();
  await expect(page.getByRole("heading", { name: "Nubank" })).toBeVisible();

  await page.getByRole("button", { name: "Novo lançamento" }).first().click();
  await page.getByRole("tab", { name: "Manual" }).click();
  await page.getByLabel("Valor (R$)", { exact: true }).fill("1.200,00");
  await page.getByLabel("Descrição", { exact: true }).fill("Celular novo");
  await page.getByLabel("Conta ou cartão").selectOption({ label: "Nubank" });
  await page.getByLabel("Parcelas").fill("12");
  await page.getByRole("button", { name: "Registrar" }).click();
  await expect(page.getByText("Compra registrada em 12 parcelas.")).toBeVisible();

  await page.reload();
  // A compra inteira compromete o limite; nunca 12 × 1.200
  await expect(page.getByText("Usado R$ 1.200,00")).toBeVisible();
  await expect(page.getByText("Disponível R$ 3.800,00")).toBeVisible();

  await page.goto("/lancamentos?mes=todos&q=Celular");
  await expect(page.getByRole("button", { name: /Editar Celular novo/ })).toHaveCount(12);
});

test("lançamento offline é sincronizado ao reconectar", async ({ page, context }) => {
  await register(page);
  await page.goto("/lancamentos");
  await expect(page.locator("h1")).toHaveText("Lançamentos");

  await context.setOffline(true);
  await expect(page.getByText(/Sem internet/).first()).toBeVisible();
  await page.getByRole("button", { name: "Novo lançamento" }).first().click();
  await page.getByRole("tab", { name: "Manual" }).click();
  await page.getByLabel("Valor (R$)", { exact: true }).fill("30");
  await page.getByLabel("Descrição", { exact: true }).fill("Padaria offline");
  await page.getByRole("button", { name: "Registrar" }).click();
  await expect(page.getByText(/salvo no aparelho/)).toBeVisible();
  await expect(page.getByText("Aguardando sincronização")).toBeVisible();

  await context.setOffline(false);
  await expect(page.getByText(/sincronizados/)).toBeVisible({ timeout: 15_000 });
  await expect(page.getByText("Aguardando sincronização")).toHaveCount(0);
  await expect(page.getByRole("button", { name: /Editar Padaria offline/ })).toHaveCount(1);
});

test("assistente responde com dados reais", async ({ page }) => {
  await register(page);
  const quick = page.getByLabel("O que aconteceu?").first();
  await quick.fill("abasteci o carro com 120 reais");
  await page.getByRole("button", { name: "Interpretar" }).first().click();
  await page.getByRole("button", { name: "Confirmar" }).click();
  await expect(page.getByText("Lançamento registrado.")).toBeVisible();

  await page.goto("/assistente");
  await page.getByLabel("Sua pergunta").fill("Quanto gastei com combustível este mês?");
  await page.getByRole("button", { name: "Enviar" }).click();
  await expect(page.getByText(/Você gastou R\$\s?120,00 com Combustível este mês/)).toBeVisible();
});
