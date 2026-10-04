import react from "@vitejs/plugin-react";
import { defineConfig } from "vite";
import { VitePWA } from "vite-plugin-pwa";

export default defineConfig({
  plugins: [
    react(),
    VitePWA({
      registerType: "autoUpdate",
      includeAssets: ["favicon.svg", "apple-touch-icon-180x180.png"],
      manifest: {
        name: "JULIUS — finanças pessoais",
        short_name: "JULIUS",
        description: "Controle financeiro pessoal com assistente inteligente.",
        lang: "pt-BR",
        theme_color: "#0B3D2C",
        background_color: "#F7F6F2",
        display: "standalone",
        start_url: "/",
        icons: [
          { src: "pwa-64x64.png", sizes: "64x64", type: "image/png" },
          { src: "pwa-192x192.png", sizes: "192x192", type: "image/png" },
          { src: "pwa-512x512.png", sizes: "512x512", type: "image/png" },
          { src: "maskable-icon-512x512.png", sizes: "512x512", type: "image/png", purpose: "maskable" },
        ],
      },
      workbox: {
        // App shell offline; a API nunca é servida do cache do service worker
        navigateFallback: "/index.html",
        navigateFallbackDenylist: [/^\/api\//],
        globPatterns: ["**/*.{js,css,html,svg,png,woff2}"],
      },
    }),
  ],
  build: {
    // O FastAPI serve o build: mesma origem para API e app
    outDir: "../backend/static",
    emptyOutDir: true,
  },
  server: {
    port: 5173,
    proxy: { "/api": "http://127.0.0.1:8010" },
  },
});
