# 합성 브리핑 HTTP 시험 자료

이 폴더는 테스트 전용입니다. 실제 뉴스·공시·시세·모델 출력이 아니며 외부 요청이 없습니다. 운영 데이터를 생성하는 seed가 아닙니다.

- 격리된 폐기용 DB에 정상 Flyway migration을 먼저 적용하고 `fixture.sql`을 명시적으로 한 번 실행합니다. 재실행·원본 덮어쓰기는 실패하도록 했습니다.
- 시험 API 프로세스의 `ZOOP_DOCUMENT_READ_GRANTS`에 이 폴더 `grants.json`의 절대 경로를 지정합니다. 운영 권리 레지스트리로 사용하지 않습니다.
- 공개 내용: `GET /api/v1/briefings?date=2026-10-15&edition=evening` 또는 `morning`.
- 빈 이슈: 2026-10-14 morning. 제공 중단: 2026-10-14 evening. 미발행: 2026-10-16 morning.
- 날짜를 생략한 조회는 최신 **저장** 회차를 반환하므로 morning 최신은 미발행입니다.
- sourceBindings, 공통 문서/버전/근거 FK, SHA-256, 같은 날 출근 비교 원본까지 포함합니다.
