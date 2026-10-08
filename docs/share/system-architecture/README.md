# 줍 시스템 구조도 · 현재 프로토타입

**[3장 PDF](out/system-architecture.pdf)** · [한눈에 보는 PNG](out/contact-sheet.png) · [단독 HTML](out/system-architecture.html) · [Mermaid 원문](diagrams.md) · [프로토타입 설명서](../prototype-guide.md)

2026-10-08 로컬 구현을 설명합니다. **실선은 구현 경로**, 점선은 선택적 연결·승인 후 실행 또는 본개발 목표입니다. 실선이 전체 수용 기준 통과나 실제 공급자 호출 완료를 뜻하지 않습니다. S1 worker의 실선은 합성 재현·검증 후 앱 반영 경로이며 실제 모델 실행은 별도 source grant·예산 승인이 필요합니다.

문서 공개 계약은 `zoop-document-gate-2`로 수정됐고, 해당 7개 지적과 직접 회귀에 한정한 독립 소스 재검토에서 resolved/findings=[]로 보고됐습니다. 이 그림은 계약 경계·로컬 시연 설명이며 전체 보안 승인이나 운영 안전 보장이 아닙니다.

현재 권한·범위는 [오늘 작업 기준](../day-work-2026-10-08.md)이 우선합니다. 전체 명세와 FS074~081은 팀 합의 요구/설계 대상이고, 원문의 ‘검토 전’을 이유로 요구에서 제외하지 않습니다. 전체 구현 완료와 실 provider 승인·클라우드 배포는 별개입니다. Figma는 폰트를 제외한 최종 목표이고 SUIT를 유지합니다. 현재 화면이 Figma와 일치한다는 보고가 아닙니다.

## 읽는 순서 1 → 2 → 3

1. **전체 시스템**: 사용자는 BFF에서 공개 자료를 읽습니다. 뉴스 생산·관리자 검수·snapshot 공개와 S1 문서 요약/기업 판정 생산·검증 후 반영을 별도로 봅니다.
2. **프론트엔드**: 기업/시점 선택이 URL·공용 상태·조회 key·HTTP·차트/관계 그래프에 전달되는 경로입니다. 저장 문서 분석과 일반 규칙 질문을 구분합니다.
3. **백엔드**: 사용자 공개 조회, 관리자 원장/게시, 브리핑 회차, 별도 S1 worker를 구분합니다. worker ready와 앱 반영/현재 공개 gate는 같은 완료 상태가 아닙니다.

| 장 | 원문 | SVG | 실제 PDF에서 렌더한 PNG |
|---|---|---|---|
| 1 전체 | [01-system.mmd](01-system.mmd) | [01-system.svg](out/01-system.svg) | [01-system.png](out/01-system.png) |
| 2 프론트엔드 | [02-frontend.mmd](02-frontend.mmd) | [02-frontend.svg](out/02-frontend.svg) | [02-frontend.png](out/02-frontend.png) |
| 3 백엔드 | [03-backend.mmd](03-backend.mmd) | [03-backend.svg](out/03-backend.svg) | [03-backend.png](out/03-backend.png) |

### 용어

- **BFF**: 화면용 HTTP 서버입니다. 현재 FastAPI `/api`이며 본개발 `/api/v1`과 다릅니다.
- **snapshot**: 공개한 그래프와 문서·근거를 고정한 버전별 JSON입니다. snapshot이 합성이라는 뜻은 아닙니다.
- **앱 SQLite**: 세션·검수·회차·반영된 분석 결과와 현재 공개 상태를 보관합니다.
- **worker SQLite**: 별도 작업·호출 예약·receipt·불변 artifact를 보관합니다. 앱과 DB를 공유 쓰기하지 않습니다.
- **원장/투영**: 기존 PoC의 PostgreSQL 분석·감사 원장과 Neo4j 진단입니다. 관리자 경계이며 사용자 게시본을 대신하지 않습니다.
- **CLI**: 별도 명령행 프로세스입니다. 새 worker도 원본 PoC도 독립 HTTP 서버로 그리지 않습니다.

## 그림에서 보존한 경계

- React → BFF → 공개 snapshot + 앱 SQLite가 현재 사용자 조회입니다. 브라우저가 PostgreSQL·Neo4j·worker DB에 직접 접근하는 선은 없습니다.
- **일반 질문은 RuleEngine의 규칙 답변과 근거 검증**입니다. S1 생성형 문서 분석 구현을 일반 채팅의 LLM 전환으로 설명하지 않습니다. 일반 브리핑은 선정·검증·시장 HTTP 조회 후 회차를 고정하며 자동 LLM 생성 경로가 아닙니다.
- **S1 worker**는 문서 요약·문서×기업 판정·별도 의미 검증과 **기존 briefing-outlook 생산**을 보존·이행한 네 kind를 제공합니다. versioned JSON CLI와 자체 SQLite를 쓰고, 문서는 `AiWorkerClient` transport → `DocumentAnalysisStore.import_job()` 검증을 거칩니다. 기존 회차는 `judge_outlook.py`가 승인 설정으로 미발행 회차 생성과 원래 발행 경로에 연결합니다. 새 기업·시장 요약은 S5이며 기존 outlook를 미루지 않습니다.
- 사용자 `GET /api/companies/{id}/documents`, `GET /api/evidence/{id}?companyId=...`는 저장 분석만 읽습니다. 미판정은 null이며 `not_requested/pending/failed/withheld/available`을 분리합니다. GET에서 생성·import·usage 증가를 실행하지 않습니다. 시장 공급자 설정 시의 시세 GET에는 외부 HTTP가 있을 수 있습니다.
- worker 입력의 source grant와 결과 provenance를 검사합니다. 작성된 합성 replay는 실제 기사나 실제 provider 결과로 승격하지 않습니다. **문서 분석**은 원문 `[start,end)`와 Unicode codepoint offset 확인 및 별도 claim 의미 검증을 모두 거칩니다. 기존 outlook의 검증 수준은 다음 항목과 구분하며 문서 두 consumer의 현재 gate를 S4 전체 의존성 closure 완료로 확대하지 않습니다.
- 현재 grant snapshot은 artifact와 별도로 등록합니다. `document_analysis.py import --grants`에는 server-owned **전체 현재 목록**이 필요하며 누락 grant는 fail-closed로 제외됩니다. 과거 worker/job의 grant는 영수증이고 현재 권한을 갱신하지 않습니다. 문서 gate-2는 public limitations와 limitation claims의 순서·1:1 대응 및 전체 semantic coverage를 확인하고, 옛 gate-1은 raw 이력을 보존하되 `document_policy_outdated`로 공개 보류합니다. standalone HOLD/REJECT의 save_only는 저장한 own artifact를 재사용하여 provider를 다시 호출하지 않습니다.
- 기존 PoC는 승인된 원문에서 LLM·임베딩·선택적 Jev를 사용할 수 있지만 이번 그림 작업에서 실호출하지 않았습니다. 원본 PoC 추출/SAME/outbox를 재작성하지 않습니다. 중복된 옛 BFF sentiment CLI/client의 live 분기는 worker로 컷오버했고 **기존 outlook provider/replay 생성과 불변 발행 기능을 유지**합니다. 기존 outlook의 exact 참조/금지 표현 정책은 `validation.semantic=null`이며 문서의 별도 의미 검증과 동급으로 표시하지 않습니다.
- 모델명은 그림에 고정하지 않습니다. stage별 모델·추론 수준, current grant, live opt-in, durable 호출 ceiling과 실제 예산 승인은 [AI 시스템 계약](../../design/ai-system.md)을 따릅니다. 실제 `.env`·키·개인정보는 열람하지 않았습니다.
- `/api/v1`은 [목표 OpenAPI](../../api/openapi.yaml)입니다. 현재 운영 보안·멱등·커서 규칙이나 클라우드 배포 완료로 표시하지 않습니다. React/Python은 현재 구현이며 본개발 스택의 필수 선택이 아닙니다.

## 근거와 실행 증거

### 현재 source 경계

| 주장 | 현재 코드/계약 |
|---|---|
| FE 라우트·조회 key·cookie·선택/근거 | `prototype/web/src/{App.tsx,api/queries.ts,api/client.ts,pages/company-page.tsx,features/overlays.tsx}` |
| 문서 요약 표시·claim 근거·provenance 소비 | `prototype/web/src/components/domain/{document-analysis,document-item}.tsx`, 기존 문서/evidence consumer |
| 공개 조회·세션·게시·브리핑 | `prototype/bff/src/zoop_bff/{app,deps,sources,chat,briefing_rounds,graph_versions}.py` |
| 원장/Neo4j 관리자 경계 | `prototype/bff/src/zoop_bff/{admin_ledger,admin_pipeline,admin_jobs}.py` |
| S1 transport·import·현재 공개 gate | `prototype/bff/src/zoop_bff/ai_worker.py`, `sentiment.py`, `routers/market.py` |
| worker CLI·독립 저장·복구·검증 | `prototype/ai-worker/src/zoop_ai/{cli,contracts,runner,store,provider}.py` |
| 언어 독립 JSON·합성 fixture | [AI schema](../../api/ai-contract.schema.json), `prototype/ai-worker/fixtures/contracts/synthetic-document/` |

위 표는 source inspection 근거이며 모든 함수를 이번 그림 작업에서 실행한 결과가 아닙니다. S1 실행 설명과 담당자의 기록은 [AI 시스템 문서](../../design/ai-system.md), 최종 화면 관측은 [v10 구조화 실행 기록](../../design/v10/ai-document-runtime-evidence.json)을 따릅니다.

### 실행을 나누어 읽기

1. **기존 구조도 smoke**: [out/api-observation.json](out/api-observation.json)은 이전 별도 8864 합성 관측입니다. health/OpenAPI/graph/companies 200, v1과 JSON/SQLite hash 대조를 보존했습니다. S1 schema 또는 S1 분석 성공의 증거로 재사용하지 않습니다.
2. **이번 매뉴얼 smoke**: [manual evidence JSON](../prototype-guide-evidence.json)은 8874/5244, `/tmp/zoop-manual-day-20261008`의 기본 합성 조회와 회원/문서 흐름입니다. scheduler·시장·live AI off, source grant registry 미연결이며 기본 그래프는 노드 4·간선 2입니다. 소유 서버와 브라우저 핸들은 종료했습니다.
3. **담당 S1 worker 실행**: backend가 실제 `replay_fixture.py --worker-state /tmp/zoop-ai-doc-backend-worker --bff-state /tmp/zoop-ai-doc-backend`를 실행해 4 job ready, job별 replayCalls 2/providerAttempts 0/cost null, 앱 import 4 available을 관측했습니다. 별도 8871 기업 두 경로는 summary와 positive/negative를 200으로 제공했습니다. 실행 상세·최종 테스트 결과는 담당자 문서가 기준이며 이 그림 작업에서 전체 실행을 반복하지 않았습니다.
   **기존 outlook 최종 증거**: fresh 3상태에서 실제 `replay_outlook_fixture.py`가 저녁 이슈 1개 published/undetermined, worker 1 ready/replay 1/provider 0을 관측했습니다. 같은 발행 회차는 값 불변·workerJobs=[], 출근 0이슈는 outlook null·workerJobs=[]였습니다. 8871 실제 briefing GET도 같은 값을 반환했습니다. 최초 문서 상태 재사용의 `replay_input_mismatch` 실패와 최종 fresh-state 성공은 [backend 최종 실행 기록](../../design/ai-system.md#실행으로-확인한-결과)에 구분되어 있습니다. 불변·재시작·409·SQLite trigger 수용 시험은 `prototype/bff/tests/test_outlook_worker.py`입니다.
   **현재 수정 baseline**: [현재 AI 실행 기록](../../design/ai-system.md#실행으로-확인한-결과)은 수정 담당자의 worker 42/BFF 310·validator 16 records와 actual document/outlook helper 관측을 담습니다. 이전 37/304는 수정 전입니다. 독립 소스 재검토는 해당 7개와 직접 회귀에 한정해 resolved/findings=[]로 보고했으며 UI·S2–7·전체 권한 감사는 범위 밖입니다. 이 그림 담당은 시험을 재실행하지 않았고 전체 보안 승인을 주장하지 않습니다.
4. **외부 미검증**: 실제 provider 품질/비용, 시장 HTTP, 새 원문 수집, 관리자 원장/게시, 실계좌/운영 OAuth, 클라우드 배포는 이번 그림·매뉴얼 smoke의 증거가 아닙니다. 전체 수용 기준 통과로 합산하지 않습니다.

### 내보내기와 직접 시각 확인

전체/프론트엔드/백엔드 **3장**을 이미지·기술 식별 자산·일관된 역할 아이콘 중심으로 재구성했습니다. 실제 최종 PDF에서 렌더한 **1600×1000 PNG 세 장**을 모두 열어 한국어, 역할명, 화살표 방향, 권리/검수 경계와 잘림을 확인했습니다. 주요 역할은 **12 / 10 / 12개**, 작은 보조 객체는 **1 / 0 / 3개**입니다. FE의 FastAPI 식별 자산과 역할명 겹침, 전체의 반환선과 시장 역할명 충돌, BE의 worker 경계 제목과 전달선 충돌은 최종 출력에서 분리했습니다. 앱 실행·모델 호출·전체 수용 시험을 다시 수행한 작업은 아닙니다.

현재 조회는 React → FastAPI `/api` → 게시본/앱 저장 결과입니다. PoC 승인 분석은 관리자 원장/게시 경계에 남습니다. worker 결과는 **작업 전달 → 결과·영수증 → 현재 권리/공개 검증 → 앱 반영**으로 나타내고, worker 자체 DB를 앱 DB와 잇지 않습니다. 요약과 기업별 판정은 **독립 작업**이며 각각 별도 의미 검증을 받습니다. 기존 outlook의 참조 검증은 문서 의미 검증과 같은 수준으로 표시하지 않습니다. 일반 질문은 규칙 기반이며 사용자 조회는 worker를 실행하지 않습니다. 현재 권리 목록은 서버 관리 입력이지 과거 영수증이나 브리핑 회차가 갱신하는 자료가 아닙니다.

기존 `docs/design/tokens.json`과 SUIT Variable을 재사용했습니다. [OFL 라이선스](SUIT-LICENSE.txt)와 변경하지 않은 글꼴 파일을 보존했고 SVG/HTML에는 자산과 글꼴을 data URI로 포함했습니다. 이 Chrome의 PDF 출력은 SUIT에서 렌더한 **Type3 glyph 프로그램**을 담으며, TTF 파일이 그대로 포함됐다는 뜻은 아닙니다. CDN·새 패키지·브라우저 설치 없이 생성했고 최종 렌더의 원격 요청은 0회입니다. Mermaid는 같은 역할/간선의 의미 원문이며 자동 배치는 고정 SVG와 다를 수 있습니다.

#### 그림/문자 비중과 관측 범위

[재현 가능한 렌더 검사](out/visual-verification.json)는 페이지 밖 텍스트·텍스트끼리 겹침·이미지/텍스트 겹침·미포함 이미지 **각 0건**을 관측했습니다. 승인/조건부 선과 현재 선은 별도 스타일이며 `/api/v1`·Java/Spring 후보·배포 미정은 연결 없는 목표 틀에 남깁니다. 권리·공개 여부나 모든 선 교차의 안전성을 자동 증명하는 검사는 아니며 최종 PNG 직접 확인과 함께 읽습니다.

[내용 검사 기록](out/content-verification.json)은 로컬 문서 링크 80개에서 누락 0건, SVG의 이미지 19/14/21개가 모두 data URI인 점, PNG 규격과 현재 도식의 한글 cmap 누락 0건을 기록합니다. maker와 designer에 이어 Main도 최종 세 PNG를 직접 열고 수용했습니다. 글꼴 검사는 같은 기존 SUIT TTF의 현재 저작 문구에 한정하며 모든 한국어 글자의 지원 보장이 아닙니다.

| 장 | 기존 → 최종 문자(공백 포함) | 공백 제외 비율 | 이미지 bbox 면적 | 문자 bbox 면적 |
|---|---:|---:|---:|---:|
| 전체 | 916 → 438 | 347 / 743 = 46.7% | 9.9% | 9.4% |
| 프론트엔드 | 798 → 345 | 278 / 655 = 42.4% | 16.2% | 8.0% |
| 백엔드 | 963 → 494 | 397 / 791 = 50.2% | 6.9% | 10.6% |

집계는 **SVG에 저작한 가시 텍스트**의 Unicode 문자 수입니다. 화면 raster 안의 원래 UI 텍스트는 전후 집계에 포함하지 않으며 [기존 baseline](assets/text-baseline.json)을 보존합니다. 면적은 이미지/문자 bounding rectangle 합계이고 실제 잉크 면적이나 디자인 품질 점수가 아닙니다. 전체/BE의 권리·영수증·독립 저장소·참조 검증 구분 때문에 디자이너의 45% 문자 목표를 초과하며, Main의 **문자 수보다 의미 보존 우선** 결정에 따라 역할을 삭제하지 않았습니다. FE 이미지 면적 역시 권장 20–30%보다 작으나 여백을 이미지로 채우거나 가짜 UI를 만들지 않았습니다.

#### 자산·상표·화면 출처

[자산 manifest](assets/manifest.json)는 사용 자산 **26개**의 원천 URL/로컬 원본, 수집일, 권리·notice, SHA-256, crop 좌표·비례 축소와 현재 기술 연결을 기록합니다. [권리 안내](assets/RIGHTS-NOTICE.txt), React/FastAPI MIT, Lucide ISC 및 Feather 유래 MIT notice, SUIT OFL을 함께 보존합니다. 기술 표지는 식별용이며 제휴·승인·후원을 뜻하지 않습니다. **저작권 허용/CC0는 상표권 양도가 아닙니다.** Simple Icons는 출처 탐색에만 사용했고 그 자산은 배포하지 않습니다. PostgreSQL/Neo4j 로고 재사용 조건이 명확하지 않아 Lucide 역할 아이콘과 실제 기술명을 썼습니다.

- 전체 지도: `docs/screen-plan/captures/D-GRP-01.png`의 기존 게시본 화면 일부입니다. 이번 작업에서 원문/공급자 품질을 새로 검증하지 않았습니다.
- FE 선택·차트·관계: 같은 `D-COM-01b.png`의 삼성전자 화면 crop입니다. 클릭 전후 사진이 아니며, 차트/사건 배치는 가격 인과를 뜻하지 않습니다.
- FE 근거 시트: v10 `ai-document-evidence-1440-light.png`의 **합성 replay** crop입니다. 원래 `SYNTHETIC—not real news` 표시를 남겼고 도식에서도 합성 예시로 구분합니다. 실제 기사 지도/차트와 같은 기업의 전후 장면으로 연결하지 않습니다. 원본 PNG는 변경하지 않았습니다.

긴 코드 경로, `S1`, `gate-2`, `receipt`, source grant 정책은 위의 **그림에서 보존한 경계/근거** 부록에 남겼습니다. 후속 구현 순서는 [다음 작업](../next-work-2026-10-08.md)을 따르며 이 세 장을 S2–S7 완료 보고로 읽지 않습니다.

## 재현 명령

편집 원본은 [diagrams.json](diagrams.json)입니다. `build.py`가 같은 노드/간선에서 Mermaid, Markdown, SVG, 단독 HTML, PDF, PDF 페이지 PNG, contact sheet와 검사 JSON을 생성합니다. 이미 설치된 `playwright/pymupdf/Pillow` 환경과 Chrome 실행 파일만 사용하며, manifest의 자산 hash·notice 누락과 렌더 겹침을 검사합니다.

```sh
# 이 워크스테이션의 기존 도구 경로입니다. 새 설치를 요청하지 않습니다.
/Users/asqi/.cache/uv/archive-v0/2baupm_HDQNxjW_J/bin/python \
  docs/share/system-architecture/build.py \
  --chromium '/Applications/Google Chrome.app/Contents/MacOS/Google Chrome'
```

다른 PC에 기존 도구가 없으면 새 의존성을 자동 설치하지 말고 PDF/HTML을 공유합니다. 매뉴얼의 8874/5244 합성 기동 명령은 [설명서 §5](../prototype-guide.md#5-설치와-안전한-로컬-실행)에 있습니다. 원장·실 provider를 켜는 명령으로 대체하지 않습니다.
