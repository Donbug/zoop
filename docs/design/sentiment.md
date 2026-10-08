# 문서·회차 판정의 저장 이력과 S1 이행

**현재 문서와 기존 회차 판정의 생산자는 [S1 AI worker](ai-system.md)다.** 이전 `scripts/judge_sentiment.py`, BFF OpenAI-compatible client와 중복 replay/live 분기를 worker로 이행했다. 실행되지 않는 CLI shim이나 옛 환경변수 alias는 남기지 않는다.

## 보존되는 의미와 불변 자료

- 문서 판정은 `(documentVersion, companyId)`의 사업·재무·평판 해석이다. 같은 문서도 기업마다 반대 판정이 가능하다.
- `positive|negative|mixed|undetermined`는 주가 방향·확률·투자 권유가 아니다. `undetermined`는 실제 평가 후 방향 근거가 부족한 상태이며 산출물 없는 `null`과 다르다.
- 기존 `DocumentSentiment` JSON 필드(`label,companyId,rationale,quotes,judgedAt,model,promptVersion`)는 그대로다. S1은 별도 `analysisStatus`/`resultVersion`/provenance와 versioned summary를 제공한다.
- `sentiment_results`의 기존 accepted/failed 캐시와 발행된 `briefing_rounds.payload`는 불변 읽기로 보존한다. 과거 `sentiment-2026-10-06-v1` prompt/hash와 모델 메타데이터를 새 형식으로 덮어쓰지 않는다. 기존 회차의 null까지 발행 당시 결과다.
- 회차 outlook은 회차 이슈들의 성격이지 시장 전망이 아니다. 기존 생산 기능은 worker의 `briefing-outlook`과 실제 `scripts/judge_outlook.py`로 보존한다. issueIds 정확 참조·금지 표현은 기존 exact 정책이며 semantic=null이다. 새 문서의 별도 의미 검증과 같은 검증이라고 주장하지 않는다. 빈 회차만 무호출 null이고, 비어 있지 않은 미발행 회차는 provider/replay로 생성한다. 기업·시장 요약은 S5 후속 범위다.

## 설정과 실행 경계의 변경

옛 `ZOOP_SENTIMENT_MODEL`/`ZOOP_SENTIMENT_REASONING_EFFORT`의 문서 설정은 `ZOOP_AI_DOCUMENT_SENTIMENT_MODEL`/`ZOOP_AI_DOCUMENT_SENTIMENT_REASONING_EFFORT`로, 회차 설정은 `ZOOP_AI_BRIEFING_OUTLOOK_MODEL`/`ZOOP_AI_BRIEFING_OUTLOOK_REASONING_EFFORT`로 명시적으로 옮긴다. summary와 semantic verification 모델은 stage별로 별도 승인한다. `.env`를 자동으로 읽지 않는다. 실제 모델·effort·단가·금액 상한은 아직 결정하지 않았으며 실제 키나 `.env`를 열어 이행하지 않는다.

현재 CLI JSON, 정확한 입력 digest replay, durable global budget·attempt/receipt, timeout 불명 상태, 권한·인용·의미 검증, BFF import 저장 복구와 합성 재현 명령은 [AI 실행 계약](ai-system.md)에 통합했다. 과거 provider의 instance-local 호출 상한이나 network 중 SQLite transaction, timeout 자동 retry를 새 runner로 복사하지 않는다.

HTTP GET은 신규 모델을 호출하지 않는다. 기본 데모는 기존 stored source를 읽고 신규 live grant를 자동 생성하지 않는다. 합성 authored 응답은 별도 worker/BFF 상태에서만 실행하며 실제 뉴스 문서에 수입할 수 없다. 입력 권한은 [외부 API 조사](../evidence/external-api-candidates-2026-10-08.md)의 출처 제한을 따른다. PoC 검수 확률·ALLOW/HOLD/REJECT를 감성이나 가격 확률로 쓰지 않는다.
