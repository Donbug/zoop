import { fileURLToPath, URL } from "node:url";
import { defineConfig } from "vitest/config";

// 화면 동작 시험 설정. 앱 번들(vite.config.ts)과 분리해 Tailwind·개발 서버 프록시를 싣지 않고,
// 시험 파일은 src 밖(tests/)에 둬서 `vite build` 입구(index.html)에서 닿지 않게 한다.
export default defineConfig({
  resolve: {
    alias: { "@": fileURLToPath(new URL("./src", import.meta.url)) },
  },
  test: {
    environment: "jsdom",
    include: ["tests/**/*.test.{ts,tsx}"],
    setupFiles: ["tests/setup.ts"],
    // 응답이 오가는 순서는 시험이 직접 정하므로 시간에 기대지 않는다. 다만 앱의 일시 장애 재시도(1초)를 기다리는 시험이 있어 넉넉히 둔다.
    testTimeout: 15_000,
  },
});
