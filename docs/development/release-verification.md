# 배포 인수·성능·장애 검증 계획

**현재 배포 후보는 선택하지 않았다.** 이 문서는 팀 피드백 F03–F07을 실제 배포 인수와 WBS 검증 작업으로 연결하는 실행 계획이다. 목표 계약 검사, 현재 프로토타입 소스 확인, API 실행, 화면 실행, 운영 부하는 서로 다른 증거다. 문서 작성 중 서버·부하·모델·CI·배포를 실행하지 않았다.

## 1. 현재 버전과 증거의 한계

| 항목 | 현재 확인한 상태 | 배포 인수에서 필요한 증거 |
|---|---|---|
| 마지막 원격 CI | Main이 2026-10-10 새로 확인한 목록에서도 [run 37734731230](https://github.com/Donbug/zoop/actions/runs/37734731230)이 마지막이다. 실제 관측 commit은 `69cc0067af1702dbd660869cecc3009543ad9030`이다. public-config / web / ai-worker success, bff / required-ci failure다. | 후보의 **전체 40자리 commit**, 같은 main SHA의 최신 완료 CI run·attempt·각 required job 결과 |
| 미해결 CI | BFF는 `POC_APP_ID`·`POC_APP_PRIVATE_KEY` 미등록으로 preflight에서 실패했다. 그 run의 BFF 시험은 시작되지 않았다. | private PoC 접근·App key 접근 trust 승인 후 전체 CI success. 실패/skip을 green으로 바꾸지 않는다. |
| 현재 로컬 | Main 인계 기준 HEAD는 `69cc006`이며 S2-1·API v2 등 미커밋 변경과 이번 병행 작업이 있다. 이 문서의 소스 확인도 로컬 working tree 기준이다. 별도 Git 명령으로 재관측하지 않았다. | 선택 시점의 정확한 변경 목록과 commit. 미커밋 파일은 해당 원격 run의 검증 대상이 아니다. |
| 릴리스 버전·배포 대상 | 릴리스 번호, artifact, 운영 대상, 배포 실행은 미선택/미관측이다. 제안된 production 아키텍처 그림은 운영 승인이나 실제 가동 증거가 아니다. | 승인된 버전→commit→artifact hash→실행 대상→관측 결과의 연속된 인수 기록 |
| 선행 로컬 증거 | [API v2 검토](../evidence/api-v2-review-2026-10-08.md) 마지막 절은 contracts/docs 및 합성 스키마 소비 검사를 기록한다. [AI 실행 기록](../design/ai-system.md#실행으로-확인한-결과)은 S1·S2-1의 로컬 합성 실행을 기록한다. | 후보 소스에서 다시 실행한 해당 API·UI·회귀 결과. 과거 353 passed는 이번 로컬 변경 전체의 합격 증거가 아니다. |

위 전체 SHA는 Main의 원격 관측 인계값이며 이 문서 작성자가 별도 원격 명령으로 재확인한 값은 아니다. 원격 운영 등록·키 열람·새 의존성·유료 호출·배포·커밋/푸시는 이 계획의 실행 권한에 포함되지 않는다.

### 증거 유형과 상태 표기

- **계약/스키마:** OpenAPI 설명·security·응답 분기와 JSON Schema 표본의 허용/거절이다. 실제 서버의 조건부 검증이나 HTTP 상태를 증명하지 않는다.
- **소스 확인:** 아래 심볼의 분기를 읽은 결과다. 코드에 시험이 있어도 이번에 그 시험을 실행했다는 뜻이 아니다.
- **API 실행:** 격리 상태의 실제 요청·응답·세션/저장 상태·호출 횟수를 기록해야 한다.
- **UI 실행:** 네트워크와 화면·최신 요청 식별자·늦은 응답 폐기를 함께 관측해야 한다.
- **운영 인수/부하:** 정확한 artifact와 승인된 환경·데이터 범위를 사용한 실행이다. 로컬 fixture smoke로 대신할 수 없다.

아래 `목표 있음 / BFF 차이 / 미실행`은 테스트 실패를 새로 관측했다는 의미가 아니다. 관측하지 않은 결과는 합격·실패로 추정하지 않는다.

## 2. WBS에 연결할 실제 산출물

출처는 [최신 WBS 본문](../evidence/raw/wbs_2026-10-10/01-프로젝트-WBS.csv)의 **XLSX 행 = CSV 논리 레코드**다. 줄바꿈 셀 때문에 텍스트 파일의 물리 줄 번호와 다르다. 아래 날짜·담당은 원본이며, 이 계획이 재배정하거나 완료일을 변경하지 않는다.

| WBS / 행 | 원본 업무·담당 / 기간(2026년) | 이 계획에서 인계할 내용 |
|---|---|---|
| 6.11.1 / 175 | API·스키마 계약 통합 점검 / 팀원 전원 / 10-12–10-20 | F03/F05 조건부 보안·상태/오류·required/nullable 검사와 `/api`↔`/api/v1` 차이 목록. 스키마 결과와 API/UI 결과를 다른 열로 보관한다. |
| 6.11.2 / 176 | 개발·테스트 환경 통합 및 DB 마이그레이션 검증 / 안재현 / 10-12–10-23 | F06 stage env, 실행기·lock·DB별 migration/backup/restore, worker transport와 기동·readiness 증거 |
| 6.11.3 / 177 | 핵심 사용자 시나리오 E2E 검증 / 안재현 / 10-12–10-23 | F03 로그아웃 후 개인정보 제거·지연 응답 폐기, F05 영역별 장애·재조회 UI와 실제 네트워크 |
| 6.11.4 / 178 | 데이터·GraphDB·근거 정합성 검증 / 윤서진 / 10-12–10-27 | 문서/사건/이슈·근거 version과 두 조회 경로 공통 공개 버전, NFS012 저장≠조회 완료 |
| 6.11.5 / 179 | AI 챗봇·브리핑 결과 및 복구 검증 / 김도현 / 10-12–10-27 | NFS003/006/008/009, S1 영수증·무호출 저장 복구와 후속 실제 AI/브리핑 경로. stage별 모델·권한·비용 기록 |
| 6.11.6 / 180 | 성능·장애·예외 처리 검증 / 안재현 / 10-19–10-23 | 아래 측정 원장·p50/p95/max·성공/실패/timeout/누락, F03/F05 장애 주입, NFS007/012의 미정/확정 기준 분리 |
| 6.11.7 / 181 | 결함 수정 및 회귀 테스트 / 팀원 전원 / 10-25–10-28 | case ID별 결함·수정 commit·같은 입력 재검증. Critical/Major 미해결은 인수 보류 |
| 6.11.8 / 182 | 운영 환경(Docker·CI/CD) 배포 / 안재현 / 10-19–10-23 | exact commit·passed required CI·artifact hash·runtime/env·실제 경로(F07)·health·rollback·승인자 |
| 6.11.9 / 183 | 시연 영상 및 발표 PPT 제작 / 팀원 전원 / 10-26–10-28 | 실행한 버전/환경/시나리오가 표시된 시연. 제안 architecture를 실제 배포 화면으로 소개하지 않는다. |

F03 도메인 구현은 회원 `6.2.5` 및 관리자 `6.10.1/6.10.13`, F05는 공급원 `6.5.6`과 기업 조회 `6.6.4/6.7.2`에 연결한다. 이 연결은 위 통합 검증 WBS를 대체하지 않는다. operation별 전체 FE·BE 연결은 [목표 OpenAPI](../api/openapi.yaml)의 `x-zoop`와 생성 추적표를 따른다.

## 3. F06/F07: 경로·모델 설정을 먼저 인수한다

### API 경계와 코드 경로

| 기능 | 현재 Python BFF 경로 / 소스 | 목표 정식 계약 |
|---|---|---|
| 회원 로그아웃 | `POST /api/auth/logout`, `prototype/bff/src/zoop_bff/routers/auth.py::logout` | `POST /api/v1/auth/logout`, `logOut` |
| 관리자 로그아웃 | `POST /api/admin/auth/logout`, `routers/admin_auth.py::logout` | `POST /api/v1/admin/auth/logout`, `logOutAdmin` |
| 최신 시세 | `GET /api/companies/{id}/quote`, `routers/market.py::get_quote` | `GET /api/v1/companies/{id}/quote`, `getCompanyQuote` |
| 회차 그래프 근거 | `/api/briefings/{id}/graph` | `/api/v1/briefings/{id}/graph`, `getBriefingGraphBasis`. F07은 목표 설명의 helper 경로를 이 버전으로 정정한 것이다. |
| 상태 확인 | `GET /api/health`, `routers/system.py::health` | production health/readiness 경로는 대상 구현에서 확정한다. 현 BFF 경로를 Spring에서 가동한다고 가정하지 않는다. |
| AI 실행 | `prototype/ai-worker/src/zoop_ai/{contracts,cli,runner,store,provider}.py`, BFF `zoop_bff.ai_worker.AiWorkerClient` | 언어 독립 JSON seam. Spring 후보도 Python import/worker DB 공유 쓰기 대신 schema·transport·오류/복구 계약을 구현해야 한다. |
| 오프라인 원문 준비 | `zoop_bff.ingestion_cli`, `ingestion{,_contracts,_parsers}.py` | 내부 `zoop-ingestion-s2-1` 프로세스다. `/api/v1` 공개 수집 API나 이미 연결된 admin job이 아니다. |

목표 경로 정정은 현재 BFF의 prefix cutover나 운영 가동을 뜻하지 않는다. F07 확인은 다섯 operation(`getGraph/getCompanyRelation/getCompany/getEvent/getEvidence`) 설명의 회차 helper, 실제 배포 router·프록시·FE client 요청을 각각 대조한다. 목표는 `/api/v1`, 현 프로토타입 consumer는 `/api`라는 사실을 숨기는 alias를 만들지 않는다. 본개발 선택은 [이식 경계](../migration/README.md)를 따른다.

### 공개 가능한 설정 이름·예제값과 활성화 책임

아래는 [`.env.example`](../../prototype/bff/.env.example)와 [AI 설정 이행](../design/ai-system.md#설정-이행과-재현-명령)의 **공개 원본 값**이다. 실제 `.env`나 secret 값은 읽지 않았다. 승인된 운영 모델/effort 값이 정해졌다는 뜻도 아니다. `.env`는 자동으로 로드되지 않는다.

| 옛 설정 → 현재 stage 이름 | 공개 예제의 값 / 전달 경계 |
|---|---|
| `ZOOP_SENTIMENT_MODEL` → `ZOOP_AI_DOCUMENT_SENTIMENT_MODEL` | 현재 예제는 비어 있다. 실제 선택 모델은 별도 승인한다. |
| `ZOOP_SENTIMENT_REASONING_EFFORT` → `ZOOP_AI_DOCUMENT_SENTIMENT_REASONING_EFFORT` | 비어 있으면 provider 요청에서 effort 필드를 생략한다. |
| 옛 회차 sentiment 설정 → `ZOOP_AI_BRIEFING_OUTLOOK_MODEL`, `ZOOP_AI_BRIEFING_OUTLOOK_REASONING_EFFORT` | 현재 둘 다 비어 있다. 문서 판정과 회차 판정은 별도 stage이며 하나의 모델 export를 자동 공유하지 않는다. |
| 새 요약 / 새 의미 검증 | `ZOOP_AI_DOCUMENT_SUMMARY_MODEL/REASONING_EFFORT`, `ZOOP_AI_VERIFY_MODEL/REASONING_EFFORT`도 비어 있다. 문서 live 작업은 생성 stage와 VERIFY 양쪽 설정이 필요하다. |
| provider / endpoint | `ZOOP_AI_PROVIDER=openai-compatible`, `ZOOP_AI_BASE_URL=https://api.openai.com/v1`은 공개 예제다. API key 값은 인수 문서에 싣지 않는다. endpoint와 grant recipient/providerRevision의 일치를 확인한다. |
| live / 호출 상한 | 예제 `ZOOP_AI_LIVE_ENABLED=0`, `ZOOP_AI_GLOBAL_MAX_CALLS=0`. live 활성화에는 명시적 `1`, 양수 durable 상한, stage model, 현재 권리 registry, 별도 전송·비용 승인이 모두 필요하다. 호출 수 상한은 금액 상한의 대체물이 아니다. |
| 격리 합성 smoke | AI 문서 예시의 `ZOOP_QUOTE_PROVIDER=off`, `ZOOP_METRICS_PROVIDER=off`, `ZOOP_BRIEFING_SCHEDULER=0` 및 별도 `ZOOP_STATE_DIR/ZOOP_SNAPSHOT_PATH/ZOOP_COMPANY_CATALOG`를 사용한다. 실제 운영 설정이라고 옮기지 않는다. |
| 인증·배포 설정 | `ZOOP_CORS_ORIGINS`, `ZOOP_COOKIE_SECURE`, 회원/관리자 session 정책·DB/상태 경로는 앱/운영 책임자가 환경별로 확정한다. localhost의 기본값·데모 계정·로컬 DSN을 production 값으로 사용하지 않는다. |

**작업자 책임안:** 윤서진은 stage별 payload·권리·모델 설정 요구와 무호출 복구를 인계하고, 앱 구현 담당자는 세션/오류/consumer mapping을 소유한다. WBS `6.11.2/8` 담당 안재현은 승인된 실행 환경의 설정 주입·기동·배포/rollback 증거를 통합한다. secret 등록·예산·자료권리·배포 권한 승인자는 아직 미정이며 팀이 실재 담당자를 지정해야 한다. 이 책임안은 새로운 팀 합의나 타인의 재배정이 아니다. 옛 export를 명시적으로 제거하고 stage를 분리한다. 런타임 alias·미지원 effort 자동 제거·다른 provider 자동 전송으로 설정 오류를 숨기지 않는다.

### 10/10에 채택한 작업 설계 — 실제 AWS 설정은 미관측

Main은 production 그림의 내부 검토를 바탕으로 다음을 **작업 설계**로 채택했다. 새 팀 회의 합의·프로비저닝·가동 완료를 주장하지 않는다. 합리적인 설계 선택을 다시 사용자에게 떠넘기지 않고, 계정/도메인/비용/credentials처럼 외부 입력·권한이 필요한 활성화만 보류한다.

| 작업 설계 | 6.11.2/8에서 필요한 운영 증거·위험 |
|---|---|
| 같은 origin CloudFront, private S3 OAC, API cache off | 승인 도메인/TLS와 실제 behavior/origin·cookie/Origin/CSRF 전달을 확인한다. API cache로 개인 응답이 공유되지 않아야 한다. 같은 origin도 F03 Origin/CSRF를 면제하지 않는다. |
| 앱→AI 내부 HTTP, App SG만 허용, AI 포트 인터넷 비노출 | production transport의 멱등 submit/status/result와 재접수·timeout/reconcile·receipt 복구를 확인한다. 현재 JSON CLI는 이 내부 HTTP 구현 완료가 아니다. SG/route/host port 실관측이 필요하다. MCP는 선택적 내부 읽기 도구이며 공개 필수 서비스가 아니다. |
| DB schema·쓰기 소유권 분리, RDS session 권위·Redis 선택 cache | app/worker/ingestion/원장의 역할별 권한과 서로의 DB 직접 쓰기 금지를 인수한다. Redis 장애/재시작으로 폐기된 session·철회 자료가 복원되지 않아야 한다. |
| HOLD만 사람 검수→재검증, 브리핑 자동 생성→방식에 맞는 검증→불변 발행 | 매 기사·매 회차 사람 승인 대기를 의무로 넣지 않는다. 검수 허용은 공개가 아니다. 현재 outlook의 exact-only 한계를 강화된 production 검증 통과로 바꾸어 보고하지 않는다. |
| 버전 projection→양쪽 readiness→active pointer CAS + 현재 withdrawal gate | 부분 투영·한쪽 준비 실패·늦은 회차·rollback에서 새/옛 버전 혼합과 철회 재노출을 막는 실행 증거를 확인한다. NFS012 마감은 이 단계들을 포함한다. |
| GitHub Actions 기존 기반, 최소 권한 배포 trust | 새 Jenkins를 전제로 작업을 늘리지 않는다. private PoC App trust와 배포 OIDC/environment 역할은 별도 승인/관측한다. same SHA·immutable artifact와 rollback을 확인한다. |
| Single-AZ RDS여도 DB subnet group은 두 AZ의 subnet, 전체 구성은 HA 아님 | 실제 subnet group·백업/restore·Neo4j 재투영과 현재 deny 적용을 인수한다. 두 AZ subnet만으로 서비스 HA를 주장하지 않는다. 운영 RPO/RTO·보존 기간·egress 비용은 외부 인수값이 필요하다. |

이 선택은 코드/DB 이식까지 자동 승인하지 않는다. 실제 AWS SG·subnet·route·OIDC claim·계정·도메인·비용은 아직 검증하지 않았다.

## 4. F03 로그아웃: 조건별 기대 결과와 현재 차이

대상은 두 로그아웃 endpoint다. 각 HTTP case를 회원/관리자에 각각 실행하고, 분리 case는 두 쿠키를 동시에 가진 browser context에서 실행한다. cookie·CSRF 실값은 결과 파일에 저장하지 않고 유효/불일치 여부와 제거된 **쿠키 이름**만 기록한다. 공통 WBS는 `6.11.1/3/6/7`, 구현 연결은 `6.2.5` 또는 `6.10.1/13`이다.

현재 소스 근거: `routers/auth.py:55–59,120–125`는 세션 폐기·회원 cookie 제거, `routers/admin_auth.py:56–61`은 관리자 폐기·cookie 제거를 선언한다. 이 handler들에 목표 Origin/세션 결합 CSRF 분기는 없다. `test_accounts.py:169–170` 및 `test_admin_auth.py::test_logout_and_audit_trail`은 기본 폐기/반복의 시험 정의이며 이번 실행 증거가 아니다. 목표 조건부 security는 [F03 검토](../evidence/api-v2-review-2026-10-08.md#발견-사항과-처리)와 OpenAPI `logOut/logOutAdmin`에서 확인했다.

| 번호 / 입력·절차 | 기대 결과·부정/복구 판정 | 현재 증거·종류·상태 | WBS / NFS |
|---|---|---|---|
| F03-01 유효 해당 cookie + 허용 Origin + 같은 세션 CSRF | 204, 해당 서버 session 폐기, 해당 cookie만 제거. 보호 API 재호출은 미인증. Idempotency-Key 없이 가능하며 저장 데이터/대화 자체는 삭제하지 않는다. | 계약 있음. BFF 기본 폐기 소스·시험 정의 있음. **전체 조건부 API 미실행**, CSRF 이행 차이. | 6.11.1/3, 도메인 구현 / 001·003 |
| F03-02 유효 cookie, CSRF 누락/다른 값/다른 세션 토큰 각각 | 모두 403 `ACCESS_DENIED`, `retryable=false`. 세션/쿠키를 정상 폐기처럼 처리하지 않는다. 올바른 같은 세션 토큰을 다시 확보한 요청만 F03-01로 진행한다. | 계약/구조 확인. 현재 handler에 해당 검사 없음. **BFF 차이·API 미실행**. | 6.11.1/6/7, 도메인 구현 / 001 |
| F03-03 유효 cookie, Origin 누락 또는 비허용 Origin 각각 | 403 `ACCESS_DENIED`. 올바른 CSRF만으로 우회되지 않는다. 허용 Origin+CSRF 요청으로 복구한다. | 계약 있음. 현 handler 분기에 검사 없음. **BFF 차이·API 미실행**. | 6.11.1/6/7, 도메인 구현 / 001 |
| F03-04 security의 anonymous 대안을 악용하려고 유효 cookie+잘못된 Origin/CSRF 전송 | 204 익명 분기로 downgrade하지 않는다. 403과 원래 session 유지 확인 후 올바른 요청의 폐기를 확인한다. | OR security 설명은 계약 증거뿐이다. **BFF 조건부 이행 차이·API 미실행**. | 6.11.1/6/7 / 001 |
| F03-05 cookie 없음/무효/만료 각각, 이어서 같은 요청 반복 | 204, 해당 cookie만 제거, 다른 session 변경 없음. CSRF 요구/401/409/새 멱등 key 저장을 만들지 않는다. 만료 상태는 격리 clock/저장소로 준비한다. | BFF 기본 반환·관리자 반복 시험 정의 있음. 만료/무효 전체 matrix는 **API 미실행**. | 6.11.1/6 / 001·003 |
| F03-06 회원+관리자 cookie 함께 준비; 회원 폐기 후 관리자 조회, 그 반대도 실행 | 회원 폐기는 `zoop_session`만, 관리자 폐기는 `zoop_admin_session`만 제거한다. 반대 역할 session은 살아 있고 보호 데이터 소유권은 그대로 검증한다. | cookie 상수·별도 handler 소스 확인. **쌍방 동시 cookie API/browser 미실행**. | 6.11.3/6 / 001 |
| F03-07 서버 폐기 뒤 응답을 유실 / 폐기 전 서버 실패 / 상태 조회도 실패 | 응답 미수신이면 session 조회부터 한다. 이미 미인증이 확인되면 로컬 정리·로그인 이동. 유효 session이면 올바른 Origin/CSRF로 재요청. 조회 실패는 성공이나 익명으로 단정하지 않고 개인정보를 재노출하지 않는 실패 안내·재확인을 제공한다. 무한 자동 재시도는 없다. | FS007 논리93–103행의 실패/미수신 규칙과 NFS003 근거. **장애 API·UI 미실행**. | 6.11.3/6/7 / 001·003 |
| F03-08 개인화 응답을 지연시킨 뒤 성공 폐기→다른 회원 로그인; 이전 정상·오류 응답 도착 | 이전 보유/관심/대화·오류가 새 화면을 덮지 않는다. 네트워크 응답 owner/session generation과 화면 상태를 함께 확인한다. 닫기/폐기는 서버 기록 영구 삭제가 아니다. | FS007·NFS001/002 계약 근거. **UI 미실행**. 일반 BFF suite 합격으로 대체 불가. | 6.11.3/6 / 001·002 |
| F03-09 폐기 성공 후 로그인 화면 이동 실패→이동 재시도/시작 화면 접근 | 미인증 상태 유지, 이전 개인정보 재표시 없음, 접근 가능한 로그인 경로 제공. session을 다시 복원하지 않는다. | FS007 예외 처리 계약 근거. **UI 미실행**. | 6.11.3/6 / 001·002·004 |

## 5. F05 최신 시세: 정상 부재와 공급자 장애를 분리한다

테스트는 외부 공급자 실제 호출 대신 기존 adapter injection/`httpx.MockTransport`를 이용한 격리 합성 장애부터 준비한다. 그것은 실공급자·운영 품질 검증이 아니다. HTTP 응답 상태·body·`X-Request-ID`와 upstream 호출 횟수, UI의 재조회 영역을 별도로 기록한다. 공통 WBS는 `6.11.1/3/6/7`, 구현은 `6.5.6/6.6.4/6.7.2`다.

**정렬 전 소스와 이후 실행 보고를 분리한다.** 처음 읽은 `MarketData.quote/TtlCache`와 `get_quote`는 장애를 200 unavailable로 반환하고 역사 selector를 무시했으며 graph dataset에 먼저 의존했다. 이후 MarketFailureAlignment의 2026-10-10 수정 실행 보고(`local://market-failure-runtime-2026-10-10.md`, Main 검토 후 revised)는 실제 `create_app`+TestClient+Toss/Yahoo/Naver MockTransport, 각 행 fresh app/cache로 **46/46 기대 일치**를 기록했다. 이 문서 작성자는 보고를 읽었고 재실행하지 않았다. 외부 network/credentials 없이 격리한 API 정확성 smoke이며 latency·부하·운영 provider proof가 아니다. 현재 결과는 소문자 `source_unavailable/validation_error`와 details 안 retryable을 유지하므로 목표 대문자 code·top-level retryable/requestId·X-Request-ID 계약 전체와 동일하지 않다.

| 번호 / 입력·절차 | 기대 결과·재시도/복구 판정 | 현재 증거·종류·상태 | WBS / NFS |
|---|---|---|---|
| F05-01 관측값 있는 합성 provider, 일부 부가값/시각 누락 | 200 available. 제공된 실제 0은 0, 미제공은 null. `quote.asOf=null`은 현재 시각·차트시각으로 채우지 않는다. 출처·통화/단위·가격 종류·지연을 보존하며 latest를 실시간 보장으로 안내하지 않는다. | API의200/시각null을 확인했다. 최종 실제 브라우저에서 정상 시세와 일부 지표만 표시되고 PBR/EPS 누락을0으로 채우지 않음을 확인했다. [부분 지표 화면](market-proof-2026-10-10-partial-metrics.png). 전체 단위·가격 종류 matrix는 별도 인수다. | 6.11.1/3 / 002·005 |
| F05-02 의도적 off/미설정, 미지원 종목, 정상 응답인데 관측값 없음 각각 | 200 unavailable의 `not_connected/unsupported_symbol/no_data`만 허용. 임의 가격0·최근 차트값·최신시각 생성 없음. 설정/지원 범위가 바뀌지 않은 자료 부재는 무조건 retry 버튼으로 장애처럼 안내하지 않는다. | API 정상 부재3종을 확인했다. 브라우저의200 no_data는 오류 alert 대신 이유만 표시했고1일/1주가 미제공 상태로 구분됐다. [정상 부재 화면](market-proof-2026-10-10-no-data.png). | 6.11.1/3/6 / 004·005 |
| F05-03 공급자 인증 401/403 | 503 `SOURCE_UNAVAILABLE`, `retryable=false`. 200/no_data로 숨기지 않는다. 운영자가 승인 설정/접근 조건을 수정한 뒤 재조회한다. 키 없는 endpoint의403도 접근 거절이며 ‘잘못된 키’로 단정하거나 사용자에게 키 입력을 요구하지 않는다. | 실제 BFF의503 `source_unavailable`/details.auth_failed·retryable=false를 확인했다. 브라우저에서 서버 메시지·재시도 버튼 없음·자동 재시도 없음을 관측했다. [접근 거절 화면](market-proof-2026-10-10-auth-failure.png). 목표 공통 envelope와 설정 수정 뒤 복구는 미인수다. | 6.11.1/6/7 / 004·008 |
| F05-04 network/timeout/429/5xx 각각을 확정 장애로 주입 | 503 `SOURCE_UNAVAILABLE`. 같은 읽기를 다시 할 수 있는 일시 장애만 `retryable=true`; 한도/차단 정책상 불가능하면 false. 0건 성공으로 바꾸지 않는다. 공급자 호출 횟수·timeout을 기록하고 자동 무한 재호출 없음. | API에서503/429의temporary_failure·retryable=true를 확인했다. 브라우저에서 자동 재시도1회와 수동 재조회 요청을 관측했다. [일시 장애 화면](market-proof-2026-10-10-temporary-failure.png). network/timeout 각각의 HTTP matrix와 목표 envelope 전체는 이 smoke의 증거가 아니다. | 6.11.6/7 / 004·007·008 |
| F05-05 HTML 차단/필수 필드 변경/잘못된 형식 | 503 `SOURCE_UNAVAILABLE`, `retryable=false`. 운영 adapter 정렬 전 자동 재시도·가짜 정상가격 없음. 형식 변경을 사용자의 자료 부재로 안내하지 않는다. | API의HTML/shape/token/result·unknown metric code 실패는503 format_changed(false)였다. 브라우저에서 서버 메시지와 재시도 버튼/자동 재시도 없음을 관측했다. 목표 공통 envelope와 adapter 수정 뒤 recovery는 미인수다. | 6.11.1/6/7 / 004·008 |
| F05-06 quote에 `asOf`, `graphVersion` 각각/둘 다/빈 값 전송 | 전달 자체를 422 `INVALID_REQUEST`, `retryable=false`로 거절. 최신 시세로 조용히 처리하지 않는다. selector를 제거한 재조회만 허용. 역사 `/prices` 조건은 별도다. | **타 작업자 API 보고 부분 확인**: `forbidden-asOf/graphVersion` 각각422 `validation_error`. 둘 다/빈 값·제거 후 재조회·목표 INVALID_REQUEST envelope는 별도 인수. | 6.11.1/6/7 / 002·004 |
| F05-07 일시 장애503→동일 기업 quote 재조회 성공; 재조회 중 기업 A→B 변경 후 A의 정상/오류를 늦게 전달 | 허용된 quote 읽기만 다시 실행한다. 개요·차트·재무의 정상 결과는 유지되고 저장/AI 생성은 재실행하지 않는다. 최종 B 조건만 표시하며 A 응답·오류는 폐기한다. | 최종 웹 suite의 부분 장애·늦은 응답 회귀는 통과했다. 브라우저에서는503의 자동1회·수동 재조회 요청만 관측했다. **같은 브라우저에서503→200 복구와 A/B 지연 경쟁까지 전부 재현한 것은 아니다.** | 6.11.3/6 / 002·004 |
| F05-08 활성 그래프 부재, 기업 마스터·시세 공급 가능; 차트 기간/graph pin만 변경 | graph 부재만으로 `VERSION_UNAVAILABLE` 발생 없음. 동일 기업 최신 quote가 역사값으로 바뀌지 않고 관측시각/null 유지. 회사 자체가 없을 때의404와 graph 부재를 구분한다. | target 계약 있음. 현재 `_require_company(state.provider.get(),...)` 의존성 확인. **독립 조회 BFF 차이·API/UI 미실행**. | 6.11.1/3/6 / 002·004 |

**quote 증거로 덮을 수 없는 관련 정렬:** 같은 수정 보고는 metrics/prices를 **각각** 시험했다. metrics known값 전부N/A 또는 유효 빈 목록은200 no_data, nonempty 목록의 code가 전부 unknown/renamed이면503 format_changed/retryable=false, known usable+unknown extra는known만 available이었다. Naver403은503 auth_failed/retryable=false다. prices는 정상 부재200·auth/형식503(false)·503/429 일시 장애503(true), Yahoo 1년 주 단위 및 Toss 주 단위 집계를 보고했다. 이들은46행의 별도 API evidence이며 quote proof에 포함해 부풀리지 않는다. PER/PBR·재무 기간/단위·전체 역사 범위·UI 늦은 응답·실공급자 품질은 미인수다. briefing 시장지표의 Yahoo `history()`401/403 분류와 Toss quote 보조 조회 실패 시 전체 실패는 보고의 잔여 범위다.

## 6. 부하·시간·오류 측정: 원본 기준과 작업자 실험값

### 원본이 확정한 것과 비어 있는 것

[비기능 상세](../evidence/raw/functional-spec_2026-10-10/12-비기능-상세.csv) **논리91–103행(NFS007)**은 동일 환경·구간·데이터 규모·동시 요청·표본을 기록하고 성공 표본의 p50/p95/max와 성공/실패/timeout 건수를 재현하도록 한다. 동시 사용자 수, 응답시간 목표, 오류율 한도, warmup/기간/timeout/표본 수는 숫자가 없고 목표 미정 상태의 성능 합격을 금지한다.

**논리161–173행(NFS012)**은 KST 05분 예정 회차→10분, 35분→40분에 **두 새 조회 경로**에서 같은 공개 버전의 유효 결과를 확인하도록 한다. 시작 지연으로 마감을 연장하지 않는다. 저장 완료·한쪽 준비·정상0건/검증 탈락0건/실패0건을 혼동하지 않는다. 기사 수·길이·분석 대상·동시 처리의 승인된 운영범위는 숫자가 없다. 이 기한은 브리핑 생성·이미 열린 화면 자동 갱신의 기한이 아니다.

### 먼저 가능한 로컬 측정 준비 실험 — 작업자 결정, 운영 수용 기준 아님

다음 값은 **측정 원장·장애 분류·시연 반응성을 확인하기 위한 보수적 작업자 로컬 수용안이며 아직 실행하지 않았다.** 팀 합의·NFS 원문 수치·production SLO/capacity가 아니다. 작은 fixture와 짧은 구간으로 외부 부하/과금 없이 재현성을 먼저 확보한다. 로컬 반응성에만 아래 p95 기준을 적용하고 NFS007의 미정 운영 목표를 임의 확정하지 않는다.

| 조건 | 제안하는 로컬 실험 값·범위 |
|---|---|
| 동시 사용자 / 동시 요청 | 읽기 사용자 `C=1→5→10`, 사용자마다 in-flight 1개, 완료 뒤 think time 1초. 단계별 조건을 섞지 않는다. 세션은 사용자별 분리한다. 읽기 실험으로 로그인/AI 쓰기 처리량을 추정하지 않는다. |
| 기간·반복 | C별 warmup 60초 제외 후 300초 측정, 같은 입력·환경으로 2회 반복. warmup 실패도 별도 기록한다. 표본이 20개 미만인 구간은 p95 대표성이 낮다고 명시하고 전체 capacity 결론을 내리지 않는다. |
| 로컬 데이터 | 합성 기업20, 문서100(본문 code point 1,000/5,000/10,000 길이를 40/40/20개), 사건100·분석 주제20·관계200을 계약이 지원하는 범위에서 준비한다. corpus hash, 정확한 실제 개수·길이분포·대상 수를 먼저 기록한다. 현재 별도 주제/관계 생산·GraphDB 투영이 없으면 해당 journey는 **미구현으로 보류**하며 가짜 runtime으로 대체하지 않는다. |
| read 입력 | graph/기업 상세/문서/근거/quote의 고정 합성 ID 목록을 순환한다. 경로별 횟수를 분리하고 cache cold 최초 결과와 warm 결과를 섞지 않는다. 외부 quote·metrics·scheduler off 또는 승인된 합성 transport만 사용한다. |
| 로컬 반응성 한도(작업자 수용안·미실행) | 비AI 일반 읽기 p95≤1초, graph/timeline p95≤2초, 실제 구현된 비동기 job 접수 p95≤1초. 읽기 숫자는 HTTP 요청→body 수신, 접수 숫자는 요청→유효 접수 응답으로 측정한다. browser 결과 표시는 별도 NFS007 구간으로 보고한다. 접수 성공은 답변 완료가 아니다. 작은 합성 데이터의 시연 대기·폴링 시작을 우선 확인하려는 기준이며 실제 LLM 완료 목표는 모델/비용 결정 전 미정이다. |
| timeout | 일반 HTTP 관측 종료 10초, AI replay 관측 종료 120초. 이는 클라이언트 실험 한계이며 운영 timeout·서버 작업 취소·미등록/재실행 판정이 아니다. timeout 표본을 성공 통계에서 제외하고 기존 job 상태만 조회한다. |
| AI/브리핑 준비 smoke | 실제 구현된 S1 replay만 한 번에 유효 job1개로 최소20작업을 관측한다. 기존 outlook은 미발행 출근/퇴근 최소2회차와 정상0건·저장 복구를 구분한다. 합성 receipt·modelCalls=0을 확인한다. 일반 AI chat·강화 브리핑 미구현을 S1 replay로 합격시키지 않는다. |
| 갱신 fixture 관측 | future 공통 공개 경로가 실제 구현되면 05/35 예정 회차별 두 조회를 5초 간격으로 확인한다. 이 간격은 로컬 harness 제안이지 운영 승인값이 아니다. 최초 실제 관측시간을 저장하며 마감 뒤 관측을 기한 내 완료로 소급하지 않는다. |

**측정 방법:** browser 구간은 동일 브라우저·viewport·네트워크 조건에서 monotonic clock으로 시작/끝 event를 저장한다. 서버 처리와 브라우저 표시 시간을 별도 열로 둔다. (1) 화면 진입→첫 유효 영역 표시, (2) 영역 요청→현재 조건 결과 표시, (3) 질문 접수→검증·앱 저장된 답변 표시, (4) 브리핑 회차 시작→발행 가능 저장 완료를 NFS007대로 측정한다. worker ready나 HTTP202를 (3)/(4)의 끝으로 사용하지 않는다. CLI S1만 측정하면 ‘worker 구간’으로 따로 보고한다. NFS012는 예정 시작→두 새 조회 확인을 추가 측정하며 (4)와 합치지 않는다.

표본 원장은 `runId,caseId,commit,artifactHash,environmentId,corpusHash,journey,userOrdinal,requestId/jobId/roundId,conditions,startEvent,endEvent,startMonotonic,endMonotonic,durationMs,httpStatus,expectedOutcome,actualOutcome,timeout,missing,graphVersion,observedAt`을 보관한다. OS/CPU/RAM·runtime/lock·서버 worker 수·브라우저 version·viewport·실제 네트워크·DB/인덱스/데이터량·cache 상태를 run metadata에 기록한다. cookie/token·개인정보·provider 원문·비밀 설정은 원장에 넣지 않는다.

**계산과 판정:**

1. 시작한 전체 표본 `N = S + F + T + M`을 맞춘다. `S`는 기대한 완료를 확인한 성공, `F`는 예상과 다른 실패, `T`는 관측 timeout, `M`은 기록 누락이다. 장애 주입에서 기대한403/503/422는 정상 부하 표본과 분리하여 ‘case 기대 일치’로 판정한다. 성공2xx라도 잘못된 데이터는 F다.
2. 정상 읽기 run의 오류율은 `(F+T)/N ×100%`, timeout율은 `T/N ×100%`, 누락률은 `M/N ×100%`로 각각 공개한다. M>0이면 측정 불완전이며 낮은 오류율을 성능 합격으로 사용하지 않는다. 완료 throughput은 `S/측정초`, 실제 시작 요청률도 별도로 기록한다. closed-loop 결과를 무제한 유입 처리량으로 해석하지 않는다.
3. S의 duration을 오름차순 정렬해 nearest-rank `p50=x[ceil(0.50S)]`, `p95=x[ceil(0.95S)]`, `max=x[S]`를 계산한다(1-based). S=0은 null, timeout을 timeout 한도의 성공값으로 대입하지 않는다. 같은 원장 재계산 결과·건수·hash가 일치해야 한다.
4. **작업자 로컬 수용 gate(제안·미실행):** `M=0`, 원장 합계·재계산 일치, 정상 fixture run에서 `F+T=0`, 위 endpoint군별 p95 한도 충족, 모든 필수 fault case 기대 결과 일치가 필요하다. 구현된 journey만 판정하고 누락 journey는 보류로 남긴다. 조건을 못 맞추면 원인과 결과를 인계하고 다음 C단계로 올리지 않는다. 통과해도 NFS007의 운영 성능/실제 LLM 완료/운영 용량 합격이라고 쓰지 않는다. p50/max·browser 표시 시간도 숨기지 않고 보고한다.
5. **운영 성능 gate:** 승인권자가 실제 환경·예상 운영량·C/요청률·duration·timeout·구간별 latency 한도 `L50/L95/Lmax`·오류율 한도 `E`를 확정한 경우에만 `M=0 ∧ 각 구간 p50≤L50 ∧ p95≤L95 ∧ max≤Lmax ∧ (F+T)/N≤E ∧ 정합성/fault 필수 case 모두 통과`로 판단한다. 하나라도 미정이면 **측정 가능성 결과만 제출/성능 최종 판정 보류**다. 승인값은 실행 전 기록해 결과를 보고 유리하게 바꾸지 않는다.
6. **NFS012 운영 gate:** 승인 범위의 각 정상05/35회차에서 두 확인시각 모두 해당10/40분 이하이고 같은 공통 공개 버전·회차·현재 조건·유효 결과가 확인돼야 한다. 정상0건은 두 경로의 기존 유효 버전·0건 사유·회차 확인시점·기한을 확인한다. 실패/보류/관측누락/부분성공은 정상 완료가 아니다. 운영범위 미확정 또는 S2-1만 실행한 상태에서는 이 gate를 완료로 선언하지 않는다.

**중단 조건:** 예상하지 않은 외부 통신/모델 과금·실데이터·권리 미확인·공유 상태 쓰기·개인정보 기록·중복 생성/미검증 공개·최신 버전 되돌림을 발견하면 실험을 중단한다. 승인된 외부 테스트는 공급자 rate limit·모델 비용/금액 ceiling·데이터 전송 권리·대상 환경을 먼저 고정한다. 지금은 full load를 실행하지 않는다. 로컬 fixture smoke → 승인 테스트 환경의 capacity → 승인된 실제 공급원/AI 비용·품질 시험을 별도 인수한다.

## 7. 실제 릴리스 선택 이후 수행할 인수 순서

다음 순서는 계획이며 완료 기록이 아니다. 기존 [GitHub 수동 등록](github-setup.md#private-poc-읽기-등록)의 권한 경계를 그대로 사용한다.

1. **운영 선행조건을 확정한다.** FE/앱 BE/AI 스택·실행기/버전, 계정·지역·서비스·도메인/TLS, 역할/승인자, 자료/모델 권리·비용, 로그 보존/열람, DB·GraphDB·worker/ingestion 상태 분리와 백업 보존 정책을 기록한다. Docker·Spring·Neo4j 그림만으로 선택/기동 완료라고 쓰지 않는다.
2. **private PoC trust를 먼저 승인한다.** same-repository PR 작성자 전원의 PoC/App private key 접근 허용과 회수/회전 책임을 실재 handles로 기록한다. 미승인자는 CODEOWNERS/merge review만으로 credential 접근이 격리된다고 가정하지 않는다. 관리자만 필요한 App/secret·ruleset 등록을 수행하며 CI App에 배포 권한을 추가하지 않는다.
3. **불변 후보를 고정한다.** 릴리스 이름과 full commit을 정하고 같은 SHA의 최신 CI push run/attempt에서 public-config/web/bff/ai-worker/required-ci가 모두 success인지 확인한다. 로컬 미커밋 결과·다른 SHA·과거 success·skipped는 대체 증거가 아니다.
4. **artifact를 검증한다.** [release-artifacts](github-setup.md#release-artifacts는-배포가-아닙니다)의 실제 run, manifest commit/CI run, ZIP·manifest·파일별 SHA-256을 대조한다. 그 ZIP은 운영 설정·데이터·PoC/venv를 포함하지 않는 준비 산출물이다. 배포 대상별 실행 이미지/wheel/static 자산과 runtime/lock provenance를 별도로 고정해야 한다. 이 문서에서 임의 artifact hash를 만들지 않는다.
5. **승인된 테스트 환경에 기동·migration·복구를 인수한다.** DB별 사전 backup hash/시각·schema version, restore 시험 결과와 migration 전후 값/참조를 기록한다. 서비스 역할별 접근과 최소 권한, state volume/permissions, env 이름·공개값 변경·secret version 식별자(값 아님), health/readiness와 실제 `/api` 또는 `/api/v1` 요청을 확인한다. BFF `/api/health`는 실패도200이므로 HTTP200만 보지 않고 `status/source.connected/graphVersion`과 필수 조회를 확인한다. production readiness 기준은 대상에 맞춰 별도 확정한다.
6. **API/UI/fault/measurement 증거를 묶는다.** F03/F05 번호별 실행 입력·expected/actual·timestamp·sanitized request/response·로그와 UI 관측을 연결한다. F06 stage env와 grant가 실제 승인 boundary 안에서 주입되었는지, F07 프록시/client/router 요청 경로가 일치하는지 확인한다. 안재현의 6.11.6 원장과 윤서진/김도현의 데이터·AI 복구 증거를 같은 commit으로 연결한다.
7. **rollback을 실환경과 같은 승인 대상에서 확인한다.** 이전 승인 artifact/hash·config/schema/active graph pointer를 지정하고 새 쓰기 보존/구 decoder 호환을 먼저 확인한다. migration이 비가역이면 단순 이전 binary 기동을 rollback으로 주장하지 않는다. 트래픽/쓰기를 통제한 뒤 승인 절차로 복원하고, 권리 철회/deny와 worker 호출 원장을 과거 backup으로 되돌려 재공개·이중과금하지 않는지 확인한다. 실패 주입 후 이전 유효 버전의 양쪽 조회·인증·무호출 저장 복구 결과를 남긴다. 근거가 없으면 인수 보류다.
8. **배포 담당자와 승인자가 판정한다.** 필수 case·required CI·hash·health/readiness·backup/rollback 증거가 일치하고 Critical/Major가 해결됐을 때만 해당 대상의 인수를 승인한다. 공개/유료/권한 승인이 없으면 로컬에서 준비 가능한 계약·합성 검증은 진행하되 외부 활성화만 보류한다.

인수 기록 필수 필드: `releaseVersion`, `fullCommit`, `dirtyChangesExcluded`, `ciRunUrl/attempt/checks`, `artifactManifest/sha256`, `deployTarget/roles/approval`, `runtime/lock/schemaVersions`, `actualApiPaths`, `envNameChanges/configOwner/activationApproval`, `health/readinessEvidence`, `F03/F05/F06/F07CaseResults`, `measurementRunIds/approvedThresholds`, `backupRestoreEvidence`, `rollbackArtifact/steps/result`, `knownGaps`, `acceptor/date`. 미정은 미정으로, 미실행은 미실행으로 남긴다. 계획을 채웠다는 이유로 인수 완료를 표시하지 않는다.

## 8. 원본 적용과 이번 문서의 확인 범위

- 최신 기능 입력은 `functional-spec_2026-10-10`, WBS는 `wbs_2026-10-10`, 요구사항은 전 셀이 unchanged인 `requirements-sheet_2026-10-06`이다. [재확인 증거](../evidence/raw/refresh_2026-10-10/_source-analysis.json)의 exact NFS/WBS 값을 사용했다. CSV 행 인용은 논리 레코드이며 NFS001은9–19, 002는23–33, 003은37–47, 004는51–61, 005는65–75, 006은79–89, 007은93–103, 008은107–117, 009는121–131, 012는163–173행이다.
- F03의 사용자 흐름은 회원가입·로그인 시트 FS007 ID93/필드94–103행, F05는 외부 연동 시트 FS063 ID37/필드38–47행과 목표 계약 정정에서 연결했다. CSRF·503·역사 selector 거절은 작업자 목표 계약 정정이며 원본에 없는 수치를 팀 합의처럼 쓰지 않았다.
- 최신 WBS의 `6.11` 종료10-28·AI복구10-27·회귀/발표10-28을 적용했다. 상단의 기능통합10-29·수행기간11-05·개발완료11-06과 충돌하는 사실은 원본 정정 대상으로 보존한다. 현재 6.11.*를 옛 번호의 다른 업무에 연결하지 않는다.
- 이번 작성자는 원본 행·공개 예제·현 handler/provider·기존 시험 정의와 선행 실행 기록을 읽었다. F05 일부의46행 API smoke는 별도 작업자의 수정 후 보고를 읽어 인수했으며 직접 실행과 구분했다. Git/원격 재실행, build/lint/tests/formatter, 서버·browser·full load·배포·유료 모델은 이 작성자가 실행하지 않았다. 미인수 case와 수치 실험값은 계획으로 남아 있다.

### 10/10 Main의 최신 통합 실행 인계

Main은 market 정렬 후 `prototype/bff`에서 `env PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=src .venv/bin/python -m pytest tests -q -p no:cacheprovider`를 실행하여 **380 passed, 기존 Starlette warning 1개, 64.45초**를 관측했다(`artifact://4362`). 이어 웹 전체 `pnpm test`는 **20파일·110개 통과**였다. 프론트엔드 담당자의 최종 app/test TypeScript 검사와 Vite build도 통과했고 기존 chunk 크기 경고는 남았다. 이들은 로컬 소스의 회귀 결과이며 원격 CI·운영 배포·부하·실공급자/LLM 품질·비용 증거가 아니다.
 
최종 BFF를 격리 합성 snapshot과 loopback fake provider로 실행하고 HTTP `/openapi.json`을 새로 관측했다. 그 관측에서 생성한 웹 타입은 현재 `schema.d.ts`와 동일했고 Main의 `bff-types-check`도 drift 없이 통과했다. API/문서 생성 검사에서는 **276개 산출물 drift 없음, hard error0, XLSX10시트·46,826셀 일치**를 확인했다. 원문/이행 경고와 목표-BFF 차이387건은 보존했다. `make public-check`는 기존 검증과 별도로 새 문서 의미/예외 회귀 **17개**를 같은 의존성 환경에서 실행하며, 기존 저장소 tooling 시험17개도 통과했다. 역사 정의가 새 번호의 다른 기능으로 연결되거나 미선언 예외로 누락 연결을 숨기지 못하도록 검사한다.

화면 증거는 [합성 출처·파일 해시 기록](market-proof-2026-10-10.json)과 다섯 PNG로 보관한다. Main이 파일을 직접 열어 부분 지표, 1년 주 단위, 정상 부재, 접근 거절, 일시 장애를 확인했다. [1년 주 단위 화면](market-proof-2026-10-10-weekly-year.png)은 주 버킷·주별 종가 표시를 보여 준다. 최초 브라우저 screenshot의 `path` 옵션은 저장되지 않아 inline 관측만 남았으며, 여기 링크한 다섯 파일은 Puppeteer로 다시 저장하고 실제 존재·해시를 확인한 파일이다. 추천 제거의 desktop/mobile 흐름은 브라우저 DOM·네트워크·저장 결과로 확인했고, 영속 화면계획서에는 D-WAT-01/01b 재캡처를 사용한다. 존재하지 않는 임시 screenshot 경로를 증거로 쓰지 않는다.

실행에 사용한 소유 BFF/fake-provider/Vite 서버·브라우저는 종료했고 임시 상태·fixture·build·schema dump는 제거했다. F03 보안 이행, F05 목표 공통 오류 모델·graph 부재 독립성, 실공급자·운영 capacity와 S2 이후 전체 기능은 별도 범위다. 커밋·푸시·배포·공유 시트 변경은 수행하지 않았다.
