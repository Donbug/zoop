import { fileURLToPath, URL } from "node:url";
import tailwindcss from "@tailwindcss/vite";
import react from "@vitejs/plugin-react";
import { defineConfig } from "vite";

// BFF 주소. 다른 포트에서 BFF를 띄웠다면 `ZOOP_BFF_URL=http://127.0.0.1:9000 pnpm dev`로 바꿀 수 있다.
const bffUrl = process.env.ZOOP_BFF_URL ?? "http://127.0.0.1:8787";

export default defineConfig({
  plugins: [react(), tailwindcss()],
  resolve: {
    alias: { "@": fileURLToPath(new URL("./src", import.meta.url)) },
  },
  server: {
    port: 5173,
    strictPort: true,
    proxy: {
      "/api": { target: bffUrl, changeOrigin: false },
    },
  },
  preview: {
    port: 4173,
    proxy: {
      "/api": { target: bffUrl, changeOrigin: false },
    },
  },
});
