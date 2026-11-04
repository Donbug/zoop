# 공통·개인화 브리핑 표시 계약

D-BRF-01/02의 기존 발행본은 그대로 읽는다. 새 표시 결과가 저장된 회차에서는 상대 우선순위 카드, 기업별 사업 영향·판단 근거·조건부 전망·다음 확인 사항을 함께 표시한다. 중요도 점수나 적격 핵심 선정 기준을 바꾸는 기능은 아니다.

## 저장 위치와 응답

| 저장 위치 | HTTP 응답 | 내용 |
| --- | --- | --- |
| `briefing_rounds.public_snapshot.commonPriority` | `GET /api/v1/briefings`의 `commonPriority` | `common-relative-priority-view-v1` |
| 같은 snapshot의 `prioritySummary` | 같은 응답의 `prioritySummary` | `briefing-priority-summary-v1`, 회차·cutoff·결과 버전·text·evidenceIds |
| `briefing_personal_deliveries.result_snapshot.presentation.personalPriority` | `GET /api/v1/briefings/{id}/personalized/delivery`의 `selection.presentation.personalPriority` | `personal-relative-priority-view-v1` |
| 같은 결과의 `verifiedPresentation.personalPriority` | 같은 위치의 `selection.verifiedPresentation.personalPriority` | 부분 완료 결과의 검증된 보기에도 동일한 규칙 적용 |

새 필드가 없는 기존 회차는 기존 화면을 유지한다. 공통 priority를 개인화 결과로 복사하지 않는다. 개인화는 현재 회원 세션으로 찾은 발행 기록과 그 기록에 고정된 `choice.companyIds`를 사용한다. 오늘 설정한 종목으로 과거 정식 발행본을 만들거나 다른 회원의 결과를 재사용하지 않는다. 화면에서 회원·세션·회차가 바뀌면 이전 상태를 재사용하지 않는다.

생성·발행 생산자는 새 발행 전에 위 선택적 필드를 포함할 수 있다. 조회는 저장 결과만 읽으며 모델 호출·재선정·DB 보정을 수행하지 않는다. 이미 발행된 immutable payload/snapshot/delivery를 UPDATE하는 절차는 제공하지 않는다. 새 필드를 붙이지 않은 기존 생성기는 계속 종전 계약으로 동작한다.

## 근거·버전 검사

- 공통은 회차 ID·cutoff·원래 references의 이슈/기업/근거 ID를 대조한다. 요약도 같은 회차 및 허용 근거에 결속한다.
- 분석은 이슈에 연결된 기업과 근거만 사용하고 결과 버전, 프롬프트 버전, 별도 요청 검증 방식이 맞아야 한다. 기존 문안의 보관 영역은 새 검증 결과와 구분한다.
- 인용문·원문 URL·게시 시각은 DB evidence/article version과 같아야 한다. 문서의 현재 읽기 권한과 원래 그래프 출처 권한을 다시 검사한다. 미래 자료, 변조 인용문, 해제된 권한은 제공하지 않는다.
- 개인화의 새 카드도 complete candidate pool의 검증 후보·기업 연결·근거와 대조하고 현재 권한을 검사한다. 기존 `presentation.items`가 비어 있어도 새 카드가 이 검사를 건너뛰지 못한다.
- 알려지지 않은 속성은 거절하므로 프롬프트·모델 응답·내부 권한 메타데이터가 표시 결과에 섞여 반환되지 않는다.
- 서버가 유효하지 않은 저장 결과를 받으면 `SOURCE_UNAVAILABLE`을 반환한다. 클라이언트는 잘못된 선택 필드로 화면 전체가 중단되지 않도록 하고 기존 이슈로 돌아간다.

`candidateCount`는 현재 후보 수다. 이전 이슈 추적/참고 카드를 포함한 표시 항목 수보다 작을 수 있다. `importance=1`을 2로 올리지 않으며 `previous_issue`는 새 뉴스나 확인 조건 충족으로 표현하지 않는다.

## 완료된 로컬 결과의 형식 준비

```sh
python3 scripts/prepare_briefing_priority_views.py \
  --input-sqlite /absolute/path/completed-results.sqlite3 \
  --output /absolute/path/private/transfer-fragments.jsonl
```

도구는 `round_results(scope, day, edition, payload, sha256)`를 읽기 전용으로 열고 원본 SHA-256 및 회차를 검증한다. 결과는 새 파일에만 쓰며 DB·네트워크·원본 파일은 변경하지 않는다. 프롬프트/전체 기사/호출 영수증/사용자 정보를 복사하지 않고 표시 fragment와 필요한 reference ID, 원본 digest만 준비한다.

**이 파일 자체는 import/공개 승인이 아니다.** `publicationReady=false`를 유지한다. 실제 문서·그래프 권한, 발행 원문 결속, 개인화의 실제 회원·회차 고정 설정·전체 후보 풀을 별도로 확인해야 한다. 완료된 과거 실험을 정규 예약 발행본으로 바꾸거나 공개 grant를 만들어 내지 않는다. 원본 보존/권한 검사 없이 DB에 직접 넣지 않는다.

이 PR은 API·화면 연결과 형식 준비 범위다. 기존 자동 생성기가 새 계약을 생산하도록 연결하고 승인된 데이터로 발행하는 작업은 별도다. 이후 API/Web 반영, 승인 자료 import, 실제 생성·검증·발행, 관리자 원장·재처리 확인을 마친 후 정규 예약을 활성화한다.

## 검증

- `briefingIntegrationTest --tests com.zoop.briefing.integration.*`: 실제 PostgreSQL → Spring HTTP, 현재 권한 철회·인용문 변조·회원 격리·기존 발행본 보존.
- `test --tests '*BriefingPriorityRulesTest'`: 분석/기업/버전/근거 결속. 외부 저장 결과 검사는 `BRIEFING_PRIORITY_RECORDS`가 지정된 경우에만 실행하며 공개 자료/발행 권한을 증명하지 않는다.
- `web`: 브리핑 회귀 테스트, TypeScript, ESLint, production build. 간단히/전체 보기, 출근/퇴근, 공통/개인화 및 기존 데이터 fallback을 확인한다.
