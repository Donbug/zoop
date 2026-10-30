# 개인화 브리핑의 사전 설정과 회차 고정 (D-BRF-01/02)

처음 이용한 회원은 보유·관심 종목을 중복 제거해 기본 종목 설정을 자동 저장한다. 둘 다 없으면 설정·브리핑·AI 작업을 만들지 않는다. 기존 설정이 있으면 그대로 유지한다. 회원은 화면 위에서 기준 종목을 변경할 수 있으며 이슈 수 추가 설정 UI는 제공하지 않는다. 핵심 최대3개/최소 강제 없음/같은 기업의 독립 사건 허용 정책을 고정한다. 종목 선택기는 검색창 클릭/포커스 시에만 열고, 회사 카탈로그의 로고를 공용 CompanyLogo로 표시한다. 로고가 없거나 실패하면 이름 첫 글자를 표시한다. 기본 설정은 초기 한 번만 만들며, 계좌·관심 종목이 이후 바뀌어도 이미 저장한 선택을 덮어쓰지 않는다. 수량·계좌정보를 모델에 보내지 않는다.

설정 저장은 AI 생성 요청이 아니다. `briefing_personal_preferences`는 불변 revision 이력이다. 서버 시각(Asia/Seoul) 이후의 첫 09:20/17:30에 효력이 생긴다. 경계 시각에 저장한 변경은 그다음 회차다. 저장 충돌은 expectedRevision으로409 처리한다. 설정한 기업 목록 자체를 이후 보유 계좌 변경으로 조용히 바꾸지 않는다.

`briefing_personal_deliveries`는 회원·공통 회차마다 한 번만 확정한다. 해당 회차의 예정 시각 이전에 저장되고 effectiveFrom이 도달한 가장 최신 설정을 선택한다. 발행이 지연돼도 뒤늦게 저장한 변경을 이미 시작한 회차에 적용하지 않는다. 선택 종목·설정 revision·후보/시세/회차 기준·선정 스냅샷은 고정하고 PASS 결과를 한 번만 저장한다. 회원이 설정을 바꾸거나 새로고침해도 이미 나온 개인 브리핑은 수정되지 않는다. 현재 원문 권리 철회·제공 중단·정정은 별도 조회 제한으로 유지하며 기록을 바꾸지 않는다.

## API

- POST `/api/v1/briefings/personalization/settings/initialize`: 회원·CSRF 필수. 보유·관심 기본 설정의 멱등 초기화이며 AI 호출은 하지 않는다.
- GET/PUT `/api/v1/briefings/personalization/settings`: 회원 전용/no-store/Vary Cookie. PUT `{choice:{companyIds,maxIssues,minIssues,perCompanyLimit},expectedRevision}`. 응답에는 preference revision/choice/savedAt/effectiveFrom과 schedule/timezone/demoEnabled.
- GET `/api/v1/briefings/{id}/personalized/delivery`: 저장된 회차 조회만. 새 선택·AI 호출 없음. 아직 없으면 `not_published`, 생성 중 `generating`. 원 발행문/평가는 유지한다.
- POST `/api/v1/briefings/{id}/personalized/demo`: `{preferenceRevision}`. 명시적으로 활성화한 데모에서만 현재 설정으로 과거 회차를 시험하며 scheduled 발행과 별도 보존한다. GET `delivery?demo=true`로 재조회한다.

정식 경로는 화면의 실행 버튼이 아니라 서버 dispatcher다. `zoop.briefing.personal-scheduler-enabled=true`로 활성화하면 공통 회차와 적격 후보 풀이 준비된 뒤 설정을 고정하고 공통 AI 생성 작업을 연결한다. 공통 09:20/17:30 생성 **시작** 시각이 즉시 발행 완료를 보장하지는 않는다. 서버는 먼저 처음 이용하는 활성 회원의 기본 설정을 페이지 방문 없이 준비한다(100명씩 순환). 정시 cron에서 활성 회원별 보유·관심 종목 유무를 별도 불변 슬롯에 기록한다. 둘 다 없으면 해당 회차를 건너뛰며 공통 발행 지연 중 종목을 추가해도 소급 생성하지 않는다. 정시 유효 자격이 있으면 이후 종목을 삭제해도 이미 시작한 해당 회차의 저장·완료를 계속할 수 있다. 관측 허용 범위는 예정 시각부터2분 미만이다. 그 범위를 놓친 회차는 당시 종목 상태를 추측해 생성하지 않는다. 이후30초마다 완료된 공통 회차·후보 풀과 자격을 확인하는 publication 후속 dispatcher다. 모델 작업은 기존 `briefing_selected_generation.py` 별도 워커/승인 예산으로 실행한다. 두 프로세스는 별도 운영 관리가 필요하다.

`zoop.briefing.personal-demo-enabled`는 기본false다. false이면 미리보기 UI/POST와 기존 수동 generations/retry POST를 차단한다. scheduler는 내부 서비스로 생성 작업을 넣으므로 사용자 클릭에 의존하지 않는다. 모델 전송 플래그 `zoop.briefing.selected-generation-enabled`와 워커의 현재 권리/비용 보호도 유지한다. 운영 배포·스케줄러 활성화는 별도 절차이며 코드 추가만으로 운영 서버가 켜지는 것은 아니다.

데모에서는 현재 저장한 설정으로 과거 자료를 미리 볼 수 있지만, 이를 당시의 정식 개인 발행본으로 소급 기록하지 않는다. 기존 개인화 생성 기록과 공통 발행·평가·AI 영수증은 그대로다. 적격 후보 부족/분석 보류를 정상 결과로 속이지 않으며 최소 희망 수로 강제 채우지 않는다.


## 서버의 공통 정시 예약과 배포 연결

`zoop.briefing.common-scheduler-enabled=true`는 Asia/Seoul의09:20/17:30에 `briefing_common_schedule_jobs`에 회차를 한 번만 예약한다. 서버 재시작 시 당일 이미 지난 슬롯만 보충하며 미래 시각은 예약하지 않는다. 입력 구간은 전날17:30→오늘09:20, 오늘09:20→17:30으로 고정한다. 사용자 페이지 방문이나 버튼으로 이 작업을 시작하지 않는다. 주말 포함 매일 슬롯이며, 거래일·휴장 판단은 기존 입력/수집 정책에서 처리한다.

실제 공통 수집→선정→AI 생성·검증→발행은 `scripts/briefing_common_schedule_worker.py`의 별도 서버 프로세스로 연결한다. 비공개0600 JSON 설정에 `enabled:true`, `dsn`, `producerCommand`(shell 문자열이 아닌 실행 인자 배열), `producerTimeoutSeconds`를 둔다. 인자 자리표시는 `{roundId}`, `{date}`, `{edition}`, `{windowFrom}`, `{cutoff}`다. `producerCommand`는 **배포 환경의 실제 공통 생성/검증/발행 실행기**를 지정해야 한다. 기존 로컬 DB 재생·예제 실행기를 운영 실행기로 대체 사용하지 않는다. 이 PR은 정시 큐와 소비자 연결을 제공하며, 운영 수집기·키·예산·발행 권리/그래프 승인·실행기 배치는 배포 시 연결해야 한다. 실행기 미설정이면 시작을 거부한다.

소비자는 `FOR UPDATE SKIP LOCKED`로 한 작업을 점유한다. 공통 발행 원문 SHA·회차/마감/입력 구간·전체 적격 후보 풀과 발행본의 SHA 연결을 DB에서 확인해야 완료한다. 프로세스가0으로 종료됐다는 사실만으로 성공 처리하지 않는다. 이미 완성된 발행본은 재사용한다. 실패·미확인 응답은 `requires_recovery`로 남겨 운영자가 원장을 확인하며 자동 유료 재전송하지 않는다. 개인화도 공통 후보 풀이 준비된 뒤 같은 검증 경로를 사용한다.

배포 활성화 항목(기본false):

- `ZOOP_BRIEFING_COMMON_SCHEDULER_ENABLED=true`: 공통 정시 큐 예약.
- `ZOOP_BRIEFING_PERSONAL_SCHEDULER_ENABLED=true`: 기본 설정 준비·정시 자격 고정·개인화 후속 생성.
- `ZOOP_BRIEFING_SELECTED_GENERATION_ENABLED=true`: 분석 누락 후보의 실제 생성 작업 허용. 별도 생성 워커와 비공개 예산/키 설정 필요.
- `ZOOP_BRIEFING_PERSONAL_DEMO_ENABLED=false`: 정식 배포는 수동 과거 회차 미리보기 버튼을 노출하지 않음.

이번 로컬 검증은 정시 큐·설정/발행 불변성을 실제 PostgreSQL에서 확인한다. 공통 생성 소비자·모델 전송은 실행하지 않으므로 추가 AI 사용량은0이다.
