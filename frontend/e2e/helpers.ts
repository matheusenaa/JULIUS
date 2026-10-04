import { expect, type Page } from "@playwright/test";

export function trackConsole(page: Page) {
  const errors: string[] = [];
  page.on("console", (m) => m.type() === "error" && errors.push(m.text()));
  page.on("pageerror", (e) => errors.push(e.message));
  return errors;
}

/** Cria uma conta nova. Por padrão pula a configuração inicial. */
export async function register(page: Page, { onboarding = false } = {}) {
  const email = `e2e-${Date.now()}-${Math.random().toString(36).slice(2, 7)}@teste.com`;
  await page.goto("/criar-conta");
  await page.getByLabel("Seu nome").fill("Ana Teste");
  await page.getByLabel("E-mail").fill(email);
  await page.getByLabel("Senha").fill("senha-forte-123");
  await page.getByRole("button", { name: "Criar conta" }).click();
  await expect(page.getByRole("heading", { name: "Bem-vindo, Ana!" })).toBeVisible();
  if (!onboarding) {
    await page.getByRole("button", { name: "Pular configuração" }).click();
    await expect(page.getByRole("heading", { name: "Olá, Ana" })).toBeVisible();
  }
  return email;
}
