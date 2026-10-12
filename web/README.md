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
pnpm test
```

테스트는 Vitest·Testing Library(jsdom)로 실행하며 `tests/`에 둡니다. API는
`tests/support/fakeServer.ts`로 fetch를 대체해 응답을 흉내 냅니다.

커밋 시 Husky와 lint-staged가 staged 파일의 린트와 포맷을 검사합니다.

## 주요 구조

- `src/apis`: 공통 API 클라이언트와 API 전용 응답 래퍼
- `src/components`: 공통 및 기능별 UI 컴포넌트
- `src/hooks`: 재사용 React Hook
- `src/pages`: 라우트 진입 페이지
- `src/util`: UI와 API에 독립적인 유틸리티
- `src/stores`: 인증·온보딩 초안·지도 UI·AI UI의 Zustand 상태
- `src/types`: auth, map, company 등 페이지 도메인별 공유 타입
- `src/constants`: 사용자/관리자 내비게이션

## 개발 문서

- [초기 설정 정리](docs/FRONTEND_SETUP.md): 실행 환경, 품질 도구, API, Git 훅
- [와이어프레임 기반 구조](docs/WIREFRAME_ARCHITECTURE.md): 19개 페이지와 라우트, 공통 컴포넌트·상태·훅 후보

현재 화면은 와이어프레임 기반 개발 골조입니다. 실제 인증·그래프·차트·관리자
API는 후속 연결 대상입니다. 개발용 로그인은 Vite 개발 모드에서만 표시됩니다.
