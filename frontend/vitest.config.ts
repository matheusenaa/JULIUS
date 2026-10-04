import react from "@vitejs/plugin-react";
import { defineConfig } from "vitest/config";

// Configuração própria para testes: sem o plugin PWA (lento e desnecessário aqui)
export default defineConfig({
  plugins: [react()],
  test: {
    environment: "jsdom",
    globals: true,
    setupFiles: ["./src/test/setup.ts"],
    include: ["src/**/*.test.{ts,tsx}"],
    pool: "threads",
  },
});
