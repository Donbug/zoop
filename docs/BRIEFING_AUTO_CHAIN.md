# 자료 수집부터 출퇴근 브리핑 발행까지

`briefing-auto-chain-v1`은 #541의 자료 수집·native 등록과 #557의 기업별 분석 생산자를 연결한다. 기존 완성 결과 반입(#553), 과거 회원 설정·발행본·평가는 수정하지 않는다. PR 병합이나 저장소 pull만으로 유료 실행이 켜지지 않는다.

## 실행 흐름

| 시점(KST, 매일) | 처리 |
| --- | --- |
| 09:00 / 17:00 | 전날 17:30 이후 / 당일 09:20 이후 자료의 수집·정제·권한 검사·native S2/S3 검증·DB 등록 |
| 마감 전 | 기존 활성 그래프의 모든 값을 보존하는 추가만 CAS로 활성화. 다른 작성자의 그래프 변경 시 중단 |
| 09:20 / 17:30 | cutoff 고정 → #557 선정·기업 영향·조건부 전망·독립 검증·요약. 실제 완료 시각은 생성·발행 시각으로 보존 |
| 발행 후 | 불변 공통 원본과 complete 개인화 후보 풀을 원자 저장. API 개인화 배달 스케줄러가 당시 자격·설정 리비전으로 회원별 결과 저장 |
| 유휴 시간 | 추가 분석이 필요한 개인화 선택 작업을 기존 selected worker로 처리. 같은 DB·공통 예산·현재 권한 사용 |

전용 worker는 30초마다 회차를 확인한다. API의 기존 common scheduler·공통 queue consumer·finite EventBridge task와 동시에 켜지 않는다. 새 API profile `briefing-auto`는 common scheduler를 끄고 personal scheduler와 selected-generation queue를 켠다. profile을 사용하지 않는 기존 동작은 유지한다.

현재 수집 범위는 Korea 정책뉴스/보도자료의 기사별 KOGL1 **텍스트**다. 두 목록 각 1페이지, 최대 50 HTTP 요청·30개 문서·60MB·300초이며, 종목 목록과 관련된 1개 문서만 native 처리한다. 처리 완료·전송 불명확 항목은 자동 재시도하지 않는다. 이미지·첨부·제3자 저작물·권한 미확인 뉴스룸 기사는 제외한다. 부분 수집을 시장 전체로 표시하거나 입력 부족을 ‘새 소식 없음’으로 발행하지 않는다. 범위 확대는 별도 자료·예산 검토가 필요하다.

## 비활성 배포 준비

이미지와 자격 증명이 필요 없는 검사는 [기존 런타임](BRIEFING_SERVER_RUNTIME.md)의 Docker build와 `--check`를 사용한다. 새 opt-in 설정은 다음과 같다. 실제 Secret·DB URL·승인 파일·개인 자료는 Git에 넣지 않는다.

| 설정 | 의미 |
| --- | --- |
| `BRIEFING_SERVER_ENABLED=true`, `BRIEFING_AUTO_CHAIN_ENABLED=true` | 둘 다 필요. 기본 비활성 |
| `BRIEFING_SERVER_ADDITIVE_GRAPH_ALLOWED=true` | 기존 값을 보존하는 추가만 허용. HOLD·상충 필드를 승인하지 않음 |
| `BRIEFING_SERVER_WORK_ROOT` | 전용 durable 0700 경로. 다른 생산자의 상태·예산 폴더 사용 금지 |
| `BRIEFING_SERVER_AUTHORITY_ROOT` | 새 worker 소유 권한 폴더. 기존 소유자 파일은 읽기 전용 |
| `BRIEFING_ORIGINAL_SOURCE_AUTHORITY` | 기존 source authority의 정규 절대 경로. 매번 원본 재검사 |
| `BRIEFING_ORIGINAL_READ_GRANTS` | 기존 flat read grants의 정규 절대 경로. 승인 목록을 복사하지 않음 |
| `BRIEFING_SELECTED_WORKER_CONFIG` | 0600 config. #557 exact-server 승인, 같은 DB/schema·`serverBudgetWork`·`serving-grants.json` 요구 |
| `OPENAI_API_KEY`, `TYPESAFE_API_KEY` | Secret 주입 후 임시 0600 파일로 이동. 이미지·EFS에 키 기록 금지 |

설정 검토 후 `--initialize-authority`는 **새 소유 폴더만** 초기화한다. API의 `ZOOP_DOCUMENT_READ_INGESTION_SOURCES`는 그 폴더의 `serving-delegates.json`, `ZOOP_DOCUMENT_READ_GRANTS`는 `serving-grants.json`, artifact root는 기존 shared artifact root를 가리킨다. `zoop-grant-authority-delegates-1`은 기존 원본과 새 `grants.json`에 위임한다. 철회는 즉시 반영되고 중복 소유·중첩 delegate·읽기 실패는 차단된다. API/worker에는 이 reader가 포함된 동일 검토 버전이 필요하다.

새 migration은 추가하지 않으며 선행 PR과 최신 main의 migration이 필요하다. API/Web과 전용 worker는 다른 배포 대상이다. main의 자동 API 배포와 전용 worker·권한·스케줄러 활성화를 구분한다. 이 작업은 실제 배포나 활성화를 수행하지 않는다.

## 시각·품질·호출 한도

날짜만 있는 기사는 `publishedAt=NULL`, 원래 `publishedDate`, 실제 최초 수집 `availableAt`, `eligibilityBasis=first_observed`를 저장한다. 관측 시각을 게시 시각으로 바꾸지 않는다. 마감 이후 관측·미래 게시일은 제외한다. 공통/개인화 카드에 `게시일 … · 최초 수집 …`와 저장된 발행기관을 표시한다. 기존 정밀 게시 시각도 계속 읽는다. 원문 인용·버전·SHA·offset과 현재 권한을 전송 및 조회에서 재검사한다.

native 최대 **6회**, #557 기본 생성·검증 10회가 공통의 **회차 16회/보수적 USD1, 실행일 KST USD2** 한도를 공유한다. native 기본 성공 경로는 5회여서 합성 전체 검사는 15회다. 보완·개인화 추가 분석도 같은 한도 내에서만 실행하며 부족하면 보류한다. 전송 불명확 요청은 예약을 유지하고 자동 재전송하지 않는다. 비용은 기준·USD를 가진 추정치이고 청구 근거 없는 실제 비용은 NULL이다. 미확인 전송·토큰도 NULL이다.

## 저장과 복구

| 위치 | 내용 |
| --- | --- |
| PostgreSQL `briefing_common_schedule_jobs` | queued/running/completed/requires_recovery. 날짜·출퇴근 조합당 하나 |
| `briefing_attempts`, `ai_executions` | 자료 준비와 생성 시도·단계·전송 영수증. 프롬프트·응답 본문은 사용량 원장에 복사하지 않음 |
| `briefing_rounds`, `briefing_personal_pools` | 공통 발행 원본·표시 결과·complete 후보 풀, digest 결속 |
| `briefing_personal_slot_eligibility`, `briefing_personal_deliveries` | 당시 자격과 prospective 설정 리비전으로 고정한 개인화 발행 |
| `<work>/chain/<round>/` | collection/native/authority/import/activation/cutoff/generation/publication/slot의 immutable started/completed/failed/requires_recovery JSON. 본문·키·회원·모델 응답 제외 |
| `<work>/native/<round>/`, `<work>/<round>/`, `<work>/budget/` | private 수집·검증·native 상태, 생성·영수증, 물리 요청 예약. 운영 중 삭제·reset 금지 |

마감 10분 전까지 준비를 시작하지 못하면 소급 수집하지 않고 `collection_window_missed` 실패 시도(모델 호출 0)를 남긴다. 슬롯 실행은 45분으로 제한된다. PostgreSQL 공통 writer lock은 기존 생산자와 공유한다. 실패·중단 슬롯은 requires_recovery로 남으며 다음 poll에서 모델을 다시 부르지 않는다. 이미 발행 원본과 complete pool이 확인되는 경우만 저장 증거로 completed를 복구한다.

복구 시 journal·attempt·예약·현재 권한·그래프를 확인한다. 기존 발행본 UPDATE, Flyway 이력 수정, DB 복원, 다른 작성자 그래프 되돌리기는 하지 않는다. 유료 재실행은 별도 승인된 새 시도로 검토한다. 종전 `--recover-unpaid-slot`은 증명된 무전송 schema 실패만을 위한 legacy 기능이며 auto-chain에는 노출하지 않는다.

## 검증 범위

`briefingAutoIntegrationTest`는 자체 PostgreSQL schema와 loopback HTTP 기사로 실제 수집기 → S2/S3 → native import → additive CAS → #557 → Java 사용량 원장 → 공통 발행·HTTP → 회원 설정 → 개인화 배달 스케줄러·인증 HTTP를 연결한다. provider wire 응답만 직접 작성한 합성 응답이다. 날짜 precision·기존 그래프 보존·반복 실행 0회·회원 격리·권한 철회를 검사한다. 고정 시각은 test source set에만 있고 운영 Clock는 실제 시각이다.

```sh
PYTHONPATH=scripts:scripts/tests:ai/service/src:ai/pipeline/src python3 -m unittest test_briefing_auto_chain test_briefing_native_intake test_briefing_server_runtime
# Dedicated empty local zoop_company_test_19 / JDK21 / Python3.12 / pinned requirements + freezegun==1.5.5
./api/gradlew -p api briefingAutoIntegrationTest
```

합성 성공은 실제 자료의 품질이나 서버 유료 운영 성공을 뜻하지 않는다. 실제 기사·키·DB·회원·생성 결과는 PR에 포함하지 않으며 이번 작업의 AI 호출·공유 서버 변경·신호·병합·배포는 0이다.
