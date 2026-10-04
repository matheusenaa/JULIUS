import { defineConfig, devices } from "@playwright/test";

// Pré-requisito: backend rodando com o build do frontend (ver README, "Testes E2E").
export default defineConfig({
  testDir: "./e2e",
  timeout: 60_000,
  fullyParallel: false,
  workers: 1, // um navegador por vez: o hash de senha (Argon2) é lento de propósito
  expect: { timeout: 10_000 },
  reporter: [["list"]],
  use: {
    baseURL: process.env.E2E_BASE_URL ?? "http://127.0.0.1:8010",
    channel: "msedge", // usa o Edge instalado; dispensa baixar navegadores
    locale: "pt-BR",
    screenshot: "only-on-failure",
  },
  projects: [
    { name: "desktop", use: { viewport: { width: 1366, height: 860 } } },
    { name: "celular", use: { ...devices["Pixel 7"], channel: "msedge" } },
  ],
});
