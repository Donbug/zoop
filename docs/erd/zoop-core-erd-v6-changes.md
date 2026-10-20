# Zoop ERD v6 변경 이력

작성일: 2026-10-13

기준: v5와 사용자 제공 v5 검증 결과. API 필드는 저장소 docs/api/out/zoop-api-spec.md 및 openapi.yaml과 대조했다. 이전 다운로드 API 파일과 바이트 단위 동일성을 검증한 것은 아니다.

## 2026-10-20 추가 변경 — 확인 질문 답 연결

- `chat_jobs`에 `resolves_job_id text? FK chat_jobs`, `resolves_choice_id text?`와 CHECK(choice가 있으면 job 필수)를 추가했다. 기존 계약에는 clarification 선택지(`ChatChoice.id`)를 새 질문에 돌려보낼 필드가 없어 원 질문과 선택을 서버가 결합할 근거가 없었다.
- API `ChatJobRequest.resolves`·`ChatJob.resolves`(`ChatClarificationReply`)와 대응한다. 원 작업의 같은 대화·completed·clarification 여부와 choice 존재는 접수 트랜잭션에서 검사하며, 새 작업은 원 작업의 고정 문맥을 복사한다.
- 테이블 수는 그대로 36개다. 챗봇 첫 migration에 함께 포함한다.

## 2026-10-17 추가 변경 — 챗봇 동적 라우팅·도구 호출 관측

- PostgreSQL 테이블 수를 35개에서 36개로 변경하고 `chat_tool_calls`를 추가했다. 질문 결과와 함께 읽는 분류·계획 요약은 `chat_jobs.route_summary` JSONB에 유지하되, 실제 MCP/서버 읽기 호출은 요청당 상한·지연·오류·중복 제거를 독립 집계할 수 있도록 행으로 분리했다.
- `chat_jobs`에 `route_schema_version`, `route_summary`를 추가했다. 요구 ID, Q01~Q08 multi-label, 논리 기능, Luna 커버리지, 계획 revision, 예약·사용 예산, 답변 근거 수준과 검증 결과만 저장하며 자유 형식 내부 추론은 저장하지 않는다.
- `chat_tool_calls`는 레지스트리·논리 기능·실제 도구·스키마 버전과 입력 digest, 허용된 요청 메타데이터, 결과 artifact·근거·dataVersion, timeout을 포함한 실제 상태를 고정한다. 모델 출력의 도구명을 직접 실행하지 않으며 회원 ID·인증값·질문 원문·개인 포트폴리오 전문은 기본 메타데이터에서 제외한다.
- 모델 호출은 기존 `ai_executions(feature=chatbot)`에 router, coverage-verifier, answer-generator, semantic-verification stage로 기록하고 도구 호출과 중복 집계하지 않는다.
- 이 변경은 목표 ERD와 계약 결정이다. 기존 migration을 수정하지 않고 챗봇 구현 PR에서 `chat_sessions`, `chat_jobs`, `chat_tool_calls`를 만드는 새 Flyway migration과 저장소·동시성 시험을 추가해야 한다.

## 2026-10-15 추가 변경 — 기업 브랜드 출처

- `companies.brand_source text?`를 추가했다. 색상·로고의 출처 URL을 보관하는 내부 필드이며, 기업 상세 API의 공식 홈페이지 주소 `websiteUrl`과 구분한다.
- 출처를 확인하지 못했거나 홈페이지 주소만 알고 있으면 NULL로 둔다. 공개 기업 API 응답에는 포함하지 않는다.
- API 구현은 새 Flyway migration으로 컬럼을 추가하고, 앱 시작 시 기업 카탈로그 JSON의 값을 기업 ID 기준으로 적재한다. 기존 기업 행과 참조 기록을 삭제하지 않는다.

## 2026-10-13 추가 변경 — 후보 allow 접수와 실행 분리

버전과 파일명은 v6를 유지한다. 사용자 요청에 따라 아래 내용이 기존 단일 queued/running 슬롯 정책을 대체한다.

- `analysis_jobs` 부분 UNIQUE를 `scope='admin' AND status='running'`으로 변경했다. queued는 여러 개 저장하고 실행은 하나씩 처리한다.
- allow는 검수 결정·재검증 queued 작업·감사·멱등성 완료 기록을 한 트랜잭션에 저장한다. 기존 DecisionResponse의 revalidation_requested/jobId/publicChanged=false를 반환하며 다른 작업 실행 때문에 결정을 롤백하지 않는다.
- worker의 실행권 획득, requested_at/id 순서 처리, 토큰/임대 검사와 실행 경합 처리 위치를 명시했다. 경합은 worker에서 처리하고 이미 접수한 결정에 오류를 전파하지 않는다.
- JobList.active와 JobLock은 running 기준이다. queued만 있으면 active=null, locked=false, jobId=null이다. 목록과 Dashboard/Overview의 queued 집계에는 여러 대기 작업을 포함한다.
- 허용된 재시도도 queued로 접수한다. 다른 작업의 실행만으로 RetryState.other_running을 반환하지 않는다. 기존 enum과 요청·응답 필드는 유지하며 결정 API에 JOB_IN_PROGRESS를 추가하지 않는다.
- 기존 queued/running 부분 인덱스가 구현돼 있다면 running 전용으로 교체해야 한다. 이 작업에서는 ERD와 변경 이력만 수정했다.

문서 점검: 기존 관리자 슬롯 충돌 시 결정 롤백 규칙과 queued/running 제한을 본문에서 제거하고 관련 조회·집계 설명의 일관성을 확인했다. 채팅과 브리핑의 별도 동시성 제약, 평가 대상 미결 항목은 이번 변경 범위가 아니다. SQL 실행 검증은 수행하지 않았다.

## v6 최초 반영 내역 (아래 슬롯 정책은 추가 변경으로 대체)

| 검증 항목 | 처리 | 위치 |
| --- | --- | --- |
| a 검수 CAS·필수 행위자·검증 결과 | 대상별 UNIQUE, origin CHECK, verification_artifact_id 복원 | review_decisions |
| b 전역 검수 revision | global_revision UNIQUE, 공통 트랜잭션 잠금 아래 MAX+1; 결정 부재는 0 | review_decisions, graph_versions, briefing_rounds |
| c 중복 pending | summary/sentiment 범위별 부분 UNIQUE, 진행 행 재사용, 임대 회수 | document_analyses |
| d AI 실행 FK 모순 | 실행 소유는 최대 하나, 문서 분석 문맥 병행 허용, 적어도 하나 참조 및 관계 검증 | ai_executions |
| e OAuth 보조 쿠키 | 인증 주체가 아닌 내부 보조 쿠키로 결정, 속성·소비·정리·사전 속도 제한 정의 | member_sessions |
| f 활성 시각 이중 원천 | graph_versions.activated_at 제거, 이력에서 파생; active 변경과 이력은 원자 저장 | graph_versions/activations |
| g 관리자 집계·슬롯 제약 | Dashboard/Overview도 admin scope만 집계; queued/running 하나인 부분 UNIQUE | analysis_jobs |
| h 기업 ID 검색 | id 정확 일치 PK 검색 및 ticker/이름/별칭 분기 병합 | companies |
| 낮음: 관리자 만료 | idle_expires_at <= expires_at CHECK | admin_sessions |
| 낮음: 아침 비교 대상 | 같은 KST 날짜·morning·발행본 확인 및 자기 참조 금지 | briefing_rounds |
| 낮음: 발행 필수 필드 | published_at 존재 시 review_revision/payload/생성 시각 필수 | briefing_rounds |
| 낮음: 약관 기간 겹침 | btree_gist + tstzrange [) exclusion constraint | term_versions |
| 낮음: 짧은 검색어 | 3자 미만 부분 검색의 인덱스 한계와 순차 검색 허용 명시 | companies |
| 낮음: replay 용어 | execution_mode의 reuse를 replay로 통일 | ai_executions, enum 표 |
| 낮음: 공개 회차 상태 | scheduled/missing→not_ready, verifying→generating 등 매핑 | briefing_rounds |
| 본문 작업 메타 | 소스 경로·실행 검증 한계·과거 반영표를 이 변경 이력으로 이동 | ERD 본문 및 본 문서 |

v6 최초 반영 당시 테이블은 35개로 유지했다. 이후 2026-10-17 챗봇 호출 관측 테이블 추가로 현재는 36개다. 검증 문서가 제시한 전역 revision 문구 중 BriefingPayload를 현재 MAX로 해석할 수 있는 부분은 발행 당시 고정값으로 구체화했다. 오래된 분석 결과에 현재 revision만 붙이지 않도록 커밋 시 입력 revision 일치 검사도 추가했다.

내부 보조 쿠키를 선택했으므로 OAuth API 문서의 Set-Cookie 설명 동기화는 구현 시 필요하다. 이번 변경은 ERD 문서에 그 계약을 정의했으며 OpenAPI 자체를 수정하지 않았다. 최초 관리자 큐 설계는 하나의 queued/running 슬롯이었으나, 상단 추가 변경에서 복수 queued·단일 running 정책으로 대체했다.

기존 briefing_issue 회차 식별과 공개 graphVersion NULL 충돌 등 외부 계약 미결은 유지했다. 새 displayName 기본값 등 v5의 제안 정책은 API에서 이미 확정된 사실로 취급하지 않는다.

## 문서 점검 범위

현재 테이블 36개와 번호 01~36, v3.5 테이블 60개의 이동 대응, 저장소 API operationId 86개의 대응을 정적으로 점검한다. 이름 대응 확인은 모든 DTO 필드와 실행 동작의 완전 검증을 의미하지 않는다. SQL 마이그레이션·서버 코드는 변경하지 않았으며 PostgreSQL 제약·동시성 실행 검증은 수행하지 않았다.

## 이전 v5 반영 이력 (보관)


| 검증 항목 | v5 처리 | 위치/남은 조건 |
| --- | --- | --- |
| 높음 1: 모의 계좌 필수 필드·현금 NULL | account_id, label, active 복원; 현금 컬럼의 동시 NULL CHECK | mock_portfolios; cash=null과 실제 0 구분 |
| 높음 2: 활성화 행위자·adminEmail | actor_kind, NOT NULL 이메일 snapshot, system 표식 및 CHECK 복원 | graph_activations; pointer_changed도 복원 |
| 높음 3: OAuth와 guest 혼합 | oauth_pending 및 별도 쿠키·집계 제외 | member_sessions; 공개 kind enum 변경 없음 |
| 중간 4: 거래소별 ticker | exchange_code+ticker 부분 UNIQUE | companies |
| 중간 5: 보유 JSON 조인·FK 손실 | mock_holdings 복원, 기업 FK 및 역방향 인덱스 | 총 35개; holdingMembers·개인화 관계 조회 |
| 중간 6: 검수 상세 이중 원천 | detail 제거, 원천 version/revision 조회, 현재 candidate 부분 UNIQUE | review_targets; 원천 snapshot 조회 지원 필요 |
| 중간 7: 복구 키 충돌 | 시도 번호 포함 recoveryKey 및 save_only 원본 참조 | chat_jobs.attempts; 불변 파일 쓰기 |
| 중간 8: 누락 제약 6종 | rank 1~3/중복 금지, window CHECK, 활성 시도 UNIQUE, 토큰 일치, 생성 당시 pending 건수 불변, CSRF HMAC 복원 | briefing_rounds/attempts, graph_versions, 세션 |
| 중간 9: 내부 투영과 관리자 잠금 | scope 도입, 관리자 API/JobLock에서 internal_projection 제외 | analysis_jobs; 실제 그래프 쓰기는 공통 대상 잠금 |
| 이월: 선택 displayName | 생략 시 기본 표시명 저장 정책 명시 | members; `회원`은 v5 제안값 |
| 이월: 회원 가명 ID | 난수 기반 members.id와 통계 키 구분 | members; 짧은 예시 형식 강제 안 함 |
| 이월: 기업 aiQuestions JSON 스캔 | 고정 context_company_ids와 GIN 인덱스 | chat_jobs; 기업 해석 범위는 API 산식과 동기화 |
| 이월: 세션 수와 정리 | 인증 만료와 통계용 메타데이터 보존 분리 | member_sessions; 보존 일수/조회 기간 수치는 미결 |
| 이월: enum 누락 | 폐쇄 enum/내부값/외부 식별자 구분 | 제10절; role 값은 배포 registry에서 확정 |
| 이월: 부분 일치 검색 인덱스 | search_text 파생 컬럼+pg_trgm GIN, 원소별 재확인 | companies; 확장 설치는 구현 단계 |
| 이월: guest transcript 도달 불가 | member만 생성, guest enum은 계약 정리 대상으로 명시 | 제10절; 임의 guest 기능 추가 없음 |
| 서술: 일정·인력 범위 | v4 일정표 제거 | ERD에 저장 구조와 계약만 유지 |
| 서술: API에 없는 holding ID | holding ID 보존 주장 제거, 프로필+기업 복합 PK | mock_holdings |
| 유지: 평가 회차/graphVersion NULL 충돌 | 미결 상태 유지 | 제8절; API를 임의 변경하지 않음 |

제약과 조회 정책은 설계 문서에 반영했다. 원천 snapshot 인터페이스·보존기간·공개 평가 대상 같은 외부 계약까지 확정됐다는 의미는 아니다. 실행 SQL의 구현과 테스트는 이 문서 수정 범위에 포함하지 않는다.
