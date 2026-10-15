/// <reference types="vitest/config" />
import path from 'node:path';
import { fileURLToPath } from 'node:url';
import tailwindcss from '@tailwindcss/vite';
import react from '@vitejs/plugin-react';
import fs from 'node:fs';
import { defineConfig, loadEnv } from 'vite';

const dirname = path.dirname(fileURLToPath(import.meta.url));

// 로컬에서 실제 api/(Spring)와 붙여 볼 때만 켠다(web/.env.local). 설정이 없으면 기존과 같다.
// - ZOOP_DEV_API_TARGET: /api 요청을 넘길 API 주소(예: http://localhost:8080). 같은 Origin이라 세션 쿠키가 붙는다.
// - ZOOP_DEV_HTTPS_CERT·ZOOP_DEV_HTTPS_KEY: 개발 서버 HTTPS 인증서. 인증 API는 정확한 HTTPS Origin만 허용한다.
export default defineConfig(({ mode }) => {
  const env = loadEnv(mode, dirname, 'ZOOP_DEV_');
  const cert = env.ZOOP_DEV_HTTPS_CERT;
  const key = env.ZOOP_DEV_HTTPS_KEY;
  return {
    plugins: [tailwindcss(), react()],
    server: {
      https:
        cert && key
          ? {
              cert: fs.readFileSync(path.resolve(dirname, cert)),
              key: fs.readFileSync(path.resolve(dirname, key)),
            }
          : undefined,
      proxy: env.ZOOP_DEV_API_TARGET
        ? { '/api': { target: env.ZOOP_DEV_API_TARGET, changeOrigin: false } }
        : undefined,
    },
    resolve: {
      alias: {
        '@': path.resolve(dirname, './src'),
      },
    },
    test: {
      environment: 'jsdom',
      include: ['tests/**/*.test.{ts,tsx}'],
      setupFiles: ['./tests/setup.ts'],
      restoreMocks: true,
      unstubGlobals: true,
    },
  };
});
