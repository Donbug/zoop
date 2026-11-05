# 자료 수집부터 출퇴근 브리핑 발행까지

`briefing-auto-chain-v1`은 #541의 자료 수집·native 등록과 #557의 기업별 분석 생산자를 연결한다. 기존 완성 결과 반입(#553), 과거 회원 설정·발행본·평가는 수정하지 않는다. PR 병합이나 저장소 pull만으로 유료 실행이 켜지지 않는다.

## 실행 흐름

| 시점(KST, 매일) | 처리 |
| --- | --- |
| 08:10 / 17:00 | 전날 17:30 이후 / 당일 08:30 이후 자료의 수집·정제·권한 검사·native S2/S3 검증·DB 등록 |
| 마감 전 | 기존 활성 그래프의 모든 값을 보존하는 추가만 CAS로 활성화. 다른 작성자의 그래프 변경 시 중단 |
| 08:30 / 17:30 | cutoff 고정 → #557 선정·기업 영향·조건부 전망·독립 검증·요약. 실제 완료 시각은 생성·발행 시각으로 보존 |
| 발행 후 | 불변 공통 원본과 complete 개인화 후보 풀을 원자 저장. API 개인화 배달 스케줄러가 당시 자격·설정 리비전으로 회원별 결과 저장 |
| 유휴 시간 | 추가 분석이 필요한 개인화 선택 작업을 기존 selected worker로 처리. 같은 DB·공통 예산·현재 권한 사용 |

전용 worker는 30초마다 회차를 확인한다. API의 기존 common scheduler·공통 queue consumer·finite EventBridge task와 동시에 켜지 않는다. 새 API profile `briefing-auto`는 common scheduler를 끄고 허용 목록에 한정한 personal scheduler를 켠다. selected-generation queue는 별도 추가 생성 설정을 켰을 때만 사용한다. profile을 사용하지 않는 기존 동작은 유지한다.

개인화 자동화는 `ZOOP_BRIEFING_PERSONAL_SCHEDULER_MEMBER_IDS`에 등록한 **회원 ID만** 처리한다. 기본값은 빈 목록이며 개인화 초기화·슬롯 자격 기록·배달·완료 처리를 하지 않는다. 이메일이나 `*`를 넣어 전체 회원으로 확장할 수 없다. API profile의 `personal-generation-allowlist-required=true`는 목록 밖 회원의 새 유료 분석과 재시도도 거부하고 기존 조회는 유지한다. 수동 생성 기능을 켜기 위한 `ZOOP_BRIEFING_SELECTED_GENERATION_ENABLED`는 이 profile에서도 기본 false다. 이미 검증한 분석으로 개인화를 조립하는 데에는 새 모델 호출이 필요하지 않다.

전용 worker도 같은 회원 목록을 `personalMemberIds`로 읽는다. selected config와 0600 승인 파일의 `allowedMemberIds`는 API와 동일한 정렬된 ID 목록이어야 한다. worker는 DB 선점 단계와 매 전송 직전 job 소유자를 다시 검사한다. 대기 중인 다른 계정의 작업도 자동으로 실행하지 않는다. 시연 보존 계정은 목록에서 제외하며 실제 ID·이메일·승인 파일은 Git에 넣지 않는다. 회원 목록 변경은 API/worker 설정을 함께 갱신하고 재검증한 뒤 반영한다.

공통 분석은 회차당 한 번 생성하고 개인화는 같은 회차·이슈·입력 SHA의 검증 결과를 재사용한다. 새 분석이 필요한 이슈만 추가 호출하며 아래 회차/일 예산을 **모든 회원과 공통 작업이 공유**한다. 계정별로 예산을 새로 만들지 않는다. 예산이 부족하면 보류하며 근거나 검증을 생략해서 채우지 않는다.

Korea 정책뉴스·보도자료·해명자료의 기사별 KOGL1 **텍스트**를 최대 6페이지·100 HTTP 요청·60개 문서·100MB·360초 안에서 수집한다. 서로 다른 목록의 기사 번호 크기로 중요도를 정하지 않는다. 기업이 제목의 실제 계약·투자·실적·공급·제품·규제 사건에 직접 등장하는지와 사업 행위가 같은 문맥에 있는지를 **입력 검토 순서**에만 사용한다. 중요도·긍부정·선정 여부는 기존 native/독립 검증을 통과해야 한다. 회사명이 QR 도구나 공유 기능으로만 등장한 자료가 실제 사업 발표보다 먼저 처리되지 않게 한다. 짧은 원문이라는 이유만으로 배제하지 않는다.

`BRIEFING_SAMSUNG_NEWSROOM_ENABLED=true`와 별도 `BRIEFING_SOURCE_AUTHORIZATION_REF`가 있으면 삼성전자 한국 뉴스룸의 **직접 제작 텍스트**도 검토한다. [공식 콘텐츠 이용 안내](https://news.samsung.com/kr/%EC%82%BC%EC%84%B1%EC%A0%84%EC%9E%90-%EB%89%B4%EC%8A%A4%EB%A3%B8-%EC%BD%98%ED%85%90%EC%B8%A0-%EC%9D%B4%EC%9A%A9%EC%97%90-%EB%8C%80%ED%95%9C-%EC%95%88%EB%82%B4)를 실제로 확인하고 RSS의 자체 작성자와 기사 byline을 검사한다. 외부 기고·이미지·첨부는 사용하지 않는다. RSS 날짜는 탐색 순서만 정하며, 게시 시각·발행기관·본문은 실제 기사 응답에서 확인한다. 한 feed의 최근 후보 최대3개를 검토해 최대2개를 native 수집·정제하고 전체 입력 후보와 함께 정렬한다. 알 수 없는 게시 시각·미래 게시 시각·회차 밖 시각·정책 변경·접근 거부는 그대로 제외한다. 원문과 인용은 변경하지 않으며 생성 분석은 별도 결과다. 다른 기업 RSS가 접근 가능하다는 이유만으로 처리·공개 권한을 부여하지 않는다.

입력 검토에서는 네이버와 네이버파이낸셜, 카카오와 카카오톡처럼 다른 법인·제품명을 구분한다. 부분 문자열이나 모기업 관계를 기업의 직접 참여 근거로 쓰지 않는다. 같은 문서에 상위 회사명이 따로 등장하더라도 인용 제목만으로 실제 당사자를 바꾸지 않는다. 이 검사는 후보 검토 순서에만 사용하며, 실제 기업 연결은 native·독립 검증이 판단한다.

후보 하나가 품질 보류되면 그 원문 버전의 완료 결과를 보존하고 다음 적격 후보를 검토한다. 다음 후보 처리와 최종 분석에 필요한 예산이 남아 있는지 먼저 확인한다. 전송 불명확·기술 실패는 자동 재전송하지 않으며, 처리 완료·보류 문서는 새 후보로 다시 보내지 않는다. 부분 수집을 시장 전체로 표시하거나 입력 부족을 ‘새 소식 없음’으로 발행하지 않는다.

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
| `ZOOP_BRIEFING_PERSONAL_SCHEDULER_MEMBER_IDS` | 개인화 자동화 허용 ID 목록. 기본 빈 값. API/worker/selected 승인 파일이 동일해야 함 |
| `ZOOP_BRIEFING_SELECTED_GENERATION_ENABLED` | 별도 승인 후 필요한 개인화 추가 분석만 허용. 기본 false이며 공유 예산은 유지 |
| `BRIEFING_SAMSUNG_NEWSROOM_ENABLED`, `BRIEFING_SOURCE_AUTHORIZATION_REF` | 기본 비활성. 직접 제작 텍스트·정책·작성자 검사를 통과한 자료만 추가. 개인화 허용 목록·모델 예산을 확대하지 않음 |
| `BRIEFING_SHARED_PRIORITY_ANALYSIS_ENABLED=true` | 같은 회차·이슈의 독립 검증된 공통 분석을 개인화 후보에 그대로 재사용. 기본 false이며 원래 프롬프트·검증 영수증·digest를 보존 |

설정 검토 후 `--initialize-authority`는 **새 소유 폴더만** 초기화한다. 새 read grant ID는 `briefing-kogl1-auto-v1`로 분리해 종전 `briefing-kogl1-live`도 원래 권한과 함께 보존한다. API의 `ZOOP_DOCUMENT_READ_INGESTION_SOURCES`는 그 폴더의 `serving-delegates.json`, `ZOOP_DOCUMENT_READ_GRANTS`는 `serving-grants.json`, artifact root는 기존 shared artifact root를 가리킨다. `zoop-grant-authority-delegates-1`은 기존 원본과 새 `grants.json`에 위임한다. 철회는 즉시 반영되고 중복 소유·중첩 delegate·읽기 실패는 차단된다. API/worker에는 이 reader가 포함된 동일 검토 버전이 필요하다.

삼성 출처를 추가할 때는 worker 소유의 flat grant 파일에 새 grant ID만 원자적으로 추가한다. 기존 grant의 값이 다르면 덮어쓰지 않고 중단한다. 기존 정책·폐기·철회 기록은 유지한다. API가 새 source registry/근거를 읽으려면 worker의 전용 상태 EFS Access Point를 **읽기 전용**으로 연결해야 한다. API 역할에는 해당 Access Point의 `ClientMount`만 허용하고 `ClientWrite`를 추가하지 않는다. 다른 볼륨·이미지·환경변수·기존 IAM 정책을 유지하며, 실제 읽기 성공과 빈 probe 파일 쓰기 거부까지 확인한다. provider key/DB 자격 증명은 계속 `/tmp`에만 있어 이 마운트로 공유하지 않는다.

새 migration은 추가하지 않으며 선행 PR과 최신 main의 migration이 필요하다. API/Web과 전용 worker는 다른 배포 대상이다. main의 자동 API 배포와 전용 worker·권한·스케줄러 활성화를 구분한다. 이 작업은 실제 배포나 활성화를 수행하지 않는다.

## 일정 변경과 일회성 시험

`ZOOP_BRIEFING_MORNING_TIME`, `ZOOP_BRIEFING_EVENING_TIME`, `ZOOP_BRIEFING_SCHEDULE_EFFECTIVE_FROM`으로 prospective KST 일정을 API와 전용 worker에 동일하게 설정한다. 예: `08:30`, `17:30`, `2026-11-05`. API 설정 응답·다음 설정 적용 시각·자격 관측과 worker 수집 구간이 같은 정책을 사용한다. 기본값은 기존 09:20/17:30을 유지한다. `BRIEFING_AUTO_START_AT`보다 앞선 슬롯은 새 실패 작업도 만들지 않아 활성화 전 회차를 소급하지 않는다. 과거 발행본과 preference revision은 수정하지 않는다.

`ZOOP_BRIEFING_TEST_EVENING_AT`은 명시한 KST 날짜의 퇴근 슬롯에만 적용하는 일회성 시각이다. 다음 날 반복되지 않고 실제 마감·생성·발행 시각이 남는다. 다음 출근의 비교 구간은 이 실제 시험 회차 마감부터 시작한다. 30초 polling으로 해당 실제 마감의 자격을 관측한다. 준비를 마감 10분 전까지 시작하지 못하면 시간을 소급하지 않고 실패로 기록한다.

기존 설정이 새 시간보다 늦은 미발행 미래 회차부터 적용되도록 저장된 경우, 운영자는 대상 회원의 현재 설정을 새 immutable revision으로 이어서 저장한다. 기존 revision·발행본·평가를 덮어쓰지 않는다. 허용 목록 밖 회원의 설정은 변경하지 않는다.

## 시각·품질·호출 한도

날짜만 있는 기사는 `publishedAt=NULL`, 원래 `publishedDate`, 실제 최초 수집 `availableAt`, `eligibilityBasis=first_observed`를 저장한다. 관측 시각을 게시 시각으로 바꾸지 않는다. 마감 이후 관측·미래 게시일은 제외한다. 공통/개인화 카드에 `게시일 … · 최초 수집 …`와 저장된 발행기관을 표시한다. 기존 정밀 게시 시각도 계속 읽는다. 원문 인용·버전·SHA·offset과 현재 권한을 전송 및 조회에서 재검사한다.

기본 설정의 native 최대 **6회**와 생성·검증 10회는 **회차 16회/보수적 USD1, 실행일 KST USD2** 한도를 공유한다. 공유 분석을 명시적으로 켜면 native 최대8회와 공통 생성·독립 검증8회로 같은 한도를 나눈다. 기본 성공 경로는 native5회+공통8회이며 개인화는 검증된 공통 문장을 그대로 투영한다. 새 개인화 AI 생성이라고 표시하거나 원래 common 프롬프트 버전을 바꾸지 않는다. 이 재사용은 선택 회원·선택 종목·회차·이슈·원문 및 검증 digest를 확인하고, 개인화 추가 해석을 작성하지 않는다. 보완·개인화 추가 분석도 같은 한도 내에서만 실행하며 부족하면 보류한다. 전송 불명확 요청은 예약을 유지하고 자동 재전송하지 않는다. 비용은 기준·USD를 가진 추정치이고 청구 근거 없는 실제 비용은 NULL이다. 미확인 전송·토큰도 NULL이다.

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

승인한 당일 미발행 회차만 `--recover-recorded-slot morning YYYY-MM-DD` 또는 `evening`으로 유한 복구할 수 있다. 별도 `BRIEFING_RECORDED_RECOVERY_AUTHORIZATION`이 필요하며 일반 정기 작업에는 넣지 않는다. 기존 실패·requires_recovery 이력, 실행 중 작업 없음, 미응답 없음, 같은 DB writer lock을 확인한다. 기존 수집 결과만 읽고 새 수집을 하지 않으며, 당시 마감 이전에 실제 수집된 원문만 허용한다. 회차의 원래 마감·회원 자격·설정 리비전은 유지하고 실제 생성·발행 시각은 현재 시각으로 남긴다. 마감 뒤 조립된 내부 그래프는 이 명시적 복구 경로에서만 허용하며 관측 시각 검사는 완화하지 않는다. 복구 영수증은 별도 경로에 추가하고 완료된 문서 준비·검증 결과는 재사용한다. 미응답 요청·기존 발행본을 다시 만들지 않는다.

API의 공개 근거 조회는 Java의 현재 권한·artifact 검사를 사용하며 native CLI는 전용 worker에만 필요하다. API 배포는 현재 실행 서비스의 정확한 task definition을 복사해 승인된 EFS 읽기 전용 mount와 기존 환경 설정을 보존한다.

## 검증 범위

`briefingAutoIntegrationTest`는 자체 PostgreSQL schema와 loopback HTTP 기사로 실제 수집기 → S2/S3 → native import → additive CAS → #557 → Java 사용량 원장 → 공통 발행·HTTP → 회원 설정 → 개인화 배달 스케줄러·인증 HTTP를 연결한다. provider wire 응답만 직접 작성한 합성 응답이다. 날짜 precision·기존 그래프 보존·반복 실행 0회·회원 격리·권한 철회를 검사한다. 고정 시각은 test source set에만 있고 운영 Clock는 실제 시각이다.

```sh
PYTHONPATH=scripts:scripts/tests:ai/service/src:ai/pipeline/src python3 -m unittest test_briefing_auto_chain test_briefing_native_intake test_briefing_server_runtime
# Dedicated empty local zoop_company_test_19 / JDK21 / Python3.12 / pinned requirements + freezegun==1.5.5
./api/gradlew -p api briefingAutoIntegrationTest
```

합성 성공은 실제 자료의 품질이나 서버 유료 운영 성공을 뜻하지 않는다. 실제 기사·키·DB·회원·생성 결과는 PR에 포함하지 않으며 이번 작업의 AI 호출·공유 서버 변경·신호·병합·배포는 0이다.
