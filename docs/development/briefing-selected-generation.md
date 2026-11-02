# 명시 선택 브리핑의 공통 AI 생성·검증 (D-BRF-01/02)

로그인한 회원이 종목을 선택하고 만들기를 누르면 기존 선정 API로 정확한 종목·회차·마감·후보 버전을 확인한다. 기존 분석은 재사용하고, 없는 이슈만 생성 작업에 넣는다. 계좌 ID·회원 ID·선택 프로필·수량·금액·인증 쿠키를 모델 입력에 넣지 않는다. 모델은 공통 브리핑과 같은 gpt-6-luna, issue-intelligence-v1 프롬프트·구조·사실/시점/기업/가격 검증을 사용한다. 검증은 같은 모델의 별도 요청이며 다른 공급자의 검증으로 소개하지 않는다.

## 경로

- POST `/api/v1/briefings/{id}/personalized/generations`: `{choice, selectionVersion}`. 회원·CSRF 필수. 서버가 다시 계산한 선택과 다르면409. 기본 운영 비활성 상태에서는 미생성 실행503. 같은 회원·회차·선택 버전은 동일 작업을 반환한다.
- GET `/api/v1/briefings/{id}/personalized/generations/{jobId}`: 해당 회원 본인만 작업 진행/결과 조회. 회원/종목/회차/후보 버전이 달라지면 결과를 다른 선택에 붙이지 않는다. GET은 모델을 호출하지 않는다. 원 입력·공급자 원본 영수증은 반환하지 않는다.
- POST `/api/v1/briefings/{id}/personalized/generations/{jobId}/retry`: 알려진 의미 검증 보류에만 1회 추가 보완 시도. 원 시도를 그대로 두고 후속 행을 추가한다. 중복 클릭은 같은 후속 작업으로 연결한다. 네트워크 응답 미확인·비용 한도 종료 작업을 자동 재전송하지 않는다.

화면은 `queued/running`에서 진행을 조회하고 `ready/partial/withheld`에서 검증 결과를 보여준다. 통과한 분석은 공통 카드로 먼저 제공하며 보류 이슈의 선정 사실·원문은 남긴다. 새 선택이나 로그아웃에서 이전 선택의 비동기 응답을 폐기한다. 원 발행 회차·평가·과거 개인화 결과는 변경하지 않는다.

## 저장과 권한

후속 migration은 회원 소유 작업과 고정 요청 SHA, 공통 이슈 분석 불변 버전, 실제 호출별 사용량을 저장한다. 후속 보완 attempt도 새 행이며 원 요청 스냅샷은 그대로다. 회원 삭제 시 개인 작업은 삭제되고 호출 집계의 회원 작업 연결은 해제된다. 공개 이슈만으로 만든 공통 분석은 계좌 정보를 포함하지 않는다.

워커는 매 전송과 PASS 저장 전에 현재 회원 상태·발행/정정 상태·동일 원문 버전·최신 후보 버전·현재 source grant의 model-send/openai 허용을 다시 검사한다. 동일 입력은 DB advisory lock과 완료 분석 조회로 중복 생성하지 않는다. 생성/독립 검증의 요청·응답 원본 SHA와 입력/문안 일치를 증명한 결과만 저장한다. 가격은 뉴스 인과관계와 구분하며 unavailable을0으로 바꾸지 않는다.

## 로컬 실행

API의 `zoop.briefing.selected-generation-enabled` 기본값은 false다. 승인된 개발 환경에서만 true로 설정한다. 서버 API 자체에 키를 주입하지 않는다.

`scripts/briefing_personal_pool.py --baselines ...`로 공통 근거/시세를 고정한 새 후보 버전을 준비한다. 그 뒤 `python scripts/briefing_selected_generation.py --config /비공개/worker-config.json` 워커를 별도로 실행한다. 워커는 psycopg가 필요하며 비공개0600설정과 승인 파일만 읽는다. 설정에는 로컬 briefing_replay DB의 dsn, grants, keyFile, budget, work, task, authorizationFile, baselineCalls/baselineUsd, maxNewCalls/maxAggregateCalls/maxUsd를 둔다. 키·비밀번호·실제 설정이나 실행 자료를 저장소에 올리지 않는다.

승인 파일의 task/model/maximumNewCalls/maximumAggregateCalls/maximumAggregateUsd보다 설정 한도를 키울 수 없다. 공유 예산 잠금으로 전송 전에 상한을 예약하고, 응답에서 확인된 토큰만 저장한다. 응답을 확인하지 못하면 토큰/비용을0으로 만들지 않으며 같은 요청을 자동 재전송하지 않는다. 실행 도중 프로세스가 사라진 running 작업도 자동으로 새 과금을 시작하지 않는다.

보완 시에도 같은 공통 검사 기준을 유지한다. 예를 들어 기사 게시 직전 봉과 게시 시각이 다르면 정확한 두 시각을 구분하고, 관측된 기사 구간과 전일 종가 등락을 별개로 전망에 반영하도록 지시한다. 원 실패 초안·검증 이유·공급자 응답은 보존한다.
