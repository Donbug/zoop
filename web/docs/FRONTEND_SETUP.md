# 프론트엔드 초기 설정 정리

작성일: 2026-10-12
대상: `web/`
기준: 제공된 「프론트엔드 프로젝트 초기 설정 가이드」와 실제 적용 코드

## 1. 실행 환경과 명령

- 패키지 관리자: `pnpm@10.34.6` (`packageManager`에 정확한 버전 고정).
- 기존 가이드 권장 환경: Node.js 22 LTS. 이번 작업 검증 환경은 Node.js 24.19.0.
- 전역 pnpm 버전이 다른 환경에서는 `corepack pnpm`을 사용한다.
- `pnpm-lock.yaml`을 함께 관리하고 npm/yarn lockfile은 추가하지 않는다.

저장소 루트에서:

```bash
cd web
corepack pnpm install
corepack pnpm dev
```

품질 검사:

```bash
corepack pnpm lint
corepack pnpm format:check
corepack pnpm build
corepack pnpm test
```

테스트: Vitest + Testing Library + jsdom. 설정은 `vite.config.ts`의 `test`, 파일은 `tests/**/*.test.{ts,tsx}`, 공통 준비는 `tests/setup.ts`. API 호출은 `tests/support/fakeServer.ts`가 전역 fetch를 대체해 응답한다. 테스트 타입 검사는 `tsconfig.test.json`이 `tsc -b`에 포함한다.

자동 수정: `corepack pnpm lint:fix`, `corepack pnpm format`.
빌드 결과 확인: `corepack pnpm preview`.

## 2. 적용 스택

| 구분      | 구성                                                                   |
| --------- | ---------------------------------------------------------------------- |
| 번들러/UI | Vite 8 / React 19 / TypeScript 6                                       |
| 라우팅    | react-router-dom 7, createBrowserRouter, 중첩 라우트, lazy 페이지 로딩 |
| 스타일    | Tailwind CSS 4, @tailwindcss/vite                                      |
| API       | Fetch 공통 래퍼, 제네릭 응답 타입                                      |
| 상태      | Zustand 5                                                              |
| 품질      | ESLint 10, typescript-eslint, React Hooks/Refresh 규칙                 |
| 포맷      | Prettier 3, eslint-config-prettier                                     |
| 커밋 검사 | Husky 9, lint-staged 17                                                |

정확한 설치 버전은 `pnpm-lock.yaml` 기준이다. Axios는 가이드에 따라 설치되어 있으나 현재 API 래퍼는 Fetch를 사용한다. React Compiler는 선택 항목이므로 활성화하지 않았다.

## 3. 폴더와 경로 별칭

- `src/apis/`: 공통 호출, API 전용 응답 래퍼, 기능 API.
- `src/assets/common/`: 공통 정적 자산.
- `src/components/`: 공통 UI 및 도메인별 컴포넌트.
- `src/pages/`: 라우트 진입점; 이번 작업에서 페이지별 하위 폴더로 분리.
- `src/hooks/`: 재사용 훅.
- `src/util/`: 순수 유틸리티.
- `src/stores/`, `src/constants/`: 이번 작업에서 상태와 내비게이션 정의 추가.
- `src/types/`: 화면에서 공유하는 타입을 페이지 도메인별 하위 폴더와 `index.ts`로 분리.

기존 가이드와 코드의 복수형 `components` / `pages`를 유지했다. 단수형 폴더를 중복 생성하지 않는다.

타입은 현재 `common`, `auth`, `onboarding`, `map`, `stocks`, `company`, `briefing`, `ai`, `admin`으로 나뉜다. 컴포넌트 props, 라우트 state, Zustand state도 재사용되는 경우 해당 타입 폴더에서 가져온다. 화면에 아직 타입 계약이 없는 도메인은 빈 파일을 만들지 않고 실제 모델이 생길 때 폴더를 추가한다. API 응답 래퍼와 파일 내부에서만 쓰는 구현 타입은 응집도를 위해 `src/apis/`에 유지한다.

`@/* -> src/*`를 `tsconfig.app.json`과 `vite.config.ts`에 함께 설정했다. TypeScript 6에서 기존 가이드의 `baseUrl`을 유지하기 위해 `ignoreDeprecations: "6.0"`이 설정되어 있다. TS 7 업그레이드 시에는 `baseUrl` 제거와 상대 경로 기반 paths로 전환하는 작업이 필요하다.

## 4. 코드 품질과 Git 훅

Prettier 설정: 세미콜론, 작은따옴표, 2칸 들여쓰기, trailing comma, 80자 폭, LF.

- `eslint-config-prettier`를 마지막에 적용.
- `dist`, `node_modules`, `coverage` 등 생성 결과는 검사/포맷 대상에서 제외.
- TypeScript의 사용하지 않는 변수는 ESLint 경고이며 TypeScript 빌드에서도 검사.
- JS/TS staged 파일: ESLint 자동 수정 후 Prettier.
- JSON/CSS/Markdown/YAML staged 파일: Prettier.

Git 루트는 `zoop/`, 패키지 루트는 `zoop/web/`이므로 다음과 같이 경로를 조정했다.

```json
"prepare": "cd .. && husky web/.husky"
```

`web/.husky/pre-commit`:

```sh
pnpm --dir web exec lint-staged
```

설치 후 로컬 Git의 `core.hooksPath`는 `web/.husky/_`이다. 이번 작업에서 실제 커밋을 생성하지 않았으므로 커밋을 통한 hook end-to-end 실행은 별도 확인 대상이다.

## 5. 환경 변수와 API

`.env.example`을 참고해 `.env.local`에 실제 서버 주소를 설정한다.

```dotenv
VITE_API_BASE_URL=https://api.example.com
```

이 주소는 예시다. Vite의 `VITE_*` 값은 클라이언트 번들에 포함되므로 비밀키를 넣지 않는다.

`src/apis/auth/ApiService.ts`:

- Base URL, JSON 헤더/본문, Bearer token, `credentials: include`.
- 401 응답에서 refresh 후 원 요청을 한 번 재시도.
- 동시 refresh는 공유 Promise로 합침.
- 갱신 실패/재시도 후 401이면 인증 정보 제거 후 로그인 이동.
- HTTP 오류 예외 처리와 204 응답 처리.

현재 `/api/v1/auth/refresh`, `data.accessToken.token`, `/api/v1/items`는 초기 가이드 기반의 계약/예시다. Zoop 백엔드 계약과 확인한 뒤 연결해야 한다. `items.ts`는 실제 Zoop 기능 완성을 의미하지 않는다. `ApiResponse<T>`, `PageResponse<T>`도 백엔드 응답과 대조해야 한다.

이번 작업에서 인증 helper를 Zustand와 연결했다. API의 최신 토큰 확인은 기존 localStorage 키를 계속 읽고, 토큰 갱신/로그아웃은 화면 상태에도 반영된다. 로그아웃 시 온보딩 초안, 근거 창, AI 초안도 초기화한다.

## 6. 레이아웃과 라우팅

- 768px 미만: Bottom Navigation.
- 768px 이상: DesktopHeader.
- `#root`는 전체 폭 사용, 본문에 최대 폭과 모바일 하단 여백 적용.
- 사용자 내비게이션: 지도 / 종목 / 브리핑 / 내 종목.
- 관리자: 독립 AdminLayout 및 관리자 세션 가드.
- `vercel.json`에 SPA rewrite 포함. 실제 배포는 수행하지 않음.
- 상세 라우트 및 상태 설계: [와이어프레임 기반 구조](./WIREFRAME_ARCHITECTURE.md).

초기 예시 Home/Search/My/Detail을 실제 도메인 페이지로 대체했다. `/home`, `/search`, `/detail/:id`는 호환 리다이렉트를 둔다.

## 7. 구현 수준과 검증

완료: 초기 설정, 파일/폴더 분리, 페이지 라우팅, 공개/보호 영역 분리, 공통 골조, Zustand 상태 및 재사용 훅.

후속 작업: 실제 화면 디자인, 로그인/회원가입/온보딩 API, 그래프·차트, 문서/시세/브리핑 데이터, 관리자 API, 모바일 패널 UX.

로그인의 기존 개발용 진입은 Vite 개발 모드에서만 노출된다. 실제 사용자 인증은 미연결이며 관리자 로그인에는 가짜 세션을 발급하는 버튼을 만들지 않았다. 프론트엔드 가드는 서버의 인증·인가를 대신하지 않는다.

린트·포맷·TypeScript 및 프로덕션 빌드로 구조를 검증한다. 브라우저 시각 검증, 실제 API 통합, 인증 갱신 동시성·운영 API 검증은 이번 파일 골조 작업의 완료 범위에 포함하지 않는다.
