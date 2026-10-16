# 브리핑 후보 선정·입력 고정 기반

브리핑에 사용할 핵심 이슈를 최대 3개 선정하고, 회차·거래일과 개발용 시장 지표 snapshot을 구분해 AI 입력을 불변 파일로 보존한다. 이 문서는 입력 준비 모듈의 사용 방법과 검증 경계를 설명한다. HTTP 브리핑 조회/발행, DB writer, AI 중요도 평가/생성 호출과 운영 scheduler는 후속 개발 대상이다.

## 실행 경계

- `BriefingCandidateSelector`: 입력으로 받은 검증·권한·영향 근거를 검사해 중요도 2 이상 최대 3개를 선정한다. 적격 후보가 0~2개면 그 수를 유지하고 조회 실패를 정상 0개로 만들지 않는다. 영향 범위 근거·신규 사실·결정적 동점 기준과 후보별 선정/보류/제외 이유를 보존한다. 중요도는 전달된 영향 근거에 정책을 적용해 계산하며, AI 평가 클라이언트 연결은 후속 개발 대상이다.
- `SelectionInput`: 실제 소유자가 공급한 버전/검수 revision과 근거 참조, 회차의 `(from,to]` 구간을 사용한다. `from=NULL`은 실제 서비스 첫 회차일 때만 허용한다. 과거 ALLOW·개발 동의가 현재 전송/공개 권한을 대신하지 않는다.
- `BriefingRoundClock`: 현재 사용자 기준은 매일 **09:20/17:30 Asia/Seoul**이다. 생성 시작 기준이며 공개 완료 시각 보장이 아니다. 회차와 거래일은 별개다. 24시간 운영 시 시간 재설정은 별도 결정이다.
- `TradingCalendar`: version/source/authority/reviewedAt 및 날짜별 open/opensAt/closesAt이 필요하다. 빠진 날짜는 unknown으로 남기고 평일로 추정하지 않는다. `development_reviewed`/`owner_reviewed` 표기만으로 공식 운영 일정이나 권한이 생기지 않는다.
- `BriefingInputPreparer`: 선정 결과·원문/근거 참조·정확한 요청 JSON을 고정하며, 시장 snapshot의 해시와 회차/window 일치를 검사해 함께 보존한다. DB artifact 등록 및 임대 취득은 자동 실행하지 않는다.
- `FileBriefingInputStore`: 디렉터리0700/파일0600, SHA-256에 따른 불변 파일과 원자적 생성으로 같은 입력을 재사용한다. 등록 receipt의 해시/크기가 저장값과 다르면 거절한다. 실제 운영 artifact 계정/URI 등록은 후속 개발 대상이다.

## 시장 지표

KOSPI·KOSDAQ은 Yahoo 공개 chart, USD/KRW는 Naver 제공 하나은행 고시 기준환율과 고시 이력을 사용한다. 키 없는 개발용 읽기이며 운영 저장·모델 전송·재배포 권한을 확정한 공급원이 아니다. `official=false`, `productionAuthorized=false`, `rights.status=unconfirmed`가 유지된다. 은행 고시값은 외환시장 체결가/마감값과 구분한다.

각 수집은 4feed를 1회씩 호출한다. connect8초/전체 요청12초/본문1MB, redirect·자동 재시도 없음. 첫 회차와 실제 회차 ID는 CLI가 만들지 않는다. 수집은 cutoff 이전에 수행하며 그 이후에는 기존 SHA만 재생한다.

출근 지수는 직전 거래일 종가, 퇴근은 확보된 당일 확정 종가를 기대한다. 장중 일별 candle을 종가로 쓰지 않으며 기대값이 없으면 실제 기준일과 delayed를 보존한다. 날짜 정밀 종가의 `observedAt`은 NULL이고 15:30이라는 관측 시각을 만들지 않는다. 변화율은 분수이며 표시할 때만100을 곱한다. 환율15분 지연 기준은 개발 기준이며 운영 SLA가 아니다.

`completeness.state`는 수집 축이다. 수집이 성공했어도 캘린더/전일 baseline이 없어 `indicatorStatus=unavailable`, `valueAvailable=false`일 수 있다. 정상/지연 상태의 실제 값만 `valueAvailable=true`이며, 이 값이 권리 승인을 뜻하지 않는다. 기존 snapshot을 덮어쓰지 않고 필드 없는 옛 자료도 실제 status/value를 확인한다.

## 로컬 검증과 개발 수집

```sh
# 합성 fixture와 localhost stub만 사용한다. 외부 시장/모델 호출 없음.
./api/gradlew -p api test --tests 'com.zoop.briefing.*' --console=plain

# 별도로 승인한 개발 수집: 검토한 calendar와 실제 회차/window가 필요하다.
./api/gradlew -p api briefingMarketCapture --args='<calendar.json> <YYYY-MM-DD> morning <owned-round-id> <previous-cutoff> <private-output> --development-read'
# 같은 인자 끝에 기존 snapshot SHA를 추가하면 원응답 해시 검증 후 새 HTTP 0회로 복원한다.
```

build/test/startup에는 데이터 수집이나 유료 모델 호출이 연결되지 않는다. 본개발은 `prototype/` 코드나 DB를 import/공유하지 않는다. 기능별 완료 조건과 DB 연결 순서는 [브리핑 입력 기반 개발](../../docs/development/briefing-input-foundation.md)을 따른다.
