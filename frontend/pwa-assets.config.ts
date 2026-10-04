import { defineConfig, minimal2023Preset } from "@vite-pwa/assets-generator/config";

export default defineConfig({
  preset: {
    ...minimal2023Preset,
    maskable: { ...minimal2023Preset.maskable, resizeOptions: { background: "#0B3D2C" } },
    apple: { ...minimal2023Preset.apple, resizeOptions: { background: "#0B3D2C" } },
  },
  images: ["public/favicon.svg"],
});
