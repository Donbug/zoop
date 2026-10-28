# 핵심 이슈의 짧은 근거 허용

BRF-DEV-126 (2026-10-23). 근거의 글자 수는 사실성이나 중요도를 보장하지 않는다. 새 grouped 실행은 `recorded-supported-event-exact-quote-v1`을 입력 identity에 고정하며, 인용의 80자 하한 대신 완료된 `issue_grounding`의 실제 SUPPORTED 응답을 재사용한다.

- 요청/응답 SHA, 모델·단계·응답 ID·사용량·검증 프롬프트 SHA, 승인 source SHA를 결합한다.
- 원문 본문·HTTPS 출처·버전·정확 인용/span, 원 사건/계획·추정 상태, 원 회사 참여자·역할이 검증 입력과 같아야 한다. archive의 SUPPORTED 문자열만으로 허용하지 않는다.
- 중요도 2 이상 SELECTABLE, 3의 시장 영향 근거, 최대 3개, 회사/근거 연결, 회차 마감, 재보도·불확실성 제외, MATERIAL_UPDATE의 새 delta, 문서 중복 방지는 그대로 유지한다.
- 원문이 짧아도 중요도를 올리지 않는다. 긴 원문도 의미검증이 없으면 제외한다. 이후 제목·문장 검증을 생략하거나 계획·예상을 확정으로 바꾸지 않는다.

새 실행은 `selection-semantic-v2.md`를 사용한다. 기존 `selection.md`와 과거 provider 요청·응답·스키마는 그대로 보존한다. 새 frozen 후보에는 `evidencePolicy`, `semanticSupport`(mention→실제 요청 SHA)가 추가되고 snapshot/run identity가 달라지므로 과거 호출을 새 정책 호출인 것처럼 재사용하지 않는다. 남아 있는 80자 조건은 **정책 선언이 없는 과거 기록을 당시 계약 그대로 검사하는 호환 경로**다.

기존 완료 기록은 `scripts/briefing_core_evidence_review.py --bundle ... --output ...`로 추가 호출 없이 재검증한다. 원래 AI assessments/selected를 유지하고 `selectionReexecuted=false`를 명시한다. 새로 허용된 후보를 임의 점수·제목으로 핵심에 추가하지 않는다. 새 후보로 실제 모델 재선정을 원하면 새 identity/출력 경로에서 별도 호출해야 한다.

별도 로컬 replay DB에 반영할 때 `zoop.briefing.replay.core-semantic-enabled=true`를 명시한다. Java는 실제 grounding을 다시 검증해 핵심 후보·선정 결과를 검사하고, 정책·후보별 원 중요도/선정 상태·지원 요청 SHA를 `public_snapshot.replay.selectionEvidenceReview`에 저장한다. manifest가 이 snapshot의 DB hash를 결합하므로 기존 저장본에 조용히 덮어쓰지 못한다. 운영 권리·발행 승인·당시 본문 동일성의 증명은 아니다.

실제 3회차 재검증: 10/21 퇴근 참고 2/핵심 0, 10/22 출근 핵심 2, 퇴근 핵심 3. 새 근거 기준을 통과한 짧은 후보 10건은 원 평가가 모두 중요도 1이므로 핵심 수는 유지한다. 기존 생성/검증·시장 요약/지표/기업 전망은 재사용하며 새 AI 호출은 0이다.
