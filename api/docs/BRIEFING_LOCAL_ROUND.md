# 새 실제 수집 자료의 단일 로컬 회차 실행

이 경로는 정규 운영·AWS 발행을 대신하지 않는 명시적인 로컬 검증이다. 기존 10월 2~8일 14회차 재생과 기존 PR을 변경하지 않고, 새 원문 수집부터 후보 추출·기존 이슈 비교·서비스 등록 기업 범위에서 최대 3개 선정·브리핑 생성/독립 검증·PostgreSQL 저장·지도 등록·API/화면 실행까지 연결한다.

## 시간·자료 범위

- 검색 제공사의 날짜는 탐색 힌트다. 실제 공개 원문 응답의 본문과 publisher 발행 시각을 함께 고정한다.
- 정확한 발행 시각이 없거나 접근이 제한된 자료는 제외한다. 출처·본문 SHA·원 HTML SHA·실제 수집/확인 시각과 제외 사유를 보존한다.
- 수집이 끝난 실제 시각을 수동 로컬 마감으로 사용한다. 정규 09:20/17:30 회차에 소급하지 않는다. 날짜는 KST 마감 날짜다.
- Python과 Java가 각각 publishedAt ≤ collectedAt ≤ cutoff 및 같은 HTML 결속을 검사한다. 전체 시장 수집의 완전성이나 운영 권리 승인을 주장하지 않는다.
- 같은 날의 실제 출근 판단·시세가 없으면 가상의 아침 비교나 적중 평가를 만들지 않는다.

## 실행

기본은 OFFLINE이며 키·DB·네트워크를 사용하지 않는다. 각 경로는 해당 환경의 절대 경로를 지정한다.

```text
python scripts/briefing_local_run.py
  --output <새 개인 0700 디렉터리>
  --companies <기업 카탈로그 JSON>
  --poc-root <고정 PoC 의존성 checkout>
  --seed <기존 이슈 승인 뷰 JSON>
  --search-key-file <0600 검색 키 파일>
  --key-file <0600 OpenAI 키 파일>
  --window-from <offset이 있는 시작 시각>
  --discovery-to <검색 시작 때 고정한 현재 시각>
  --authorization-ref local:BRF-DEV-119:user-local-single-round-instruction
  --database zoop_briefing_replay_local_<구분자>
  --pg-port <전용 로컬 PostgreSQL 포트>
  --java-home <JDK21>
  --node-modules <이미 설치된 web 의존성>
  --max-calls 40
```

실제 실행에는 `--execute`, 화면 기동에는 `--serve`를 추가한다. 실제 네트워크·모델 사용은 사용자의 해당 실행 승인 범위에서만 한다.

- 검색·원문 수집은 `briefing_live_collection.py`, 추출·묶음은 기존 `briefing_issue_pipeline.py`, 선정·작성·검증은 기존 `briefing_grouped_run.py`의 `--round-spec` 분기를 사용한다. PoC 원본은 수정하지 않는다.
- 완료된 검색/모델 응답과 고정 회차는 재사용한다. 결과 불명 요청은 자동 재전송하지 않는다. 실패·사용량·보완 이력은 보존한다.
- 이번 실행 전체의 모델 예약 수를 공유하며 기본/상한은 40회다. 과거 실행의 예산·기록을 초기화하거나 그 사용량을 숨기지 않는다.
- 전용 loopback DB 이름은 `zoop_briefing_replay_local_` 접두어로 제한한다. 기존 데이터·공개 그래프 활성화는 갱신하지 않는다. importer와 graph 등록은 별도 non-web 단계로 순차 수행한다.
- 그래프는 저장된 이번 이슈·기업·정확 인용에서 만드는 로컬 재구성이다. 원래 존재하지 않던 운영 공개 버전·수동 승인·import receipt를 만들지 않는다.
- 키는 수집/모델 실행기에만 파일 경로로 전달한다. JAR와 프론트에는 모델 키를 전달하지 않는다. 실제 원문·모델 응답·DB·개인 로그는 Git에 추가하지 않는다.

## 검증

`scripts/tests/test_briefing_local_round.py`는 단일 회차·새 출처/프롬프트 결속·완료 재사용·늦은 수집의 모델 전 거절을 확인한다. `BriefingLocalRoundPostgresTest`는 합성 대조의 실제 PostgreSQL 저장·HTTP 복원·원문 상세·지도 등록·재저장 불변·잘못된 시각 거절을 확인한다. 합성 대조는 실제 유료 모델 품질 증거와 구분한다.

실제 실행의 성공 여부는 고정 입력·모델 요청/응답·토큰 영수증·DB artifact·API/브라우저 결과로 별도 기록한다. 검증 실패를 발행 성공으로 바꾸지 않는다.


## 카탈로그·보완 이력

추출용 카탈로그와 서비스 등록 카탈로그를 구분한다. 로컬 실행기는 서비스의 demo-companies.json을 최종 선정 schema에 결속한다. 모든 사건의 중요도 평가는 보존하되 등록되지 않은 기업의 사건은 최종 선정하지 않는다. Java도 카탈로그 원본 SHA·기업 ID 집합·실제 DB 등록을 확인한다.

같은 입력의 선정 기준을 보완할 때는 --round-output rounds-v2처럼 별도 목록을 사용한다. 기존 목록은 보존하며 과거 목록에서만 사용한 호출도 전체 40회 상한에서 차감한다. 실행 결과의 modelReservations는 중복을 제외한 전체 목록의 합계다.
