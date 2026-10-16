# 실제 수집 자료 → AI → 발행 DB → 브리핑 화면

과거 뉴스·공시를 이용해 전체 후보 평가, 최대 세 이슈 선정, 출근·퇴근 작성과 별도 검증을 실행하고 기존 브리핑 조회 API로 확인하는 **로컬 개발 재생** 절차다. AWS, 정시 실행, 운영 공개 승인은 포함하지 않는다. 적용된 migration과 ERD는 변경하지 않는다.

## 1. 입력과 AI 결과 고정

[실행기·번들 계약](BRIEFING_REPLAY_BUNDLE.md)에 따라 저장소 루트의 `scripts/briefing_replay.py`를 실행한다. 원본 JSONL 전체, 사용자 개발 지시 참조, 프롬프트·스키마 SHA, 모델과 호출 결과가 고정된다. 모델은 `gpt-6-luna`다. 원본 권한 값은 변경하지 않으며 개발 승인을 별도 기록한다.

먼저 유료 호출 없는 감사를 확인한 다음, 승인된 입력에만 `--execute-authorized-development --key-file /absolute/private/openai.env`를 사용한다. 같은 출력 경로의 완료 응답은 재사용한다. 실패·불명 reservation이 있으면 자동 재전송하지 않는다. 두 형식 모두 최종 검증 `PASS`인 `bundle.json`만 다음 단계에서 사용할 수 있다.

실제 원본·AI 응답·키·번들·DB·artifact 디렉터리는 Git 밖에 보존한다. 코드와 CI에는 합성 자료만 넣는다. 청구액을 추정하지 않고 모든 유료 시도의 실제 토큰 사용량을 남긴다.

## 2. 폐기용 PostgreSQL에 저장

PostgreSQL을 loopback에서 실행하고 이름에 `briefing_replay`가 포함된 별도 DB를 만든다. `DB_URL`은 `jdbc:postgresql://127.0.0.1:<port>/zoop_briefing_replay` 형태여야 한다. `DB_USERNAME`·`DB_PASSWORD`, API README의 로컬 인증 설정도 준비한다. 키 파일은 Java 서버에 전달하지 않는다.

`artifact-root`, `grants`, `manifest`의 부모는 기존 개인 디렉터리여야 한다. 경로는 모두 정규화한 절대 경로를 사용한다. 아래의 SHA는 원본 파일의 실제 SHA-256으로 대체한다.

```sh
export SPRING_PROFILES_ACTIVE=local
./api/gradlew -p api bootJar
java -jar api/build/libs/zoop-api-0.0.1-SNAPSHOT.jar \
  --spring.main.web-application-type=none \
  --zoop.briefing.replay.import-enabled=true \
  --zoop.briefing.replay.source=/absolute/private/source.jsonl \
  --zoop.briefing.replay.bundle=/absolute/private/replay-run/bundle.json \
  --zoop.briefing.replay.artifact-root=/absolute/private/artifacts \
  --zoop.briefing.replay.grants=/absolute/private/grants.json \
  --zoop.briefing.replay.manifest=/absolute/private/manifest.json \
  --zoop.briefing.replay.expected-source-sha256=<source-sha256> \
  --zoop.briefing.replay.user-inbox-ref=inbox/approved-user-instruction.md
```

기존 확정 기업 카탈로그에 하나로 매칭되는 기업만 연결한다. 원문 파일·본문 해시·문서 버전·Unicode 인용 구간, 두 형식의 모든 제목/문장 검증, 평가/선정/작성/검증의 사용량 receipt를 먼저 확인한다. 두 회차는 한 트랜잭션으로 `briefing_rounds`에 저장하며 원문·결과·검증·사용량은 기존 `artifacts` 등록부와 개인 파일에 보존한다. 존재하지 않는 AI 작업·그래프·관리자 식별값은 생성하지 않는다.

DB commit 뒤에만 읽기 허가 파일과 manifest를 원자적으로 게시한다. 파일 게시 전에 중단되면 조회가 차단된다. 동일 번들의 재실행은 같은 행·바이트를 재사용하고 누락된 허가 파일을 복원한다. 다른 내용으로 기존 발행본을 덮어쓰지 않는다.

## 3. 실제 API와 React 조회

같은 DB를 가리키고 서버 주소를 loopback으로 고정한 뒤 API를 실행한다. importer 옵션은 API 서버에 넣지 않는다.

```sh
export ZOOP_DOCUMENT_READ_GRANTS=/absolute/private/grants.json
export ZOOP_DOCUMENT_READ_ARTIFACT_ROOT=/absolute/private/artifacts
export ZOOP_API_CORS_ALLOWED_ORIGINS=http://localhost:3000
java -jar api/build/libs/zoop-api-0.0.1-SNAPSHOT.jar \
  --server.address=127.0.0.1 \
  --server.port=8080 \
  --zoop.briefing.replay.read-enabled=true \
  --zoop.briefing.replay.manifest=/absolute/private/manifest.json
```

```sh
cd web
VITE_API_BASE_URL=http://localhost:8080 pnpm dev --host 127.0.0.1 --port 3000
```

`http://localhost:3000/briefing?date=2026-10-09&edition=evening`에서 두 형식을 전환한다. 기존 프론트의 `src/apis/briefing/briefing.ts` → `GET /api/v1/briefings` → DB 저장값을 사용하며 mock이나 브라우저의 모델 호출은 없다. 발행 이력은 `/api/v1/briefings/rounds`로 조회한다. API 응답의 `metadata.source=zoop-briefing-development-replay`를 화면 안내로 표시한다.

읽기 허용은 기본 꺼져 있다. `local` profile·loopback 서버·폐기용 DB·현재 허가 파일·manifest·실제 DB snapshot SHA가 모두 일치해야 개발 재생본을 제공한다. 허가 철회나 본문 변조 후에는 제공하지 않는다. 기존 운영용 검증은 그대로 유지한다.

## 표현하는 범위

- 같은 10월 2~8일 주간 자료로 출근·퇴근 형식을 작성한다. 실제 회차 사이의 신규 정보나 장중 흐름을 관측한 결과가 아니다.
- 발행 시각은 공급자 추정/일 단위 정보이며 실제 수집은 과거 개발 회차 이후라는 한계를 보존한다.
- 실제 시장 자료·이전 전망이 없으므로 시장 요약·KOSPI/KOSDAQ/환율·출근 대비 비교는 `unavailable`이다.
- 공개 그래프를 만들지 않으므로 `graphVersion=null`, 그래프 조회는 `unavailable`이다.
- 검증은 별도 AI 호출과 정확한 원문 인용 검사다. 외부 사실을 독립적으로 확인한 승인으로 표현하지 않는다.

## 검증

```sh
python3 -m unittest discover -s scripts/tests -p test_briefing_replay.py -v
./api/gradlew -p api test briefingIntegrationTest briefingReplayIntegrationTest
```

DB 시험에는 위의 폐기용 PostgreSQL 환경이 필요하다. 기존 조회 시험과 개발 재생 시험은 별도 tag/task이며 일반 단위 시험은 DB 없이 실행한다. 재생 시험은 실패 결과 차단, 정확한 근거, 트랜잭션 rollback, 재실행, manifest/허가 변경, 사용량 phase 연결 및 실제 HTTP 응답을 확인한다.
