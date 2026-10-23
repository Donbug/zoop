# 새 핵심 이슈가 없는 회차의 복기 (D-BRF-01·02)

정상 발행·items=[]·emptyReason=no_issues_in_window일 때만 별도 복기 영역을 제공한다. 기존 발행·선정·수집 검증 조건은 유지한다. failed/not_ready/generating/suspended 또는 단순 items 누락을 정상 빈 회차로 바꾸지 않는다.

GET /api/v1/briefings/{id}/recap은 읽기 전용이다. 현재 회차에 저장된 sinceMorning.morningRoundId(퇴근) 또는 previousComparison.previousRoundId(출근)만 사용한다. 고정 참조가 없으면 unavailable이며 최신 회차나 날짜 추정으로 채우지 않는다.

이전 cutoff가 현재 cutoff보다 앞서고 입력 창 시작 이후를 침범하지 않는지, 참조 cutoff·발행 시각이 실제 원장과 같은지 검사한다. 퇴근은 같은 날 출근만 허용한다. 현재와 이전 회차의 권한·무결성·본문 검증을 다시 수행한다. 정정된 문안은 다시 강조하지 않으며 unavailable로 구분한다. 권한·저장 원문 검증 실패는 503이다.

응답 previous는 기존 BriefingResponse의 저장 원문 복원 결과다. 새 요약·전망·AI 평가·발행으로 취급하지 않는다. 모델 호출·신규 DB 스키마·기존 payload 갱신은 없다. 이전 관전 조건은 이전 전문 링크에서 확인하고, 재평가한 것처럼 서술하지 않는다.

화면은 새 핵심 이슈 목록과 분리해 과거 발행일·구분·데이터 시점을 명시한다. 간단히에서는 제목부터 보이고 펼쳐 요약·근거를 읽는다. 근거 버튼은 이전 roundId와 graphVersion(NULL 포함)을 유지한다. 이전 시장 지표나 평가 버튼을 현재 회차에 복사하지 않는다. 회차 전환의 늦은 응답은 버리고, 실패는 재시도할 수 있다.

검증: 단위·실제 HTTP/PostgreSQL·프론트 상태/문맥 회귀. 빈 회차 양성 대조는 명시적 합성 자료로 시험한다. 기존 10/2~8 과거 수집본은 시각 미확인 자료가 있어 임의로 정상 빈 회차로 승격하지 않는다.
