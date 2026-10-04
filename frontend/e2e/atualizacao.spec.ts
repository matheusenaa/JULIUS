import { expect, test } from "@playwright/test";

import { register, trackConsole } from "./helpers";

test("onboarding: moeda, conta com saldo, salário e objetivo", async ({ page }) => {
  await register(page, { onboarding: true });
  await page.getByRole("button", { name: "Continuar" }).click();
  await page.getByLabel("Saldo de hoje").fill("2.500,00");
  await page.getByRole("button", { name: "Salvar e continuar" }).click();
  await page.getByLabel("Valor líquido").fill("3200");
  await page.getByLabel("Todo dia").fill("5");
  await page.getByRole("button", { name: "Salvar", exact: true }).click();
  await page.getByRole("button", { name: "Está bom assim" }).click();
  await page.getByRole("button", { name: "Pular", exact: true }).click();
  await page.getByRole("button", { name: "Começar a usar" }).click();
  await expect(page.locator(".hero .big")).toHaveText(/2\.500,00/);
  await page.goto("/futuros");
  await expect(page.getByText("Salário").first()).toBeVisible();
});

test("visão geral, futuros, dívidas e status sem erros no console", async ({ page }) => {
  const errors = trackConsole(page);
  await register(page);
  // Conta futura pelo atalho "Conta"
  await page.goto("/futuros");
  await page.getByRole("button", { name: "Novo lançamento futuro" }).click();
  await page.getByRole("button", { name: "Outro compromisso" }).click();
  await page.getByLabel("Descrição").fill("IPVA");
  await page.getByLabel("Valor (R$)").fill("850");
  await page.getByRole("button", { name: "Salvar" }).click();
  await expect(page.getByText("Lançamento futuro registrado.")).toBeVisible();
  await expect(page.getByText("IPVA")).toBeVisible();
  // Pagar: previsto → pago
  await page.getByRole("button", { name: "Paguei" }).first().click();
  await expect(page.getByText(/IPVA: marcado como pago/)).toBeVisible();

  // Dívida: 12x de 250 com 5 pagas → restam 7 (R$ 1.750)
  await page.goto("/dividas");
  await page.getByRole("button", { name: "Nova dívida" }).click();
  await page.getByLabel("Nome", { exact: true }).fill("Notebook");
  await page.getByLabel("Número de parcelas").fill("12");
  await page.getByLabel("Valor da parcela (R$)").fill("250");
  await page.getByLabel("Parcelas já pagas antes").fill("5");
  await page.getByRole("button", { name: "Salvar" }).click();
  await expect(page.getByText("R$ 1.750,00").first()).toBeVisible();
  await page.getByRole("button", { name: "Paguei a parcela 6" }).click();
  await expect(page.getByText("R$ 1.500,00").first()).toBeVisible();

  await page.goto("/visao-geral");
  await expect(page.getByRole("heading", { name: "Visão geral" })).toBeVisible();
  await expect(page.getByText("Dívidas restantes")).toBeVisible();
  await expect(page.getByRole("grid", { name: "Calendário financeiro" })).toBeVisible();
  for (const path of ["/documentos", "/assistente", "/ajustes", "/mais"]) {
    await page.goto(path);
    await expect(page.locator("h1")).toBeVisible();
  }
  expect(errors).toEqual([]);
});

test("documento PDF de conta lido sem IA e confirmado", async ({ page }) => {
  await register(page);
  await page.goto("/documentos");
  await page.locator('input[type="file"]').nth(1).setInputFiles("e2e/fixtures/conta-internet.pdf");
  await expect(page.getByRole("heading", { name: "Documento encontrado" })).toBeVisible();
  await expect(page.getByText("R$ 99,90").first()).toBeVisible();
  await expect(page.getByText(/Vence em 20\/12\/2030/)).toBeVisible();
  await page.getByRole("button", { name: "Confirmar" }).click();
  await expect(page.getByText(/Lançado e programado|Documento confirmado/)).toBeVisible();
  await expect(page.getByText("Confirmado").first()).toBeVisible();
});

test("assistente pede confirmação antes de excluir", async ({ page }) => {
  await register(page);
  const quick = page.getByLabel("O que aconteceu?").first();
  await quick.fill("gastei 500 no mercado");
  await page.getByRole("button", { name: "Interpretar" }).first().click();
  await page.getByRole("button", { name: "Confirmar" }).click();
  await expect(page.getByText("Lançamento registrado.")).toBeVisible();

  await page.goto("/assistente");
  await page.getByLabel("Sua pergunta").fill("Apague aquela despesa de R$ 500");
  await page.getByRole("button", { name: "Enviar" }).click();
  await expect(page.getByText(/Deseja realmente excluir/)).toBeVisible();
  await page.goto("/lancamentos");
  await expect(page.getByRole("button", { name: /Editar Mercado/ })).toBeVisible(); // ainda existe
  await page.goto("/assistente");
  await page.getByLabel("Sua pergunta").fill("Apague aquela despesa de R$ 500");
  await page.getByRole("button", { name: "Enviar" }).click();
  await page.getByRole("button", { name: "Confirmar" }).click();
  await expect(page.getByText("Feito", { exact: true })).toBeVisible();
  await page.goto("/lancamentos");
  await expect(page.getByRole("button", { name: /Editar Mercado/ })).toHaveCount(0);
});

test("edição offline entra na fila e sincroniza ao reconectar", async ({ page, context }) => {
  await register(page);
  const quick = page.getByLabel("O que aconteceu?").first();
  await quick.fill("gastei 40 na padaria");
  await page.getByRole("button", { name: "Interpretar" }).first().click();
  await page.getByRole("button", { name: "Confirmar" }).click();
  await expect(page.getByText("Lançamento registrado.")).toBeVisible();

  await page.goto("/lancamentos");
  await page.getByRole("button", { name: /Editar Padaria/ }).click();
  await context.setOffline(true);
  await page.getByLabel("Valor (R$)", { exact: true }).fill("45,00");
  await page.getByRole("button", { name: "Salvar" }).click();
  await expect(page.getByText(/alteração salva no aparelho/)).toBeVisible();
  await context.setOffline(false);
  await expect(page.getByText(/sincronizados/)).toBeVisible({ timeout: 20_000 });
  await page.reload();
  await expect(page.getByText("− R$ 45,00").first()).toBeVisible();
});
