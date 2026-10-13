# D-GRP-02 사건 상세 패널

GitHub [#26](https://github.com/Donbug/zoop/issues/26), WBS 6.6.22, FS021·FS024.
참조: `docs/wireframe/manifest.json`, 보드 `03-map-relationships-evidence`,
개별 이미지 `D-GRP-02--node-619-6269.png`, 화면계획서 캡처 `D-GRP-02.json`.

## 실행

루트에서 `pnpm --dir web dev` 실행 후
`http://localhost:5173/?mode=all&select=node%3Amock-issue-1`에서 확인한다.
개발 모드에서는 기존 지도와 동일하게 합성 fixture를 사용한다.
지도 사건 노드를 클릭하거나 Tab으로 사건 버튼에 이동해 Enter를 누른다.
접힌 개별 사건과 미연결 사건도 키보드로 선택하면 지도에 펼쳐진다.

`VITE_EVENT_MOCK_SCENARIO`로 `success`, `unknown-time`, `no-companies`,
`no-evidence`, `partial`, `error`를 지정하고 개발 서버를 다시 시작하면
각 상태를 확인할 수 있다. 기존 `VITE_GRAPH_MOCK_SCENARIO`와 독립적이다.
지원하지 않는 시점/회차/버전은 오류이며 최신 데이터로 대체하지 않는다.

`VITE_GRAPH_DATA_SOURCE=api`에서는 지도와 사건 모두 목표 API를 호출한다.
production은 목업을 사용하지 않는다. 사건 consumer는 공개
`GET /api/v1/events/{id}`에 `round`, `graphVersion`, `asOf`를 전달한다.
실제 API producer 구현·배포·연동 검증은 이번 변경에 포함되지 않는다.

## ERD와 계약 대응

| UI/fixture             | 저장소 및 계약                                                                                |
| ---------------------- | --------------------------------------------------------------------------------------------- |
| 사건 ID·제목·발생 시각 | Neo4j Issue → EventDetail. PostgreSQL Issue FK를 만들지 않음                                  |
| 관련 기업·역할         | companies.id를 공유한 INVOLVES / STRUCTURALLY_RELATED_TO. 구조적 관계는 별도 표시             |
| 관련 문서              | articles / article_versions → ArticleOut. 기사 내용은 모두 합성                               |
| 근거 ID·인용문         | evidence → mockEventEvidence. 문서/버전/사건 ID, code point 인용 범위 유지                    |
| 핵심 내용              | document_analyses 등에서 조립되는 AnalysisSummary / Unavailable. 목업 요약은 모델 결과가 아님 |
| 조회 기준              | graph_versions 및 공개 스냅샷 → metadata.graphVersion/asOf                                    |
| 국내·국제              | EventDetail에는 필드가 없어 같은 지도의 GraphNode.geography를 사용. 없으면 지역 미제공        |

`eventTime`의 연/월/일/시각 정밀도를 유지하며 `publishedAt`으로 대체하지 않는다.
누락된 역할·지역·제목·출처·원문 링크는 미제공으로 표시한다.
기업별 영향 및 주가 상승·하락 확률을 생성하지 않는다.

## 상태와 후속 화면 연결

- `select=node:<id>`가 선택의 기준이다. 닫기/Escape/뒤로 가기로 선택을
  해제해도 모드·필터·포커스 URL과 지도 데이터는 유지한다.
- 상세 요청은 지도 요청과 분리한다. 선택·시점·재시도 변경 시 이전 응답을
  폐기하며 다른 사건의 정보를 잠깐 표시하지 않는다.
- 로딩·오류·관련 기업 없음·근거 0건·문서 부분 실패를 구분한다.
  `metadata.failures`에 표시된 실패를 빈 목록으로 해석하지 않는다.
- 근거 버튼은 `useGraphUiStore.evidenceTarget`, AI 버튼은
  `useAiChatStore.context`에 사건 ID, 근거 ID, 현재 지도 URL, 실제 응답 버전을 전달한다.
  상세 근거 창(D-GRP-05)과 AI 대화(D-AI-01)는 이슈 범위 밖이므로 안내만 표시한다.
- 중심 보기 버튼은 `focus=<eventId>&hops=1`을 설정하고 해당 노드로 지도 중심을 이동한다.
  별도 영향 경로/이웃 그래프 API 구현은 포함하지 않는다.
- 패널 진입 시 제목에 포커스를 주고, 닫으면 진입 버튼(없으면 지도 영역)으로 복원한다.
  지도와 패널은 모달이 아니므로 키보드 포커스를 가두지 않는다.
- 기존 지도와 같은 데스크톱 최소 너비 1024px 기준이다. 모바일 레이아웃은 별도 범위다.

## 검증

- `pnpm --dir web lint`
- `pnpm --dir web format:check`
- `pnpm --dir web test`
- `pnpm --dir web exec tsc -p tsconfig.test.json --noEmit`
- `pnpm --dir web build`

API 테스트는 fetch 가짜 서버, 화면 테스트는 합성 fixture를 사용한다.
브라우저 검증은 로컬 Vite 개발 서버에서 수행한다.

2026-10-14 확인 결과: 7개 테스트 파일의 37개 테스트 통과,
lint·format:check·테스트 타입 검사·production build 통과.
빌드에는 지도 번들의 500kB 초과 경고가 남아 있다.
로컬 브라우저에서 사건 노드 클릭 → URL 선택/상세 로딩 → 사건 표시,
중심 이동, 닫기 후 지도 유지, AI 질문 대상 연결 안내를 확인했다.
마지막 브라우저 검사에서 console error는 없었다.
