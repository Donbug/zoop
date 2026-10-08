# 줍 프로토타입 설명서

> 2026-10-08 기준. 이 문서는 현재 로컬 프로토타입의 **사용·시연·실행·개발 연동**을 잇는 인계 자료입니다. 전체 요구 104개를 구현 완료했다고 보고하는 문서가 아닙니다. 최신 권한과 범위는 [오늘 작업 기준](day-work-2026-10-08.md)이 우선합니다.

배포용: [단독 HTML](prototype-guide.html) · [인쇄용 PDF](prototype-guide.pdf). 두 파일은 설명서 본문과 SUIT 글꼴을 포함합니다. 다른 문서·화면 증거 링크까지 하나의 파일에 묶은 것은 아니므로 연결 자료는 저장소와 함께 전달합니다. 글꼴 라이선스는 [SUIT OFL](system-architecture/SUIT-LICENSE.txt)입니다.

검증 범위: 이 설명서는 로컬 시연과 현재 계약을 설명합니다. 문서 공개 계약은 `zoop-document-gate-2`로 수정됐고, 해당 7개 지적과 직접 회귀에 한정한 독립 소스 재검토에서 resolved/findings=[]로 보고됐습니다. 로컬 시험·PDF 검사와 이 제한된 검토를 전체 보안 승인이나 운영 준비 완료로 읽지 않습니다.

## 1. 처음 보는 분께

줍은 기업과 사건 사이의 관계를 지도에서 살펴보고, 같은 기업의 사건을 시간순으로 확인한 뒤, 그 설명이 어떤 문서에서 나왔는지 찾아보는 금융 정보 서비스입니다. 가격 상승을 예측하거나 매수·매도를 권하는 서비스가 아닙니다. **관계선, 같은 날의 사건, 가격 변화가 함께 보인다는 것만으로 인과관계가 확인된 것은 아닙니다.**

처음에는 다음 세 가지만 기억하면 됩니다.

1. **지도 → 기업 → 근거** 순서로 읽습니다. 사건은 현실에서 일어난 일이고, 문서는 그 사건을 보도하거나 공시한 자료입니다. 문서 3개가 같은 사건을 다루면 사건이 3개로 늘어나지 않습니다.
2. **기간과 기준 시점**을 확인합니다. 사건 발생일과 문서 공개일은 다를 수 있습니다. 과거 `asOf`를 선택하면 그때까지 공개된 자료만 조회해야 하며, 차트·타임라인·관계 그래프가 같은 기준을 사용합니다.
3. **자료의 출처와 생성 방식을 따로** 확인합니다. 실제 기사 저장본도 오래된 snapshot일 수 있고, 합성 문서에 붙은 AI 분석은 작성된 replay 예시일 수 있습니다.

현재 화면은 React로 구현한 기능 확인용 복사본입니다. **Figma는 폰트를 제외한 최종 목표 디자인**이고 SUIT를 유지합니다. 현재 외관이 Figma와 이미 일치한다고 보지 않습니다. 본개발 프론트·백엔드 스택은 미정이며 Java/Spring은 유력 후보이지 확정 사항이 아닙니다.

### 지금 필요한 자료만 고르기

| 궁금한 내용 | 읽을 자료 |
|---|---|
| 10분 동안 무엇을 보여 주나요? | 이 문서 §2 |
| 모의 데이터와 실제 자료를 어떻게 구분하나요? | §3–4 |
| 내 PC에서 어떻게 켜고 끄나요? | §5–7, [실행 README](../../prototype/README.md) |
| 요청과 분석 작업은 어디에서 나뉘나요? | §8–10, [구조도 3장 PDF](system-architecture/out/system-architecture.pdf) |
| 특정 화면의 세부 상태·명세는 무엇인가요? | [77쪽 화면계획서 PDF](../screen-plan/zoop-screen-plan-v2.1.pdf), [화면 ID 목록](../screen-plan/captures/slide-index.json) |
| 본개발로 옮길 때 무엇을 유지하나요? | [스택 독립 이식 가이드](../migration/README.md), [계약 인계](../migration/contract-handoff.md) |

## 2. 10분 시연 동선

아래는 **공유 데모를 건드리지 않는 합성 모드**를 기본으로 합니다. §5의 격리 서버를 실행한 뒤 `http://127.0.0.1:5244`를 엽니다. 실제 뉴스 저장본을 보여 줄 때는 별도 상태 디렉터리와 provenance를 확인하고, 합성 시연과 섞지 않습니다. 시연 전에 외부 원문 링크를 열거나 시장·모델 공급자를 켤 필요는 없습니다.

| 시간 | 화면에서 할 일 | 설명할 내용·예상 차이 |
|---|---|---|
| 0:00–1:00 | 시작 화면에서 **로그인 없이 둘러보기 → 둘러보기 시작**을 선택합니다. 튜토리얼을 살펴보거나 건너뜁니다. | 비회원은 시장 전체 지도와 공개 자료를 봅니다. 내 종목·계좌·질문 전송은 회원 기능입니다. |
| 1:00–2:30 | 지도에서 기업·사건·관계선과 연결 없는 사건 안내를 봅니다. | 기본 합성 fixture는 기업 1개, 사건 3개, 직접 관계 2개입니다. 합성 알파전자와 현실 기업을 혼동하지 않습니다. 파생 경로는 승인된 직접 관계와 구분합니다. |
| 2:30–4:00 | 종목에서 **합성 알파전자**를 열고 사건 탭의 기간을 **1년**, 기준 시점을 저장본 시점으로 맞춥니다. 같은 날짜 묶음과 관계 그래프를 봅니다. | 기본 1개월에 사건이 없는 것은 정상일 수 있습니다. 차트와 타임라인의 동시 강조는 인과 판정이 아닙니다. 시세·지표 off 안내는 값 0이 아닙니다. |
| 4:00–5:00 | 사건의 근거를 열거나 문서 탭으로 이동합니다. | 문서 제목·발행일·인용문·출처를 확인합니다. `SYNTHETIC—not real news`는 실제 뉴스가 아닙니다. 외부 링크가 없거나 열리지 않아도 확보한 인용은 별도로 읽을 수 있습니다. |
| 5:00–6:00 | 브리핑에서 날짜와 출근/퇴근 회차를 선택합니다. | 운영 회차 예정 시각은 07:40/18:10 KST, 핵심 이슈는 최대 3개입니다. 새 합성 상태에서 scheduler를 끄면 발행 회차가 없을 수 있습니다. 이때는 ‘발행 전/자료 없음’을 보여 주고 과거 화면계획서의 회차 예시와 구분합니다. |
| 6:00–8:00 | 데모 회원으로 로그인합니다. 설정이 나오면 투자 여부, 계좌 건너뛰기, 관심 0개로 시작할 수 있습니다. 기업/사건에서 **AI에게 묻기**를 열고 ‘합성 알파전자의 사건을 알려줘’처럼 묻습니다. | 일반 질문은 규칙 기반 **예시 답변**입니다. 실 LLM 생성이라고 설명하지 않습니다. 모호한 질문은 되묻기, 근거 부족은 판단 보류일 수 있습니다. 패널을 닫았다 열어도 새 질문으로 재전송하지 않습니다. |
| 8:00–9:30 | S1 합성 분석을 import한 별도 시연 상태라면 기업 문서 또는 근거 창에서 문서 요약·문서×기업 판정을 읽습니다. 기본 상태라면 분석 미요청 상태를 설명합니다. | 일반 질문과 별도 생산 worker를 구분합니다. 작성된 합성 replay는 실제 provider 호출이 아닙니다. 요약과 기업별 긍부정은 다른 산출물이며, 혼재·판단 보류를 긍정/부정으로 바꾸지 않습니다. |
| 9:30–10:00 | 출처, 현재 기준 시점, 불러오지 못한 영역, 이번 시연의 미실행 경계를 다시 확인합니다. | 관리자 원장·실계좌·실모델·실시간 수집·클라우드 배포는 이 동선으로 입증되지 않습니다. |

합성 기업 상세를 바로 열려면 다음 주소를 사용합니다. 합성 자료는 발행일이 과거 사건 발생일보다 늦을 수 있으므로 문서 공개 전 시점에는 자료가 숨겨지는 것이 정상입니다.

```text
http://127.0.0.1:5244/companies/SYNTH-ALPHA?period=1y&asOf=2026-09-29T08%3A57%3A06%2B00%3A00&tab=documents
```

데모 회원은 `demo@zoop.local` / `zoop-demo`입니다. 이는 공개 로컬 seed이며 운영 계정이 아닙니다. 관리자 데모 계정은 일반 시연에 필요하지 않습니다.

## 3. 무엇이 실제이고 무엇이 예시인가요?

**원문의 진위, 저장 위치, 분석 실행 방식, 공개 상태는 서로 다른 축입니다.** `snapshot`은 합성을 뜻하지 않고, `live` 설정은 모든 기능이 실시간이라는 뜻이 아닙니다.

| 대상 | 현재 구현·자료 | 합성/실제 표시와 해석 | 이번 설명서의 실행·승인 경계 |
|---|---|---|---|
| 기본 지도·문서 | `poc-synthetic-inspect.json`의 고정 게시본 | `datasetKind=synthetic-preview`, `sourceMode=snapshot` | 격리 BFF/UI에서 조회. 실제 뉴스 아님 |
| 실제 뉴스 저장본 | `poc-real-inspect.json`, 별도 기업 카탈로그; 기존 원장에서 생산한 기사 저장 자료 | actual provenance + snapshot. 신규 수집·최신 뉴스라는 뜻 아님 | 기존 자료 존재/실행 안내를 인용. 이번에 재수집·재분석·권리 재확인하지 않음 |
| 모의 보유·계좌 | 회원별 SQLite 상태, 가상 계좌 연결 | 본인 실제 증권계좌나 주문 기능 아님 | 로그인/설정 seam과 구분. 실제 금융기관 연결 미실행 |
| 모의 소셜 로그인 | `/mock-idp` 개발용 동의 화면 | 실제 카카오·구글 등의 인증 아님 | 운영 OAuth 승인의 증거 아님 |
| 일반 질문 | `RuleEngine`, 질문 작업·저장 답변·근거 검증 | 화면의 ‘예시 답변’. LLM 생성 아님 | 읽기/작업 복구 기능과 provider 품질을 구분 |
| S1 문서 요약·기업 판정 | 별도 worker JSON 산출물 → 검증 → BFF import → 저장값 조회 | `sourceKind`와 `recordingKind`, `mode`로 actual/synthetic/live/replay 구분 | authored synthetic replay만 로컬 증거로 사용. 실 provider 승인 전 |
| 브리핑 | 선정·검증·발행 회차 저장과 별도 승인 outlook 생성은 다른 경로 | 기존 outlook provider/replay 생산을 worker로 이행해 보존. 재생 회차의 시계와 실제 발행 시각은 별도 | 기본 매뉴얼 상태에서는 생성 미실행. 담당 backend의 별도 fresh 합성 상태에서 생성·불변 발행·0이슈 무호출을 관측 |
| 시세·지표 | 설정에 따라 외부 HTTP; 값·관측 시각·출처·지연 상태 표시 | 실제 값이어도 지연되거나 미제공일 수 있음 | 이번 실행은 모두 off. 외부 조회 성공으로 주장하지 않음 |
| PoC 원장·Neo4j | 관리자 읽기/진단, 샌드박스 CLI 생산·게시 | 승인 결과와 HOLD/REJECT 감사 후보 분리 | 이번 매뉴얼은 원장 연결·게시·투영을 실행하지 않음 |
| 목표 운영 API·클라우드 | `/api/v1` OpenAPI, 클라우드 설계 | 현재 `/api`와 별도 목표 계약 | 목표 계약 존재 ≠ 운영 구현/배포 완료 |

일반 `replay`라는 말도 구분해야 합니다. 기존 PoC replay와 새 worker의 **authored-test 합성 응답 재생**은 같은 데이터라는 뜻이 아닙니다. 새 S1의 작성된 replay는 synthetic 입력에만 사용하며 실제 기사에 합성 분석을 붙여 실제 AI 결과처럼 표시하지 않습니다. 실 호출 수·usage와 replay 수는 분리해야 하고, 확인하지 못한 비용은 0원으로 만들지 않습니다.

## 4. ‘없음’의 네 가지 뜻

| 상태 | 뜻 | 사용자가 할 일 | 개발자가 지킬 조건 |
|---|---|---|---|
| 정상 0건 | 조회는 성공했으나 선택 조건에 맞는 자료가 없습니다. | 기간·기준 시점·관심 종목을 확인합니다. 관심 0개도 정상입니다. | 빈 배열/0과 오류를 구분하고 정상 조회 근거를 유지합니다. |
| 자료 없음/미연결 | 원문·시세·발행 회차 등이 확보되지 않았거나 공급자가 꺼져 있습니다. | 다른 확보된 자료를 읽습니다. 연결 여부를 확인합니다. | 없는 값에 0·가짜 인용·임의 시각을 채우지 않습니다. |
| 미판정/미요청·보류 | 문서 분석을 요청하지 않았거나 검증·권리 gate를 통과하지 못했습니다. | 판단값 없이 근거를 확인합니다. 운영자가 원인에 맞게 처리합니다. | `null`, `not_requested`, `pending`, `withheld`를 긍정/부정으로 대체하지 않습니다. 판단 보류라는 정상 판정 label과 산출물 비공개는 별개입니다. |
| 실패 | 네트워크·원장·작업·저장·검증 단계에서 오류가 발생했습니다. | 실패한 영역만 다시 조회하거나 기존 작업 상태를 확인합니다. | 실패를 ‘0건’, ‘작업 없음’, ‘성공’으로 바꾸지 않습니다. 재조회는 새 생성이 아닙니다. |

기업 상세 한 영역이 실패해도 다른 영역은 읽을 수 있어야 합니다. 시세 오류 때문에 문서까지 지우거나 문서 재조회 때문에 분석 작업을 새로 실행하면 안 됩니다.

## 5. 설치와 안전한 로컬 실행

### 사전 준비

- Node.js 22.12 이상, pnpm 11.9 계열, Python 3.12 이상, uv를 준비합니다. 정확한 앱 의존성은 [web package.json](../../prototype/web/package.json), [BFF pyproject](../../prototype/bff/pyproject.toml)과 lock 파일이 기준입니다.
- BFF는 비공개 `Donbug/investmate-poc`의 고정 커밋을 의존성으로 사용합니다. **해당 조직 저장소를 읽을 권한이 있는 계정과 Git 인증**이 필요합니다. 권한이 없으면 `uv sync`가 실패할 수 있으며 빈 데이터로 대신 동작했다고 보고하지 않습니다. 계정 등록·인증은 사람이 수행하고 토큰을 문서·로그에 적지 않습니다.
- 기본 합성 시연은 저장소에 포함한 [poc-synthetic-companies.json](../../prototype/bff/fixtures/poc-synthetic-companies.json)을 사용하므로 원본 PoC checkout이 없어도 실행할 수 있습니다. 공개 합성 settings의 `companies` 배열만 읽기 전용으로 추출했고 모델 설정·`.env`·키는 복사하지 않았습니다. 비공개 **설치 패키지** read 권한은 여전히 필요하며 로컬 원본 checkout 요구와는 다릅니다. 관리자 생산용 샌드박스와 원장은 별도 준비 대상입니다.
- 고정 snapshot 사용자 조회에는 Docker가 필요 없습니다. 관리자 원장/Neo4j/생산 작업에는 별도 격리 인프라가 필요합니다. [PoC 실행 기록](../evidence/poc-backend.md)을 따르고 다른 프로젝트의 볼륨을 지우지 않습니다.
- 설치 명령은 [root Makefile](../../Makefile)의 `web-install`, `bff-install`을 참고합니다. 이 설명서 작성에서는 새 패키지·브라우저를 설치하지 않았고 private dependency 재인증도 실행하지 않았습니다.

### 터미널 A: 합성 BFF

아래 명령은 **저장소 루트**에서 실행합니다. 이미 설치된 `.venv`를 사용하며 `.env`를 읽지 않습니다. env를 비워 실제 키나 공급자 설정이 상속되지 않도록 합니다. snapshot과 기업 카탈로그 모두 repo-local 파일이므로 다른 PC에서 원본 PoC checkout 경로를 맞출 필요가 없습니다.

```sh
env -i PATH=/usr/bin:/bin HOME=/tmp PYTHONDONTWRITEBYTECODE=1 \
  PYTHONPATH="$PWD/prototype/bff/src" \
  ZOOP_STATE_DIR=/tmp/zoop-manual-day-20261008 \
  ZOOP_SNAPSHOT_PATH="$PWD/prototype/bff/fixtures/poc-synthetic-inspect.json" \
  ZOOP_COMPANY_CATALOG="$PWD/prototype/bff/fixtures/poc-synthetic-companies.json" \
  ZOOP_POC_SANDBOX=/tmp/zoop-manual-day-20261008-sandbox \
  ZOOP_BRIEFING_SCHEDULER=off ZOOP_QUOTE_PROVIDER=off ZOOP_METRICS_PROVIDER=off \
  ZOOP_AI_LIVE_ENABLED=0 ZOOP_AI_GLOBAL_MAX_CALLS=0 \
  "$PWD/prototype/bff/.venv/bin/python" -m uvicorn zoop_bff.main:app \
  --host 127.0.0.1 --port 8874
```

`http://127.0.0.1:8874/api/health`에서 `status=ok`, `datasetKind=synthetic-preview`, `source.mode=snapshot`, `graphVersion=v1`을 확인합니다. `sourceErrors`, `warnings`도 읽습니다. `/docs`는 실제 BFF API 문서, `/openapi.json`은 실행 스키마입니다. source grant registry를 연결하거나 AI 작업을 submit하지 않으므로 이 실행에서 모델 전송 권한을 열지 않습니다.

### 터미널 B: 별도 웹 포트

```sh
cd prototype/web
ZOOP_BFF_URL=http://127.0.0.1:8874 pnpm exec vite --host 127.0.0.1 --port 5244 --strictPort
```

`http://127.0.0.1:5244`를 엽니다. 이 smoke는 기존 생성 토큰을 재사용하려고 Vite를 직접 실행합니다. 일반 개발에서는 `pnpm dev --host 127.0.0.1 --port 5244`가 토큰 생성 후 Vite를 실행합니다. `ZOOP_BFF_URL`이 프록시 대상을 정하며 `--strictPort`는 사용 중인 포트를 몰래 바꾸지 않습니다. `localhost`와 `127.0.0.1`을 섞지 않습니다. 세션 쿠키는 포트가 아니라 호스트 기준이므로 같은 호스트의 공유 브라우저 세션과 혼동하지 않도록 전용 프로필을 권장합니다.

새 상태 디렉터리를 다시 만드는 것은 데이터 초기화입니다. 위 경로에 상태가 이미 있으면 회원·게시 버전·회차를 유지합니다. 다른 snapshot을 등록하려면 **다른 비어 있는 상태 디렉터리**를 선택합니다. 기존 디렉터리를 지워 맞추지 않습니다. `ZOOP_SOURCE=live`는 제거된 설정이며 기동 오류가 맞습니다.

## 6. 권한·관리자·외부 실행 주의

| 사용자 | 실제 기능 범위 | 아닌 것 |
|---|---|---|
| 비회원 | 전체 지도, 공개 기업/문서/관계 조회, 튜토리얼 | 개인화 저장·계좌 연결·질문 전송 |
| 회원 | 본인 관심/모의 보유/설정/대화·작업, 개인화 지도 | 타인 데이터, 실계좌 거래, 운영 소셜 인증 |
| 관리자 | 별도 세션, 검수·게시/되돌리기·작업·회차·사용량·감사 기록 | 모든 조회가 무해한 버튼이라는 보장 |

관리자 기본 로컬 seed는 `admin@zoop.local` / `zoop-admin`입니다. 일반 데모 회원 세션과 관리자 세션은 분리됩니다. `/admin/pipeline`의 **게시·되돌리기·허용/거부·작업 재시도**, 브리핑 재처리·정정·제공 중단은 저장 상태를 바꾸며 감사 기록을 남깁니다. 관리자 원장 연결 실패가 사용자 snapshot 조회 실패와 같지 않습니다.

실제 모델 실행은 다음을 각각 충족해야 합니다. 모델명을 이 설명서에 고정하지 않습니다.

1. 원문에 대한 읽기·저장·모델 전송·인용 표시 권리를 확인하고, 목적·수신자·유효기간·grant revision을 운영자 registry로 승인합니다. 모델 응답이나 사용자 submit이 권한을 스스로 만들어 주지 않습니다.
2. 공급자와 모델, 생성 단계와 의미 검증 단계의 추론 수준을 공개 예시 변수 **이름**에 따라 운영자가 설정합니다. 실제 `.env`·키는 읽거나 문서화하지 않습니다.
3. 실제 실행 승인과 예산 상한을 따로 정합니다. `ZOOP_AI_LIVE_ENABLED`와 `ZOOP_AI_GLOBAL_MAX_CALLS`는 opt-in gate이며, 값이 없거나 0이면 실 provider를 열지 않습니다. 기존 관리자 PoC 작업의 호출 상한은 새 worker의 예산과 별도입니다.
4. live 사용량·성공·실패·결과 불명과 replay를 구분합니다. 결과 불명 상태에서 같은 요청을 자동 재호출하지 않습니다. 예산 미정인 현재는 실 provider 품질·비용을 미검증으로 남깁니다.

관련 변수의 **이름만** 참고합니다: `ZOOP_STATE_DIR`, `ZOOP_SNAPSHOT_PATH`, `ZOOP_COMPANY_CATALOG`, `ZOOP_BFF_URL`, `ZOOP_QUOTE_PROVIDER`, `ZOOP_METRICS_PROVIDER`, `ZOOP_BRIEFING_SCHEDULER`, `ZOOP_AI_LIVE_ENABLED`, `ZOOP_AI_GLOBAL_MAX_CALLS`, `ZOOP_AI_BASE_URL`, `ZOOP_AI_API_KEY`. 단계별 모델·추론 변수는 최신 [BFF 공개 설정 예시](../../prototype/bff/.env.example)와 worker 실행 문서를 따릅니다. 이 목록은 비밀값 입력 예제가 아닙니다.

| 단계 | 모델 변수 이름 | 추론 수준 변수 이름 |
|---|---|---|
| 문서 요약 | `ZOOP_AI_DOCUMENT_SUMMARY_MODEL` | `ZOOP_AI_DOCUMENT_SUMMARY_REASONING_EFFORT` |
| 문서×기업 판정 | `ZOOP_AI_DOCUMENT_SENTIMENT_MODEL` | `ZOOP_AI_DOCUMENT_SENTIMENT_REASONING_EFFORT` |
| 문서 주장 의미 검증 | `ZOOP_AI_VERIFY_MODEL` | `ZOOP_AI_VERIFY_REASONING_EFFORT` |
| 기존 회차 outlook | `ZOOP_AI_BRIEFING_OUTLOOK_MODEL` | `ZOOP_AI_BRIEFING_OUTLOOK_REASONING_EFFORT` |

위 표는 공개 템플릿의 설정 seam입니다. 빈 값에 임의 모델명을 넣거나 설정만으로 live 승인을 대신하지 않습니다.

## 7. 종료·복구·보존

### 정상 종료와 보존

1. 터미널 B에서 `Ctrl+C`로 소유 웹 서버를 종료합니다.
2. 터미널 A에서 `Ctrl+C`로 BFF를 정상 종료합니다. 진행 작업이 있다면 먼저 작업 ID와 상태를 기록합니다.
3. SQLite와 게시 JSON이 들어 있는 `ZOOP_STATE_DIR`을 함께 보존합니다. worker 실행 저장소는 별도이며 앱 상태만 백업해서 worker receipt까지 복구했다고 말할 수 없습니다. 실제 회원 자료가 있는 상태를 배포 artifact에 넣지 않습니다.

공유 `prototype/bff/var`, 8787/5173 서버, 원본 PoC는 이 설명서의 격리 smoke에서 변경하지 않습니다. `/tmp`는 영구 보존 장소가 아닙니다. 데이터가 필요하면 운영자가 승인한 위치로 정상 종료 후 상태 전체를 백업하고 복구 정책을 정합니다. 로그아웃은 회원의 대화·설정·원장 기록 삭제가 아닙니다.

### 문제별 첫 행동

| 관측한 문제 | 복구 방법 |
|---|---|
| 주소가 안 열리거나 포트 사용 중 | 소유 터미널의 기동 로그와 포트를 확인합니다. 공유 서버를 강제 종료하지 말고 새 포트와 `ZOOP_BFF_URL`을 맞춥니다. |
| private PoC 설치가 거부됨 | 조직 저장소 read 권한·Git 인증·고정 rev 접근을 사람이 확인합니다. 토큰을 로그에 출력하지 않습니다. |
| snapshot 파일을 바꿨는데 지도가 그대로 | 기존 v1이 등록된 상태인지 health warnings와 graphVersion을 봅니다. 새 상태 디렉터리로 분리하거나 승인된 관리자 게시 경로를 사용합니다. |
| 1개월 타임라인이 0건 | 사건 발생 시점·문서 공개 시점·`asOf`를 확인하고 1년으로 바꿉니다. 실패 여부를 먼저 구분합니다. |
| 시세/지표가 없거나 출처 미연결 | 공급자가 off인지 확인합니다. 이번 합성 실행에서는 의도한 상태입니다. 실제 호출을 임의로 켜지 않습니다. |
| 관리자 원장·Neo4j만 실패 | 별도 인프라 연결 문제입니다. 공개 snapshot을 유지하고 원장 설정/격리 컨테이너를 운영자가 확인합니다. |
| 질문 접수 응답을 못 받음 | 기존 작업 ID로 상태를 조회합니다. 조회 실패를 ‘미등록’으로 단정하지 않습니다. 서버가 미등록을 확인했을 때만 같은 ID·내용으로 접수합니다. |
| worker 결과가 ready인데 화면에 없음 | 앱 import·공개 gate·문서/기업/버전·권리 revision을 확인합니다. ready는 앱 공개 완료가 아닙니다. |
| 분석 산출물이 withheld | 권리·철회·원문 hash/버전·인용·의미 검증 사유를 확인합니다. 표시를 강제로 켜거나 보류를 긍정으로 바꾸지 않습니다. |
| 모델 요청 뒤 결과가 불명 | 기존 receipt/작업의 get·resume 경로를 이용합니다. 새 job으로 덮거나 자동 모델 재호출하지 않습니다. |

## 8. 개발자가 보는 실행 경계

[구조도 PDF](system-architecture/out/system-architecture.pdf)는 현재 실행 구조를 세 장으로 설명합니다. 실선은 구현 경로, 점선은 선택적 연결·실행 승인/본개발 목표이며 모든 실선이 이번에 실행되었다는 뜻은 아닙니다.

| 구성 | 현재 책임 | 외부에 노출되는 seam |
|---|---|---|
| `prototype/web` | React 화면, Router, TanStack Query, 공용 overlay, SUIT/토큰, 그래프·차트 | HTTP JSON, URL의 기업/기간/asOf/선택, 생성 OpenAPI 타입 |
| `prototype/bff` | FastAPI `/api`, 세션/소유권, 공개 자료 조회, SQLite 앱 상태, 검수·게시·브리핑, worker transport/import | `/openapi.json`, 공개 GET, 명시적 쓰기·관리 명령 |
| `prototype/ai-worker` | 별도 프로세스 CLI, versioned JSON, 자체 job/receipt/artifact 저장, 생성·정확/의미 검증 | stdin JSON → stdout JSON, `submit/run/get/resume/cancel`; 별도 HTTP 서버 아님 |
| 기존 PoC 패키지/CLI | 뉴스 분석·검증과 승인/감사 원장, 기존 공개 port | 고정 패키지의 공개 API·CLI, `PostgresRepository.inspect()`; private 구현/테이블 공유를 이식 seam으로 삼지 않음 |
| 게시 snapshot | 공개 그래프 버전과 문서·근거의 고정 조회 입력 | 불변 JSON + graphVersion/asOf |
| SQLite 앱 상태 | 회원/세션/설정/검수/회차/분석 import와 현재 visibility | BFF를 통해 접근. FE/다른 런타임이 DB를 직접 공유하지 않음 |
| PostgreSQL·Neo4j | PoC 원장·투영 진단 | 관리자 경계만. 사용자 그래프의 직접 조회 저장소 아님 |

기본 개발 포트는 BFF 8787, 웹 5173, preview 4173입니다. 이번 매뉴얼 증거는 8874/5244입니다. PoC는 CLI이고 `web_approval`은 외부 웹 근거 검증 의미이지 HTTP 서버 포트가 아닙니다. 기존 격리 DB 55432, Neo4j 원장별 연결 57687/58687은 사용자 API와 별개이며 [PoC 인프라 기록](../evidence/poc-backend.md)이 기준입니다.

### A. 요청 → 조회

브라우저의 기업/기간/asOf → API client와 조회 key → BFF 세션·권한·게시 버전 확인 → snapshot + 앱 저장값 조회 → JSON → 화면입니다. 다른 기업의 늦은 응답이 현재 기업을 덮지 않도록 key·AbortSignal·선택 상태를 함께 관리합니다. **S1 문서 분석 GET는 저장값을 읽고 현재 공개 gate만 확인합니다. worker 호출·분석 접수·usage 증가·결과 import를 하지 않습니다.** 시장 공급자 연결 시의 일반 시세 GET는 외부 HTTP를 할 수 있으므로 ‘모든 GET가 네트워크도 하지 않는다’는 뜻은 아닙니다.

### B. 문서 분석 → 검증 → import → 공개 조회

명시적 worker 제출 → job/입력 digest 고정 → 원문 권리·예산 gate → 생성 응답 receipt 보존 → 정확 인용 검증 → 별도 의미 검증 → immutable artifact/ready → **앱의 import 검증·저장** → 현재 권리/철회/버전 gate를 통과한 값만 GET로 제공됩니다. 모델 문장이 그래프 관계선을 직접 만들지 않습니다. PoC 원장에서 snapshot을 공개하는 관리자 흐름과 문서 산출물 import를 같은 게시 기능으로 혼동하지 않습니다.

정확 인용은 문서 ID/버전, sourceHash, textArtifactId, inputKind, evidenceId, `offsetUnit=unicode_code_point`, `[start,end)`를 함께 검사합니다. 실제 원문 `text[start:end]`가 quote와 정확히 같아야 합니다. JavaScript UTF-16 인덱스나 UTF-8 바이트 위치를 그대로 대입하지 않습니다. 맞는 문자열 구간이라고 의미까지 입증되는 것은 아니므로 claim별 근거와 semantic verdict를 별도로 검사합니다.

현재 문서 gate-2에서는 공개 `limitations` 문장도 `assertionKind=limitation` claim과 **순서까지 1:1**로 대응하며 별도 의미 검증의 대상입니다. `text`/`rationale`에는 사실·해석 claim만 조립하고 제한 claim을 본문에 중복시키지 않습니다. worker와 BFF가 각각 대조합니다. 이전 gate-1의 raw/worker 산출물은 삭제하지 않지만 `document_policy_outdated`로 공개 보류하고 cache hit로 재사용하지 않습니다. 운영자가 새 gate-2 job을 제출해 다시 검증해야 하며 과거 같은 job의 설정을 바꾸거나 자동 모델 재호출로 처리하지 않습니다.

## 9. S1 작업·복구 계약

S1은 **문서 요약과 문서×기업 판정**의 독립 생산 경계입니다. 일반 채팅은 여전히 규칙 기반입니다. 기존 원본 PoC는 읽기 전용으로 유지하며 새 worker를 PoC HTTP 서버처럼 설명하지 않습니다.

worker 공개 명령은 다음 help로 확인할 수 있습니다. 프로젝트가 설치되지 않은 현재 checkout에서는 기존 BFF interpreter와 `PYTHONPATH`를 사용할 수 있습니다. help는 모델/원장을 호출하지 않습니다.

```sh
PYTHONPATH="$PWD/prototype/ai-worker/src" \
  prototype/bff/.venv/bin/python -m zoop_ai.cli --help
PYTHONPATH="$PWD/prototype/bff/src" \
  prototype/bff/.venv/bin/python prototype/bff/scripts/document_analysis.py --help
```

| 단계/상태 | 의미 | 복구 원칙 |
|---|---|---|
| submit / queued | 고정된 jobId·kind·입력·config revision·권리 revision을 접수 | 같은 ID·같은 입력을 유지. 다른 입력을 같은 ID로 덮지 않음 |
| running | 생성 또는 의미 검증 실행 중 | 상태 조회는 추가 모델 호출이 아님 |
| persisting / reconciling | receipt 또는 결과 저장·정합 복구 | save_only는 저장 receipt와 같은 작업·kind의 own artifact를 재사용. standalone HOLD/REJECT의 ready 저장 복구도 provider 재호출 없음 |
| ready | worker 산출물이 준비됨 | 앱 import·현재 공개 gate 완료와 분리 |
| failed | 실패 code가 있음 | retryMode/receipt를 확인. 무조건 새 호출하지 않음 |
| cancelled | 작업 취소 | 늦게 도착한 결과가 공개되지 않도록 fence 유지 |
| 앱 available / withheld / pending / failed / not_requested | import 및 현재 공개 상태 | 화면은 상태와 사유를 표시하며 null을 판정값으로 만들지 않음 |

`get`과 `cancel`은 모델 client를 만들지 않습니다. `resume`도 필요한 receipt가 있으면 결과 회수·저장 복구를 해야 합니다. 전송 timeout은 완료 여부 불명일 수 있으므로 기존 jobId의 `get/resume`으로 확인하며 새 job을 만들지 않습니다. worker 저장소는 worker 소유이고 앱은 transport 결과를 가져옵니다.

`document_analysis.py import`는 **server-owned `--grants <registry.json>`을 필수로** 받습니다. 이 입력으로 현재 권한 snapshot을 갱신하는 단계와 저장 worker artifact를 가져오는 단계는 별개입니다. worker/job에 실린 과거 grant는 실행 영수증이며 현재 authority를 덮어쓰지 않습니다. opaque revision을 문자열 정렬·시각으로 비교해 최신 권한을 추정하지 않습니다.
 
`--grants`는 일부 변경 목록이 아니라 **운영자가 승인한 완전한 현재 snapshot**입니다. 목록에서 빠진 grant는 fail-closed로 제외되므로 공유 운영 상태에 fixture의 일부 목록을 넣지 않습니다. 다음은 앞서 만든 S1 합성 상태에서만 사용할 수 있는 import 재현 명령입니다. 정상 종료한 상태 또는 운영자가 승인한 import 권한 아래 실행하며 원문·worker 상태·registry를 서로 다른 시연과 섞지 않습니다.

```sh
env -i PATH=/usr/bin:/bin HOME=/tmp PYTHONDONTWRITEBYTECODE=1 \
  PYTHONPATH="$PWD/prototype/bff/src" \
  ZOOP_SNAPSHOT_PATH="$PWD/prototype/ai-worker/fixtures/contracts/synthetic-document/snapshot.json" \
  ZOOP_COMPANY_CATALOG="$PWD/prototype/ai-worker/fixtures/contracts/synthetic-document/snapshot.json" \
  ZOOP_BRIEFING_SCHEDULER=off ZOOP_QUOTE_PROVIDER=off ZOOP_METRICS_PROVIDER=off \
  "$PWD/prototype/bff/.venv/bin/python" prototype/bff/scripts/document_analysis.py import \
  --state-dir /tmp/zoop-manual-s1-bff-20261008 \
  --worker-state /tmp/zoop-manual-s1-worker-20261008 \
  --grants "$PWD/prototype/ai-worker/fixtures/contracts/synthetic-document/grants.json" \
  --job-id synthetic-SYNTH-A-document-summary
```

완료한 terminal job을 동일하게 다시 가져와도 최신 공개 순서를 바꾸지 않는 no-op입니다. 같은 attempt는 고정 identity를 확인해 허용된 상태·최초 확인 usage만 전진시키며 중복 행·비용을 만들지 않습니다. `deny`는 현재 visibility를 차단하는 별도 운영 명령입니다. 이 명령들은 모델 생성은 아니지만 **앱 권한·상태 쓰기**이므로 공유 상태에 임의로 실행하지 않습니다. 정확한 계약은 [AI 실행 문서](../design/ai-system.md)와 [BFF README](../../prototype/bff/README.md)를 따릅니다.

### S1 합성 분석을 따로 시연하기

기본 알파전자 fixture와 S1의 두 기업 fixture는 서로 다릅니다. 아래 명령은 **별도 worker 상태와 별도 앱 상태에 쓰는 합성 재현 명령**이며, 공유 상태에 실행하지 않습니다. helper의 `--help`는 이 설명서에서 확인했고 실제 submit/run/import 성공은 담당 S1 실행 증거와 구분합니다.

```sh
prototype/bff/.venv/bin/python prototype/ai-worker/scripts/replay_fixture.py \
  --worker-state /tmp/zoop-manual-s1-worker-20261008 \
  --bff-state /tmp/zoop-manual-s1-bff-20261008
```

worker JSON은 `zoop-ai-s1-1` schema version을 사용하고 fixture의 job 4개는 `SYNTH-A/SYNTH-B × document-summary/document-sentiment`입니다. 문서는 `doc-synthetic-s1`입니다. 이 fixture의 synthetic grant는 작성된 합성 자료에 대한 테스트 권한이지 실제 뉴스 전송 승인으로 옮겨 쓸 수 없습니다. helper는 live 설정·비밀·실제 뉴스·기본 BFF 상태를 전달하지 않습니다.

helper 실행 뒤 §5의 BFF 명령에서 `ZOOP_STATE_DIR`을 위 앱 상태로, `ZOOP_SNAPSHOT_PATH`와 `ZOOP_COMPANY_CATALOG`를 모두 `prototype/ai-worker/fixtures/contracts/synthetic-document/snapshot.json`의 절대 경로로 바꿉니다. 기본 합성 상태를 덮지 말고, 기존 8874/5244 소유 서버를 정상 종료한 뒤 같은 포트를 다시 사용합니다. 기업 경로는 `/companies/SYNTH-A?tab=documents` 또는 `/companies/SYNTH-B?tab=documents`이며 저장본 공개 시점 이후를 조회합니다.

실제 public seam은 `GET /api/companies/{id}/documents`, `GET /api/evidence/{id}?companyId=...`입니다. 직렬화 필드는 `documentSummary`, `analysisStatus`, `analysisProvenance`, `documentVersion`, `resultVersion`입니다. 기업을 바꿔 같은 문서의 기업별 판정이 다르게 유지되는지, claim별 근거 버튼이 해당 문서/버전/resultVersion의 exact citation을 여는지 확인합니다. 이 두 GET는 생성 작업이 아닙니다. 전체 재현·import/deny·권리 복구 명령은 [AI 실행 계약](../design/ai-system.md)을 따릅니다.

### 기존 회차 outlook 생성은 보존합니다

기존 `briefing-outlook`은 문서 요약/기업 판정과 같은 worker 경계로 이행한 **네 번째 kind**입니다. 새 기업·시장 요약은 S5지만 기존 outlook 생산을 삭제하거나 S5로 미루지 않습니다. 일반 HTTP 조회나 기본 scheduler가 이 설정만으로 모델을 호출하는 것은 아닙니다. 운영자가 `judge_outlook.py`에서 replay/live, source grant, 모델 설정과 예산을 명시하여 **미발행 회차**를 생성합니다.

```sh
# 저장소 루트. 문서 분석 시연과 다른, 처음 쓰는 세 상태 경로를 선택합니다.
prototype/bff/.venv/bin/python prototype/ai-worker/scripts/replay_outlook_fixture.py \
  --worker-state /tmp/zoop-manual-outlook-worker-20261008 \
  --bff-state /tmp/zoop-manual-outlook-bff-20261008 \
  --empty-bff-state /tmp/zoop-manual-outlook-empty-20261008
```

이 driver는 실제 [`judge_outlook.py`](../../prototype/bff/scripts/judge_outlook.py)를 실행해 2026-10-08 저녁의 이슈 1개 회차를 생성합니다. 같은 발행 회차를 다시 실행하면 기존 값과 `workerJobs=[]`를, 출근 0이슈 회차에서는 outlook null과 `workerJobs=[]`를 확인합니다. 이는 `undetermined`라는 유효 판정과 미산출 null의 차이도 보여 줍니다. 단독 worker/model 호출이나 일반 문서 생성 명령이 아닙니다. 정확한 flags는 `--help`, 재현 설명은 [AI 계약의 기존 outlook 절](../design/ai-system.md#기존-outlook-생성빈-회차불변-발행-재현)을 따릅니다.

회차 outlook은 기존 issueIds 참조와 금지 표현 검증 정책 `legacy-outlook-exact-1`을 보존하며 `validation.semantic=null`입니다. 문서 claim의 별도 의미 검증과 동급으로 통과했다고 설명하지 않습니다. 발행 후에는 null까지 불변이고 관리자 재처리는 409, payload 직접 변경은 SQLite trigger가 막습니다. 강화된 의미 검증과 전체 의존성 철회는 남은 단계입니다.

문서 판정이 이미 들어 있는 상태를 outlook fixture의 빈 `documentSentiments` 입력에 섞으면 exact replay가 `replay_input_mismatch`로 실패할 수 있습니다. 담당 backend의 최초 실행도 이 차이로 실패했으며 **새로 분리한 상태**의 실제 성공과 따로 기록했습니다. mismatch를 정상 결과로 바꾸거나 같은 상태를 지워 맞추지 않습니다. helper의 처음 생성 조건 때문에 재현을 처음부터 다시 할 때도 새로운 경로를 고릅니다.

불변 수용 시험은 [`test_outlook_worker.py`](../../prototype/bff/tests/test_outlook_worker.py)의 `test_existing_outlook_generates_then_round_get_and_restart_preserve_it`, `test_empty_round_publishes_null_without_any_worker_command`, `test_actual_outlook_cli_publishes_nonempty_and_empty_rounds_without_live_calls`입니다. 이 설명서 담당은 helper/producer `--help`만 추가 확인했고 해당 실제 생성·GET·시험 결과는 [backend 최종 실행 기록](../design/ai-system.md#실행으로-확인한-결과)을 인용합니다. 외부 모델을 새로 호출하지 않았습니다.

## 10. 화면·API·FS/WBS를 연결해 읽기

아래 화면 ID는 최신 77쪽 계획서의 ID입니다. 과거 `UI-01` 등의 별칭보다 `D-*/M-*/A-ADM-*`를 인계 기준으로 사용합니다. API 표는 대표 조회 seam이며 목표 `/api/v1`의 구현 완료 목록이 아닙니다.

| 관찰할 기능 | 화면 ID / PDF 페이지 | 현재 관측 seam | 요구 확인 |
|---|---|---|---|
| 시작·회원·모의 계좌 | D-AUT-01~03, D-ONB-01~02 / 16–20 | 로그인·회원 설정·계좌 API; 사용자/모의 IdP/관리자 세션 분리 | FS001~016, 모의 보유 FS039/054 |
| 전체/개인화 지도·선택·근거 | D-GRP-01~07b / 23–36, M-GRP-01 / 53 | `GET /api/graph`, 노드/관계/근거 조회 | FS017 이후 지도 정의; 전체/개인화·파생 관계 구분 |
| 기업·타임라인·asOf·문서 | D-COM-01~06 / 38–44, M-COM-01~02 / 57–58 | 기업별 개요/quote/events/documents 및 문서 분석 저장 필드 | FS038~044; FS042 목차 재무/상세 시점그래프 충돌은 정정 요청 유지 |
| 브리핑 회차·비교 | D-BRF-01~04 / 46–48, M-BRF-01 / 55 | 발행 회차·상태·변경·시장 지표 조회 | 브리핑 상세 정의, 회차 불변·최대 3개 |
| 일반 질문·근거·작업 복구 | D-AI-01~02b / 49–52, M-AI-01 / 56 | 대화·질문 작업 접수/조회·저장 답변 | FS045~053, 기존/v2 상세 정의를 따로 확인 |
| S1 문서 분석 | 기존 D-COM-02·D-GRP-05 문서/근거 seam | 기업 문서와 직접 evidence의 summary/status/provenance/version 조회 | 문서/판정 상세 수용 기준. 새 화면 캡처가 기존 77쪽에 자동 반영된 것은 아님 |
| 관리자 검수·AI·회차·감사 | A-ADM-* / 61–69 | `/api/admin/*`; 원장·게시·작업은 관리자 경계 | FS068 및 관리자 정의; 현재 WBS 제목/역할 연결 |

추적의 정본은 [system README](../system/README.md), [links.yaml](../system/links.yaml), [추적 xlsx](../system/out/zoop-trace.xlsx), [상세 수용 기준](../system/out/acceptance-matrix.md), [정정 요청](../system/out/source-corrections.md)입니다. [목표 OpenAPI](../api/openapi.yaml)의 `x-zoop`는 FS·화면·WBS·BFF 연결을 담고, [생성 API 설명](../api/out/zoop-api-spec.md)은 팀 배포용입니다. WBS는 번호가 재사용되었으므로 **ID 존재만 보지 말고 제목·BE/FE 역할·FS 의미**로 연결합니다. 저장된 [BFF 관측 스키마](../system/out/bff-openapi.json)는 관측 시점의 기준선이며 S1 현재 서버와 동일하다고 가정하지 않습니다.

### 본개발·다음 AI 단계와 현재 부족한 범위

현재 S1의 합성 결과 계약·화면 소비가 전체 AI 시스템이나 전체 프로토타입 완료를 의미하지 않습니다. S2~7은 별도 설계와 구현·검증 대상이며 단계별 정본은 [AI 시스템 설계](../design/ai-system.md)입니다. 기존 PoC에 유사 기능이 있어도 새 계약·복구·권리·두 조회 경로까지 완성됐다는 증거는 아닙니다.

| 단계 | 남은 구현 범위 |
|---|---|
| S2 | 수집 회차·cursor·정제/raw 위치, 기존 PoC 추출/SAME 재사용, 별도 주제형 이슈 |
| S3 | 공급·경쟁·투자 관계와 영향, 관계 적격성, HOLD 검수 후 재검증 |
| S4 | 전체 의존성 철회, 과거 pin·채팅·회차·캐시 공개 barrier와 증분 복구 |
| S5 | 새 기업·시장 요약, 중요도 선정·공통 회차 고도화. 기존 briefing-outlook 생산은 S1에서 worker로 이행해 보존했고 S5로 미루지 않음 |
| S6 | 실제 AI 질문 해석·답변·되묻기와 기존 채팅 작업 seam 이행 |
| S7 | 개인화 브리핑·소유권·평가·전체 사용량 끝단 |

위 순서는 요구 제외 결정이 아닙니다. 현재 문서 consumer 두 경로의 deny/version gate를 전체 그래프·옛 답변·회차의 의존성 closure 완료로 승격하지 않습니다.

FS074~081을 포함한 전체 명세·WBS는 **팀 합의 요구/설계 대상**입니다. 원문의 ‘검토 전’ 상태를 보존하되 현재 권한을 이유 없이 보류 범위로 축소하지 않습니다. 반대로 구현 권한이 실 provider 호출·외부 등록·클라우드 배포 승인이나 완료 증거를 대신하지 않습니다.

## 11. 개발 명령과 증거를 읽는 법

[root Makefile](../../Makefile)은 앱별 도구로 넘기는 진입점입니다. `make help`, `make projects`, `make available-checks`로 현재 대상과 설치 상태를 확인합니다. `web-typecheck/web-test/web-build`, `bff-test`, `worker-test`, `worker-contracts-check`, `contracts-check`, `docs-check`는 담당자가 최종 통합 때 실행할 게이트입니다. 설치 환경을 재사용하려면 `CONFIG_PYTHON`, `DOC_PYTHON`, `CONTRACT_PYTHON`, `WORKER_PYTHON` override를 참고합니다. 기본 `uv --with` 경로는 도구 bootstrap을 할 수 있으므로 새 의존성 설치가 금지된 환경에서는 기존 interpreter를 지정합니다. 구체적인 로컬/원격 구분은 [CONTRIBUTING](../../CONTRIBUTING.md)과 [GitHub 로컬 준비 가이드](../development/github-setup.md)를 읽습니다. 이 설명서 작성에서 테스트/빌드/린터를 실행하지 않았습니다. 명령이 있다는 사실을 통과 결과로 적지 않습니다.

웹 타입 생성 `pnpm api:types`는 현재 스크립트가 8787의 OpenAPI를 읽으므로 8874 smoke와 섞지 않습니다. 별도 포트의 타입을 갱신해야 할 때는 현재 스크립트/루트 tooling 계약을 확인하고 담당자가 새 schema와 모든 consumer를 함께 갱신합니다. 문서 생성·schema 검증은 [system 생성기 설명](../system/README.md)의 source freeze 경로와 목표/관측 구분을 따릅니다. `--check` 종료값뿐 아니라 hard error와 warning을 따로 읽습니다.

### 설명서 HTML·PDF 재생성

이 설명서의 source는 Markdown이며 [export_prototype_guide.py](export_prototype_guide.py)가 본문·SUIT 포함 HTML, 인쇄 PDF, 전페이지 증거 PNG를 만듭니다. 설치된 Pandoc과 기존 Playwright/PyMuPDF 환경, 기존 Chromium이 필요합니다. 새 의존성·브라우저를 자동 설치하지 않고 원격 asset 요청을 차단합니다. PDF의 문서 첨부 링크는 저장소 기준 상대 경로로 바꿔 다른 PC의 저장소 묶음에서도 원래 워크스테이션 경로를 요구하지 않도록 합니다.

```sh
# 이 PC의 기존 캐시 환경을 재사용한 예입니다.
/Users/asqi/.cache/uv/archive-v0/2baupm_HDQNxjW_J/bin/python \
  docs/share/export_prototype_guide.py \
  --chromium '/Applications/Google Chrome.app/Contents/MacOS/Google Chrome'
```

도구가 없는 다른 PC에서는 기존 HTML/PDF를 공유합니다. 재생성 후 실제 PDF 페이지 이미지에서 한국어, 표·코드 잘림, 연결 자료의 상대 경로를 확인합니다.

### 이번 설명서에서 직접 확인한 범위

- 기존 설치 도구: Node `v26.10.0`, pnpm `11.9.0`, Python `3.12.13`, Vite `8.3.1`. 이는 이 PC의 관측값이며 배포 스택 고정 선언이 아닙니다.
- `python -m uvicorn --help`, `python -m zoop_ai.cli --help`, `document_analysis.py --help`, `replay_fixture.py --help`, `judge_outlook.py --help`, `replay_outlook_fixture.py --help`, `pnpm exec vite --help`, `export_prototype_guide.py --help`로 문서의 플래그·명령을 확인했습니다.
- 격리 BFF 8874와 웹 5244는 기동 readiness를 확인했습니다. 공개 health/graph/companies GET는 HTTP 200이고 합성 v1·그래프 노드 4개·간선 2개였습니다.
- 마지막으로 기본 합성 카탈로그를 repo-local 파일로 바꾼 실제 BFF를 같은 격리 8874에서 재기동하고 공개 GET를 각각 한 번 읽었습니다. health/companies/graph/기업 documents 모두 200, warnings/sourceErrors=[], SYNTH-ALPHA 1개·사건 3개·관계 2개·문서 3개(`synthetic-multi`, `synthetic-q2`, `synthetic-repeat`)를 유지했습니다. 원본 checkout 경로를 입력하지 않았고 추가 소유 서버도 종료했습니다.
- 브라우저에서 시작 화면 → 비회원 확인 창 → 전체 지도·튜토리얼 → 합성 기업 문서 탭을 관찰했습니다. 이후 데모 회원 로그인 → 투자하지 않음 → 관심 0개 → 같은 기업 문서 조회를 확인했습니다. 근거 문서 3건, 합성 표기, 시세/지표 미연결, 기준 시점과 관계 영역을 확인했습니다. [전용 브라우저 회원 화면 캡처](prototype-guide-member.webp)는 이 기본 fixture 관측이며 S1 분석 완료 화면이 아닙니다.
- S1 합성 문서 분석은 담당 worker의 별도 실행 기록을 인용하며 기본 매뉴얼 상태와 합치지 않습니다. 실 provider·시장·새 수집·PoC 원장·관리자 게시·실계좌·운영 로그인·클라우드 단계는 이번 smoke에서 미실행입니다.

소스 검사와 runtime smoke, 합성 replay와 외부 승인 후 live 실행은 서로 다른 증거입니다. 이 설명서는 이를 합산해 전체 수용 기준 통과로 승격하지 않습니다.

직접 관측의 구조화 기록은 [manual evidence JSON](prototype-guide-evidence.json)입니다. 소유 8874/5244 서버와 두 브라우저 핸들은 관측 후 종료했습니다. 기본 `/tmp` 상태는 보존했으며 공유 상태나 원본 PoC를 초기화하지 않았습니다.

### 담당 S1 실행 증거 — 위 기본 상태와 별도

| 증거 종류 | 명령/입력과 관측 | 근거·제약 |
|---|---|---|
| backend의 실제 CLI·앱 반영 | `prototype/bff/.venv/bin/python prototype/ai-worker/scripts/replay_fixture.py --worker-state /tmp/zoop-ai-doc-backend-worker --bff-state /tmp/zoop-ai-doc-backend`: 4 job ready, job별 replayCalls 2/providerAttempts 0/cost null, import 4 available. 별도 8871의 두 기업 문서 GET 200, A positive/B negative와 요약 claim/citation 제공 | 담당 backend의 관측을 인용합니다. [AI 시스템 계약·실행 기록](../design/ai-system.md)이 최신 정본입니다. 설명서 담당이 같은 전체 흐름을 재실행하지 않았습니다. |
| backend의 기존 outlook 보존 | fresh 3상태의 `replay_outlook_fixture.py`: 저녁 이슈 1개 published/undetermined·worker 1 ready/replay 1/provider 0. 같은 회차는 동일 값·workerJobs=[]; 출근 0이슈는 published/outlook null·workerJobs=[]. 실제 8871 briefing GET도 같은 값을 제공 | [최종 backend 실행 기록](../design/ai-system.md#실행으로-확인한-결과)과 `test_outlook_worker.py`를 인용합니다. 최초 wrong-state mismatch 실패와 최종 fresh-state 성공을 구분합니다. 기존 exact 정책이며 별도 semantic 검증은 null입니다. |
| 공개 계약 수정 후 로컬 확인 | 수정 담당자의 worker 42 passed/BFF 310 passed(기존 warning 1), validator 16 records 및 실제 document/outlook helper 관측을 인용. 문서 helper 4 ready/replay 8/provider 0·4 available; 현재 grant snapshot을 artifact와 별도로 등록 | [현재 AI 실행 기록](../design/ai-system.md#실행으로-확인한-결과). 이전 37/304는 수정 전 baseline입니다. 독립 소스 재검토는 해당 7개 지적과 직접 회귀만 resolved/findings=[]로 보고했으며 UI·S2–7·전체 권한 감사는 범위 밖입니다. 설명서 담당은 이 시험들을 재실행하지 않았습니다. |
| frontend의 실제 BFF·UI 소비 | 초기 8872/5242 관측은 수정 전 이력입니다. `gate2LimitationFollowup`은 수정된 실제 replay helper와 필수 grants import 4 available → UI 1440/390에서 제한 claim 1회 표시, SYNTH-A positive/SYNTH-B negative 및 정확 citation 문맥을 관측. 읽기 후 provider 0/replay 8 유지 | [구조화 실행 기록의 gate2LimitationFollowup](../design/v10/ai-document-runtime-evidence.json), [갱신된 합성 기업 화면](../design/v10/ai-document-company-a-1440-light.png), [기존 실제 기사 null 화면](../design/v10/ai-document-actual-null-1440-light.png). 공개 DTO는 동일하며 actual-null/deny-empty 예전 증거와 DS 정적 예시를 현재 runtime 관측과 구분합니다. |
| 구조도 최종 export | 기존 설치 interpreter/Chrome로 S1 변경만 반영하여 PDF 3페이지와 HTML/SVG/PNG 생성. 실제 PDF 전페이지 이미지에서 한국어·선·상자·승인 경계 확인 | [구조도 설명과 재현 명령](system-architecture/README.md). source-landed 후 생성했으며 전체 테스트 통과나 live 품질 검증으로 읽지 않습니다. |

실제 provider의 분석 품질·비용·출처 라이선스 최종 승인과 S2~7은 미검증/남은 범위입니다. 담당자의 최종 테스트 결과는 각 기록에서 확인하고, 여기의 합성 실행 결과를 운영 준비 완료로 바꾸지 않습니다.
