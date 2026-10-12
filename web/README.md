# Zoop Web

Zoop의 웹 프론트엔드입니다. Vite, React, TypeScript, Tailwind CSS를
사용하며 pnpm으로 패키지를 관리합니다.

## 시작하기

```bash
pnpm install
pnpm dev
```

환경 변수는 `.env.example`을 참고해 `.env.local`에 작성합니다.

## 품질 검사

```bash
pnpm lint
pnpm format:check
pnpm build
```

커밋 시 Husky와 lint-staged가 staged 파일의 린트와 포맷을 검사합니다.

## 주요 구조

- `src/apis`: 공통 API 클라이언트와 기능별 요청·응답 타입
- `src/components`: 공통 및 기능별 UI 컴포넌트
- `src/hooks`: 재사용 React Hook
- `src/pages`: 라우트 진입 페이지
- `src/util`: UI와 API에 독립적인 유틸리티
