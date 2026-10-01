# PoC 백엔드 조사: 프론트엔드 연동 경계

> 범위: `/Users/asqi/InvestMateLogicTest`를 읽기 전용으로 조사했다. 아래의 `src/`, `runtime/`, `examples/`, `POC_*.md`, `compose.yaml`, `pyproject.toml` 경로는 모두 **이 PoC 저장소 루트 기준**이다. PoC 구현 사실과 신규 BFF 제안을 구분했다. 실제 뉴스 기반 실험은 운영 서비스의 사실 인증이나 투자 판단 근거가 아니다. [출처: `POC_REPORT.md:465-494`]

## 1. 아키텍처·실행 경계와 실험 결론

- **구현됨:** Python 3.12+ 패키지 `src/investmate`, `uv run poc` 콘솔 진입점이다. `domain.py`는 불변 Pydantic JSON 계약, `collection.py`·`crawler.py`·`fetching.py`는 RSS/Atom·NAVER API HUB·게시자 검색과 제한 크롤링, `source_policy.py`·`source_tools.py`는 허용 출처/조회, `source_pdf.py`는 PDF 추출, `providers.py`·`prompts.py`는 LLM/임베딩/정확한 재생 계약, `search.py`는 B0~B4 검색, `pipeline.py`는 추출→사건 후보 검색·비교→기업 관계 후보→검증→승인/보류 오케스트레이션, `verification_agent.py`·`web_evidence.py`·`jev.py`·`decision.py`는 독립 출처 조사/인용 검사/구조화 판정, `storage.py`는 PostgreSQL 승인 원장·체크포인트·outbox, `graph.py`는 Neo4j 승인 결과 투영이다. `redis_cache.py`는 선택적 발견 캐시이며 원장을 대체하지 않는다. [출처: `POC_SPEC.md:398-423,1331-1347,1373-1385`; `pyproject.toml:1-34`; `src/investmate/cli.py:191-218`; `src/investmate/graph.py:1-16`]
- **흐름:** 원문 수집·권한/버전 고정 → 기사별 `Extraction.mentions` 추출 → pgvector/규칙으로 기존 이슈 후보 검색 및 `PairDecision`(`SAME/DIFFERENT/FOLLOWS/CONFLICT/HOLD`) 비교 → 기사·이슈·기업 관계 `Candidate` 조립 → 원문 위치 검사 + 선택적 웹 조사(`WebDossier`, 원문 인용) + LLM 또는 Jev 의미 검증 → `ALLOW/HOLD/REJECT` 별도 기록 → 승인 원장·Neo4j 투영. 검색 유사도는 승인이 아니며 원장이 권위 데이터다. [출처: `src/investmate/domain.py:101-108,152-196,311-358`; `src/investmate/search.py:1-2,101-113`; `src/investmate/ports.py:130-149,178-187`; `src/investmate/storage.py:618-694`]
- **외부 의존성:** OpenAI 호환 채팅·임베딩(별도 임베딩 주소 선택 가능), 선택적 TypeSafe Jev 검증, PostgreSQL/pgvector, Neo4j, 선택적 Redis 캐시다. RSS·NAVER API HUB·게시자 검색 및 출처 도구에서 OpenDART/Naver/공식 자료 검색과 GDELT·Exa·Tavily 등은 **설정·권한·제공자별 사용 가능성에 종속**된다. 필요한 키/출처 허가 없이는 실제 모델/출처 호출을 실행하지 않는다. 기본 실행에 유료 API를 자동 호출하지 않고 `--live`를 명시해야 한다. [출처: `src/investmate/cli.py:109-185,448-486`; `src/investmate/collection.py:35-46`; `POC_SPEC.md:1113-1145,1244-1315`; `POC_REPORT.md:444-450`]
- **로컬 기동 방법(안내, 실행하지 않음):** `uv sync --locked` → `docker compose up -d` → `uv run poc init-db` → `uv run poc run --dataset examples/synthetic/articles.jsonl --config examples/synthetic/settings.json --replay examples/synthetic/replay.json --output /tmp/zoop-poc-run.json` → `uv run poc inspect --with-evidence --output /tmp/zoop-poc-inspect.json`. `init-db`와 `run`은 DB/그래프를 변경하므로 이번 읽기 전용 조사에서 **실행하지 않았다**. `compose.yaml`에는 로컬 바인딩 PostgreSQL(pgvector, `55432`), Neo4j(HTTP `57474`, Bolt `57687`), Redis(`56379`)가 있다. 의존성은 `httpx`, `pydantic`, `psycopg`, `neo4j`, `redis`, `newspaper4k` 등이며 `poc = investmate.cli:main`이다. `.env`를 자동으로 읽지 않으며 실제 호출에는 환경 주입과 `--live`가 필요하다. 비밀값은 조회하지 않았다. [출처: `POC_REPORT.md:518-526`; `POC_SPEC.md:425-453,494-497`; `compose.yaml:1-48`; `pyproject.toml:1-34`; `src/investmate/cli.py:1-2,132-185`]
- **명세와 결론:** `POC_SPEC.md`는 이슈를 주제가 아닌 식별 가능한 구체적 사건으로 정의하고, 직접/구조적 관련성 및 `REPORTS`/배경을 구분한다. `POC_REPORT.md`는 근거·버전·보류/오류·철회와 승인 투영을 잇는 로컬 PoC가 가능하다고 결론 내렸지만, 고정 자료 19건은 기업 발표·공시 위주이고 사람 확정 정답셋·대표성·금액 비용·운영 정확도는 검증되지 않았다고 명시한다. 적절한 다음 단계는 **근거 확인과 사람 검토 중심 로컬 프로토타입**이지 자동 투자판단 서비스가 아니다. [출처: `POC_SPEC.md:80-105,108-150`; `POC_REPORT.md:19-29,436-494`]
- **검증기 A/B의 시차 있는 결론:** `POC_VERIFIER_AB.md` 초기 단회 10건 비교에는 사람 정답 기반 정확도가 없다고 명시했으나, 이후 `POC_VERIFIER_AB_REVIEW.md`의 AI 보조 권장 라벨을 사용자가 승인했고 `POC_VERIFIER_AB_RESULTS.md`가 이를 집계했다. 비교 가능 대상 22개에서 범용 LLM과 Jev 확대 정책의 라벨 일치는 각각 17/22, Jev 기본은 15/22다. 범용 LLM 과잉 승인 5건, Jev 확대 과잉 승인 1건/과잉 보류 4건이며 관계 13개에서는 Jev 확대 12/13 대 범용 LLM 9/13이다. 따라서 **관계 게시 경로는 Jev 유지**라는 실험 결론을 따른다. 독립 2인 라벨이나 대규모 일반화·REJECT 성능·금액 비용을 뜻하지 않는다. [출처: `POC_VERIFIER_AB.md:9-11,89-120`; `POC_VERIFIER_AB_REVIEW.md:7-11`; `POC_VERIFIER_AB_RESULTS.md:9-10,49-60,96-117,146-155`; `POC_SPEC.md:1512-1543`]

## 2. 데이터 모델: 사건·관계·근거와 없는 데이터

| 구분 | 실제 필드·의미 | 출처 |
|---|---|---|
| 기사·원문 | `Article(article_id,url,title,body,publisher,published_at,collected_at,language,input_kind,origin_id,withdrawn,allow_model_send,synthetic)`; `input_kind=body/summary`, 내용 해시 기반 `version`이다. RSS의 검색 요약은 사건 요약이 아니라 수집 입력이다. | `src/investmate/domain.py:39-56`; `src/investmate/collection.py:116-155` |
| 원문 사건 | `Mention(mention_id,article_id,article_version,title,event_type,action,target,event_time,period,assertion_status,participants,evidence,keywords,background,countries)`와 `Participant(company_id,name,role)`; `Extraction.mentions`는 승인된 이슈가 아니다. `IssueSnapshot(issue_id,mentions,articles)`는 승인된 현재 언급을 묶는다. | `src/investmate/domain.py:75-103,361-364`; `POC_SPEC.md:84-94` |
| 원문 근거 | `Evidence(article_id,article_version,start,end,quote)`; `matches()`는 같은 버전 본문 `[start:end]`가 `quote`와 같아야 한다. 별도의 웹 자료에는 `WebCitation(document_id,version,source_id,tier,url,title,content_hash,fetched_at,body_scope,allow_model_send,published_at,start,end,quote)`가 있다. **인용 위치의 일치와 의미적 지지는 별개**다. | `src/investmate/domain.py:59-72`; `src/investmate/web_evidence.py:26-60`; `POC_SPEC.md:144-148` |
| 후보·검증 | `Candidate(candidate_id,issue_id,mention,articles,relations,prior_issues,policy_version,extraction_version,supersedes)`와 내용 기반 `revision`; `Validation(candidate_id,candidate_revision,policy_version,verdicts,verifier_version,trace,field_verdicts,web_dossier,web_dossier_digest)`. `Verdict(target,decision,reason)`에서 `target="issue"` 또는 정확한 `relation_id`; 날짜·기간·국가의 `FieldVerdict(field,decision,reason)`는 독립 게시 여부를 결정한다. Jev `VerificationObservation(question_id,target,check,choice,probabilities,confidence,numerical_diagnostics)`는 **감성 점수**가 아니라 진술 근거에 대한 의미 검증이다. | `src/investmate/domain.py:174-196,218-252,311-358`; `src/investmate/storage.py:656-666` |
| 기업·기준 관계 | `Company(company_id,name,aliases,ticker)`와 `BasisEdge(edge_id,source,target,relation_type,source_url,verified_at,valid_from,valid_until,countries,approved)`. 기준 관계 `PRODUCES/SUPPLIES/USES/MANUFACTURES/BUYS/DEVELOPS`는 적용 기간·국가·승인 조건을 통과해야 구조적 간선 후보에 사용된다. | `src/investmate/domain.py:111-149,403-425` |
| 그래프 간선 | `Relation(relation_id,source,target,relation_type,role,assertion_status,evidence,basis)`의 다섯 유형: `Article → Issue`의 `REPORTS`(현재 보도)·`PROVIDES_BACKGROUND`(과거 배경), `Issue → Company`의 `INVOLVES`(명시적 역할)·`STRUCTURALLY_RELATED_TO`(검증된 기준 관계를 통한 관련성), `Issue → Issue`의 `FOLLOWS`(후속). `Company → Company` 승인 그래프 간선, 인과적 `DIRECTLY_AFFECTS`는 없다. | `src/investmate/domain.py:152-167`; `src/investmate/graph.py:92-122`; `POC_SPEC.md:108-127` |
| 그래프 노드·저장 표현 | Neo4j 라벨 `InvestMateIssue:Issue`의 `issue_id,active,mentions_json,field_decisions_json,candidate_ids,articles_json`, `InvestMateArticle:Article`의 `article_id,url,title,publisher,published_at`, `InvestMateCompany:Company`의 `company_id`. 관계에는 `investmate_owner,relation_id,role,assertion_status,evidence_json,basis_json,candidate_ids,relation_json`을 저장한다. 기업 이름/시세가 Neo4j 노드에 자동 저장되지는 않는다. | `src/investmate/graph.py:21-30,61-122` |
| 게시·감사 뷰 | `PostgresRepository.inspect(issue_id)`는 `{issues:[{issue_id,mentions,articles,relations,candidate_ids,field_decisions,source_support}],candidates:[{candidate,validation,status,active,reasons,invalidation_reason}],errors:[]}`를 만든다. 이슈에는 **현재 ALLOW만**, 후보에는 보류·반려 기록도 남는다. 미승인 `event_time/period/countries`는 게시 언급에서 빠지고 감사에는 남는다. `source_support`는 `article_count,known_lineage_count,unknown_lineage_articles,independent_source_count,duplicate_groups`이다. | `src/investmate/storage.py:574-694`; `src/investmate/ports.py:144-149` |
| 요약·감성·브리핑 | **구현 없음:** AI 기업 요약, 이슈 설명문 생성, 긍/부정 감성 또는 주가 영향 평가, 출퇴근 브리핑, 사용자/계좌/포트폴리오/관심목록 모델은 `src/investmate/domain.py` 모델에 없고 PoC 범위에서도 제외된다. `Article.input_kind="summary"`는 RSS 수집 요약이며 AI 요약이 아니다. `VerificationObservation.probabilities`는 검증기 진술 확률이지 호재/악재 확률이 아니다. | `src/investmate/domain.py:39-52,227-252,403-425`; `POC_SPEC.md:55-65`; `POC_REPORT.md:19-29` |

## 3. 현재 연동 가능한 표면: HTTP, CLI, Python

- **기존 HTTP 제품 API는 없다.** `src/investmate/cli.py:1-2`가 “No HTTP server, user accounts”를 선언하고 `pyproject.toml:19-20`은 CLI만 등록한다. `web_approval`은 HTTP 라우트가 아니라 `run/loop/reassign/activate-policy`에 붙는 `--web-verify --live --web-sources-config` 검증 옵션으로, 웹 자료 근거를 제3자 출처에서 읽은 뒤 독립 Jev 판정에 전달한다. 따라서 프론트엔드가 호출할 기존 GET/POST 경로, HTTP 요청·응답 스키마, 로그인 엔드포인트는 **없다**. `neo4j` HTTP 포트는 DB 인터페이스이지 사용자용 BFF가 아니다. [출처: `src/investmate/cli.py:1-2,89-105,268-445,462-486`; `compose.yaml:18-26`; `POC_SPEC.md:1339-1347`]
- **CLI 조회:** `uv run poc inspect [--issue ID] [--with-evidence] [--graph] [--output PATH]`. 기본 출력은 `issues`에서 `articles`와 관계의 `evidence`를 빼고 `candidates`도 제거한다. `--with-evidence`는 원문/감사 근거를 포함한다. `--graph`는 `--issue`가 필요하며 Neo4j 투영을 **진단용**으로 추가한다. 최신 승인은 PostgreSQL `issues`를 기준으로 확인한다. `policy-status`는 활성 정책을 조회하고 `sources`는 출처·도구 능력을 조회한다. [출처: `src/investmate/cli.py:314-325,379-400,624-661`]
- **CLI 변경/실험:** `init-db`, `ingest`, `crawl`, `run`, `loop`, `reassign`, `flush-graph`, `activate-policy`는 저장소/크롤 결과 변경 가능성이 있으므로 읽기 전용 화면 조회로 호출하지 않는다. `review-export --snapshot FILE --review-file ... --judgments-file ...`, `review-compare --review FILE --profiles FILE [--judgments FILE]`, `fact-check --candidate-file FILE --live`, `evaluate`, `benchmark`도 있다. `crawl`은 DB 없이도 수집 파일을 저장하고 네트워크를 쓴다. `fact-check --live`는 모델·출처 API를 호출하므로 오프라인 명령이 아니다. [출처: `src/investmate/cli.py:273-445,501-533,534-595,596-746`]
- **Python에서 BFF가 사용할 수 있는 실제 읽기 진입점:** `PostgresRepository.inspect(issue_id: str|None)`의 현재 승인·감사 뷰, `Neo4jGraph.inspect(issue_id)`의 *진단용* 투영, `PostgresRepository.articles()/article(article_id,version)` 원문 버전 조회, `AnalysisModel.extract/compare/validate/embed` 프로토콜과 `Pipeline.run(articles)` 배치 처리 경계가 있다. BFF에서는 승인 조회를 `Repository.inspect` 중심으로 구성하고 DB 접속·전송 권한·현재 정책 검사를 서버에서 담당해야 한다. `SourceTools`/`VerificationAgent`는 별도의 출처 조회와 검증 작업이지 공개 사용자용 HTTP 라우트가 아니다. [출처: `src/investmate/ports.py:59-73,124-149`; `src/investmate/pipeline.py:66-72,832-834`; `src/investmate/graph.py:125-162`; `src/investmate/source_tools.py:207-239`; `src/investmate/verification_agent.py:214-229`]

## 4. 실제 보관된 JSON과 프로토타입 데이터 선택

| 파일(모두 `runtime/` 기준) | 실제 모양·짧은 사례 | 사용 경계·출처 |
|---|---|---|
| `real-news-batch-v1/dataset.jsonl`, `real-news-batch-v1/manifest.json` | 기사 JSONL의 `article_id,title,body,url,publisher,published_at,input_kind,origin_id,allow_model_send,synthetic` 등. 매니페스트와 보고서상 실제 자료 19건, 본문 범위 18건, 부분 원문 1건은 승인 입력 제외. 원문 기사 목록이지 승인된 그래프/감성 결과가 아니다. | `runtime/real-news-batch-v1/dataset.jsonl:1-2`; `runtime/end-to-end-integration-summary.json:1-11`; `POC_SPEC.md:1331-1336` |
| `llm-workflow-contract-graph.json`, `llm-workflow-earnings-graph.json` | `{issues:[{issue_id,mentions,relations,candidate_ids,source_support}],errors:[],projection:{issues,...}}` 형태의 **합성 LLM 실험 조회 스냅샷**. 계약 예시는 한 `issue_id`에 합성 기사 2개 `REPORTS`와 공급사/구매사 `INVOLVES` 4개가 붙는다. 실적 예시는 `target="2026년 2분기 확정 실적 …"`, `period="2026 Q2 …"`, `INVOLVES.target="SYN-HAEUN"`. 원시 스냅샷의 관계에는 `evidence`가 생략되어 있으므로 실제 근거 조회는 `inspect --with-evidence` 또는 `mentions[].evidence`를 사용해야 한다. **실제 시장 데이터로 표기하지 않는다.** | `runtime/llm-workflow-contract-graph.json:2-67,119-203`; `runtime/llm-workflow-earnings-graph.json:1-89`; `src/investmate/cli.py:644-660` |
| `web-approval-live/final-partition-1.json` | `RunReport` 형태 `{run_id,processed,skipped,errors,held,rejected,approved,pending,usage,web_usage,search_results,...}`. 한 실측 파일은 `processed=20`, `held=20`, `approved=0`, `errors`에 검증기 실패가 있다. **그래프나 브리핑이 아니라 운영·실험 진단**이며 `held`를 부정 감성으로 해석하지 않는다. | `runtime/web-approval-live/final-partition-1.json:1-83`; `src/investmate/domain.py:367-400` |
| `source-agent-verified-report.json` | 별도 읽기 전용 검증 보고서: `findings[].{target,status,reason,citations[]}`, 인용의 `document_id,url,content_hash,start,end,quote`, `documents`, `source_availability`. 사례는 `target="issue", status="SUPPORTED"`이며 `completeness="partial"`이므로 최종 게시 `ALLOW`나 사용자용 이슈 요약이 아니다. 인용 증거 패널의 **형식 참고 자료**로만 사용한다. | `runtime/source-agent-verified-report.json:1-41,75-98`; `src/investmate/web_evidence.py:26-60` |
| `verifier-ab-review/index.json`, `verifier-ab-v1/summary.json`, `numeric-review-v1/summary.json` | 검증기별 사례의 `title,article_url,relations,jev_default,chat_verdicts` 및 비교 집계·수치 오류/보류 평가. 판정 사유와 보류 이유를 설계할 때 쓰는 **실험 자료**이지 게시 이슈/브리핑 원장이 아니다. | `runtime/verifier-ab-review/index.json:1-45`; `POC_REPORT.md:569-584`; `POC_VERIFIER_AB_RESULTS.md:49-60,96-102` |

- **외부 키 없이 가능한 경우:** `examples/synthetic/articles.jsonl`, `settings.json`, `replay.json`은 허구 기업 기사 + 고정 모델 응답이며 `--replay`가 정확한 입력/응답 요청 키가 일치할 때만 재생한다. 전체 파이프라인 `run`에는 DB/Neo4j가 필요하고 저장소를 변경한다. `examples/llm-mock/articles.jsonl`, `smoke.jsonl`, `scenarios.json`은 **모델 호출 관찰용 합성 입력**으로 미리 녹음한 모델 답이 없다. 따라서 `llm-mock`만으로 외부 모델 없이 같은 결과를 재생할 수 없다. `scenarios.json`도 현재 `GoldSet` 형식의 정답셋이 아니다. [출처: `POC_SPEC.md:425-453,733-761`; `examples/synthetic/replay.json:1-8`; `src/investmate/cli.py:132-185`]
- **브리핑/AI 요약/긍·부정 JSON 없음:** 위 파일의 `summary.json`은 실험 **집계**이므로 화면의 기업·이슈 요약이나 금융 브리핑으로 바꿔 부르지 않는다. 기업 패널의 직접 관련 사건 목록은 승인된 `INVOLVES`를 역방향 조회해 만들 수 있지만 서술형 요약·감성은 별도 구현이 필요하다. [출처: `src/investmate/domain.py:81-103,152-167,367-425`; `POC_SPEC.md:55-65`; `POC_REPORT.md:479-494`]

## 5. 읽기 전용 실행 확인

- **실행 1:** PoC 저장소에서 `PYTHONDONTWRITEBYTECODE=1 UV_CACHE_DIR=/tmp/zoop-poc-uv-cache uv run --offline --no-sync poc --help` → 종료 코드 **0**, `usage: poc [-h] {init-db,ingest,crawl,run,loop,inspect,review-export,review-compare,evaluate,benchmark,reassign,flush-graph,policy-status,activate-policy,sources,source-tool,fact-check} ...` 출력. 이 명령은 CLI 도움말만 읽고 프로젝트 입력이나 DB를 쓰지 않는다. [출처: 이 조사에서 실행한 명령 및 관측 출력; `src/investmate/cli.py:268-445`]
- **실행 2:** PoC 저장소에서 `PYTHONDONTWRITEBYTECODE=1 UV_CACHE_DIR=/tmp/zoop-poc-uv-cache uv run --offline --no-sync poc review-compare --review runtime/decision-policy-v1/review.json --profiles examples/decision-profiles.json --output /tmp/zoop-poc-review-compare.json` → 종료 코드 **0**, 출력 JSON의 상위 키에 `counts`, `profiles`, `warnings`, `label_coverage`가 있고, `/tmp/zoop-poc-review-compare.json`을 `jq`로 확인하니 `schema_version="decision-review-1"`, `counts.candidate_audit_rows=92`, `counts.questions=1605`, `certified=false`, `adjudicated_questions=0`, `label_coverage=0.0`, 프로파일 4개였다. **오프라인 과거 응답의 정책 비교 성공**이지 사람 확정 정답이나 그래프 게시 결과가 아니다. `review-compare`는 로컬 JSON을 로드해 비교만 하며 DB 연결 분기보다 앞에서 반환한다. [출처: 이 조사에서 실행한 명령 및 관측 출력; `src/investmate/cli.py:48-54,501-508`; `POC_REPORT.md:528-538`]
- **최초 조사에서 미실행:** 그때는 원본 PoC의 `init-db/run/inspect`와 DB 연결을 실행하지 않았다. 아래 7절의 별도 승인에 따라 **격리된 `/tmp` 사본과 전용 Docker 프로젝트에서만** 이 경로를 추가 확인했다. `llm-mock --live`, 실제 RSS/크롤링, 테스트·빌드·린트는 여전히 실행하지 않았다. 실제 뉴스의 승인·브리핑 생성 동작을 확인한 것은 아니다. [출처: `src/investmate/cli.py:578-622,697-746`; `POC_SPEC.md:425-453,733-761`; 아래 7절의 실행 기록]

## 6. 제안: 프로토타입 BFF/API 초안과 매핑

> 아래 경로와 응답 이름은 모두 **[제안] 새 BFF 계약**이다. PoC에 존재하는 HTTP 경로가 아니다. 기본 그래프는 `PostgresRepository.inspect()`의 현재 `issues`에서 구성하며 원문 및 보류 감사는 명시적으로 권한을 나누어 조회한다. 테스트용 합성 스냅샷은 `dataset_kind="synthetic-preview"`, 실제 승인 조회는 `dataset_kind="approved"`처럼 **별도 표기**해야 한다. `HOLD`/`REJECT`를 현재 승인 간선으로 섞지 않는다. [출처: `src/investmate/cli.py:1-2`; `src/investmate/storage.py:618-694`; `POC_REPORT.md:479-486`]

| 화면·메서드·경로 **[제안]** | 응답 필드 **[제안]** → PoC 출처 | 없는 부분 / 규칙 |
|---|---|---|
| 브리핑 `GET /api/briefings?slot=commute-to-work|commute-from-work` | `{slot,as_of,items:[{issue_id,title,event_time,article_urls,company_ids,source_support,verdict_state}],dataset_kind}` → `inspect().issues[].{issue_id,mentions[].title/event_time,articles[].url,relations[].target,source_support}`; 게시된 이슈의 `verdict_state=ALLOW`만 파생. [출처: `src/investmate/storage.py:618-694`; `src/investmate/domain.py:81-98`] | **갭:** 출퇴근 시간대 저장/생성·개인화·우선순위·AI 브리핑 문장·감성·시장 가격 없음. `as_of`는 BFF 조회 시각으로 만들고 사건시각 `event_time`과 혼동하지 않으며 근거 없는 `top story`를 만들지 않는다. [출처: `POC_SPEC.md:55-65`; `src/investmate/domain.py:81-98,387-425`] |
| 그래프 `GET /api/graph?mode=market|assets|watchlist` | `{mode,dataset_kind,nodes:[{id,kind,label}],edges:[{relation_id,source,target,relation_type,role,assertion_status}],filters}` → `inspect().issues`의 이슈/언급/승인 `relations`; `Company.name`은 `Settings.companies` 같은 별도 카탈로그에서 보강. `market`은 현재 승인된 부분 그래프만 뜻한다. [출처: `src/investmate/storage.py:618-694`; `src/investmate/domain.py:152-167,403-425`; `src/investmate/graph.py:61-122`] | **갭:** 시장 전체 데이터셋, 로그인·연결 계좌·보유자산·관심종목이 없다. `assets`/`watchlist`는 새 인증된 사용자 데이터에서 `company_id` 필터를 받아야 하며, 미연결 상태는 빈 데이터+명시 상태로 반환한다. 기업–기업 화면 간선은 승인 `Issue` 경유의 **설명 가능한 가상 탐색 경로**로만 표시하고 `Relation` 실간선인 척하지 않는다. [출처: `POC_SPEC.md:55-65,108-127`; `src/investmate/graph.py:96-112`] |
| 기업 패널 `GET /api/companies/{company_id}` | `{company_id,name,ticker,aliases,direct_issues:[{issue_id,role,event_time}],structural_issues:[{issue_id,basis,source_support}],summary:null,sentiment:null}` → `Settings.companies`, `relations[INVOLVES|STRUCTURALLY_RELATED_TO].{target,role,basis}`, 해당 `issues.mentions[].event_time`·`source_support`. [출처: `src/investmate/domain.py:111-167,403-425`; `src/investmate/storage.py:684-694`] | **갭:** 기업 기본 재무·시세·AI 요약·종목 상세 및 긍/부정 없음. `STRUCTURALLY_RELATED_TO`는 사업 구조상의 관련성이지 투자 영향/직접 참여가 아니다. `summary`와 `sentiment`는 생산자가 생기기 전 `null`/`unavailable`로 응답한다. [출처: `POC_SPEC.md:108-127`; `POC_REPORT.md:479-487`] |
| 이슈 상세 `GET /api/issues/{issue_id}` | `{issue_id,mentions:[{mention_id,title,action,target,event_time,period,assertion_status,participants}],articles:[{article_id,title,publisher,url,published_at}],relations,source_support,field_decisions,evidence:[{article_id,article_version,start,end,quote}],summary:null}` → `inspect(issue_id)`의 현재 승인 이슈·`Mention`·`Article`·`Evidence`, `field_decisions`; 보류 감사 항목은 별도 운영자 조회에만 둔다. [출처: `src/investmate/storage.py:618-694`; `src/investmate/domain.py:39-98`] | **갭:** 사용자용 AI 요약·긍/부정은 없다. `event_time/period/countries`가 미승인으로 게시에서 빠졌으면 값을 기사 발행일로 채우지 않는다. 원문 `body`/전체 인용 노출은 저장·전송 이용 권한에 따라 별도 접근 제어가 필요하다. [출처: `src/investmate/storage.py:655-666`; `POC_SPEC.md:98-105`; `POC_REPORT.md:479-487`] |
| 간선 상세 `GET /api/edges/{relation_id}` | `{relation_id,source,target,relation_type,role,assertion_status,evidence:[{article_id,article_version,start,end,quote}],basis:[{edge_id,relation_type,source_url,verified_at,valid_from,valid_until,countries}],candidate_ids,review_status}` → `inspect().issues[].relations[]`의 승인 간선; `Candidate/Validation`은 권한 있는 운영자용 감사 화면의 `inspect(...).candidates`. [출처: `src/investmate/domain.py:111-167,174-196,327-358`; `src/investmate/storage.py:630-694`] | **갭:** 현재 PoC에 간선별 HTTP 인덱스/조회는 없으므로 BFF에서 승인 뷰를 색인해야 한다. `REJECT/HOLD` 간선은 공개 그래프에 실리지 않으며 검증기 `SUPPORTED`를 긍정 감성으로 바꾸지 않는다. `basis`가 빈 직접 간선과 구조 간선을 구별한다. [출처: `src/investmate/storage.py:642-683`; `POC_SPEC.md:119-150`] |

**[제안] 계약 결정 전 남는 질문:** 사용자 인증/계좌 연결·보유/관심종목의 권위 출처, 기사 원문/인용 재배포 허가, 요약·감성의 주체와 사람 검토 정책, ‘시장 전체’의 실제 수집 범위가 이 PoC에는 없다. 이것들이 정해지기 전에는 승인 이슈의 원문 근거 탐색만 실제 PoC 연동으로 선언할 수 있다. [출처: `POC_SPEC.md:55-65,108-127`; `POC_REPORT.md:436-454,479-494`]

## 7. 격리 샌드박스 라이브 실행

- **격리와 설정(합성 검증 당시):** `rsync -a --exclude .venv --exclude .pytest_cache --exclude .ruff_cache --exclude .env /Users/asqi/InvestMateLogicTest/ /tmp/investmate-sandbox/`를 실행했다(종료 코드 0). 이 단계에서는 원본의 `.env`와 비밀키를 복사하거나 읽지 않았고 샌드박스에도 별도 `.env`가 필요하지 않았다. 합성 replay는 `cli._connections()`의 로컬 기본 접속 설정을 사용했으며 원본 PoC 파일은 수정하지 않았다. `PYTHONDONTWRITEBYTECODE=1`과 `uv run --offline --no-sync`를 사용해 외부 모델/뉴스 API 호출 없이 실행했다. 이후 8절의 별도 승인에 따라 `.env` 파일을 사본으로 복사했으므로 두 시점을 구분한다. [출처: 이 후속 조사 실행 기록; `src/investmate/cli.py:109-129,132-185`; `compose.yaml:1-26`]
- **독립 DB:** `docker compose -p zoop-poc -f /tmp/investmate-sandbox/compose.yaml up -d postgres neo4j`가 종료 코드 0으로 완료됐고 전용 `zoop-poc_*` 네트워크·볼륨/컨테이너를 만들었다. `docker compose ... ps --format json`은 두 컨테이너 `running`, PostgreSQL `healthy`, 호스트 `127.0.0.1:55432` 및 Neo4j `127.0.0.1:57474,57687` 바인딩을 보고했다. `PYTHONDONTWRITEBYTECODE=1 uv sync --offline --locked`로 **사본 내부** `.venv`에 패키지 43개를 설치했다(종료 코드 0). 컨테이너는 후속 프로토타입 개발을 위해 **켜 둔 상태**다. [출처: 이 후속 조사 명령 및 실제 출력; `compose.yaml:1-48`; `pyproject.toml:1-34`]
- **스키마·합성 배치(사본 작업 디렉터리에서 실행):** `PYTHONDONTWRITEBYTECODE=1 uv run --offline --no-sync poc init-db --output /tmp/zoop-init-synthetic.json` → 종료 코드 0, `initialized=[PostgreSQL,pgvector,Neo4j]`. `PYTHONDONTWRITEBYTECODE=1 uv run --offline --no-sync poc run --dataset examples/synthetic/articles.jsonl --config examples/synthetic/settings.json --replay examples/synthetic/replay.json --output /tmp/zoop-run-synthetic.json` → 종료 코드 0, `processed=5,approved=4,held=1,rejected=0,errors=[],execution_mode=\"replay\"`. 이는 미리 녹음한 가상 기사 응답의 **실제 DB 저장·승인 경로 확인**이지 실제 뉴스 판단 성능 검증이 아니다. [출처: `/tmp/zoop-init-synthetic.json`; `/tmp/zoop-run-synthetic.json`; `examples/synthetic/replay.json:1-8`; `src/investmate/cli.py:596-622,697-746`; 이 후속 조사 명령 및 출력]
- **승인 조회:** `PYTHONDONTWRITEBYTECODE=1 uv run --offline --no-sync poc inspect --with-evidence --output /tmp/zoop-inspect-synthetic.json` → 종료 코드 0; 실제 JSON의 `issues` **3개**, `candidates` **5개**, 승인 관계 `REPORTS` **4개**·`INVOLVES` **3개**, 참여 기업 ID `SYNTH-ALPHA`, 관계의 `evidence`가 적어도 하나 이상 존재, `errors=[]`를 `jq`로 확인했다. `--issue issue-b4c3b887f7cbb6aa9ca6f2cf --with-evidence --graph --output /tmp/zoop-graph-synthetic.json` → 종료 코드 0, 권위 원장 이슈 1개와 Neo4j 투영 이슈 1개, 투영 관계 4개(`INVOLVES` 2, `REPORTS` 2). 투영 응답도 `projection_note=\"Diagnostic projection; only authority issues are current approvals.\"`를 반환한다. [출처: `/tmp/zoop-inspect-synthetic.json`; `/tmp/zoop-graph-synthetic.json`; 이 후속 조사 명령 및 출력; `src/investmate/cli.py:644-661`]
- **BFF용 Python 직접 조회 확인:** 사본에서 `PYTHONDONTWRITEBYTECODE=1 uv run --offline --no-sync python -c 'from contextlib import ExitStack; from investmate.cli import _connections; from investmate.storage import PostgresRepository; stack=ExitStack(); repo,_=_connections(stack,graph=False); assert isinstance(repo,PostgresRepository); issues=repo.inspect(None)[\"issues\"]; print({\"repository\":type(repo).__name__,\"issue_count\":len(issues),\"first_issue_id\":issues[0][\"issue_id\"]}); stack.close()'` → 종료 코드 0, `{'repository': 'PostgresRepository', 'issue_count': 3, 'first_issue_id': 'issue-b4c3b887f7cbb6aa9ca6f2cf'}`. 즉 BFF는 `PostgresRepository(dsn)`을 접속 설정으로 구성하고 `inspect(None)`을 직접 호출할 수 있으며, 검증한 최소 구성은 CLI `_connections(stack,graph=False)`가 DSN/닫기를 담당한다. **[제안]** 서비스 코드에서는 CLI 내부 함수에 의존하기보다 `PostgresRepository`를 직접 구성하고 연결 종료·접속 설정을 BFF가 소유한다. [출처: 이 후속 조사 명령 및 출력; `src/investmate/cli.py:109-129`; `src/investmate/storage.py:72-75,618-694`]
- **종료 방법(안내만, 실행하지 않음):** `docker compose -p zoop-poc -f /tmp/investmate-sandbox/compose.yaml down -v`는 **이 프로젝트의** 컨테이너와 합성 데이터가 담긴 전용 볼륨을 삭제하므로 프로토타입 개발 완료 후에만 실행한다. 다른 프로젝트의 컨테이너나 볼륨을 종료하지 않는다. [출처: 전용 프로젝트 기동 명령의 관측 출력; `compose.yaml:46-48`]

## 8. 실제 뉴스 라이브 실행

- **입력·격리:** 원본 PoC 파일은 수정하지 않고 `/tmp/investmate-sandbox` 사본에서만 실행했다. 원본 `.env`는 사본으로 파일 복사만 했고 값을 출력하거나 문서화하지 않았다. 합성 DB `investmate`와 별도로 같은 `zoop-poc` PostgreSQL 컨테이너 안에 `CREATE DATABASE investmate_zoop_real`로 DB를 생성했다. 실제 뉴스 DSN은 `127.0.0.1:55432/investmate_zoop_real`(접속 계정은 `compose.yaml`의 개발 전용 로컬 계정)이고, 실행 시 `DATABASE_URL`을 명시해 사본 `.env`보다 우선하는 것을 확인했다. `REDIS_URL=''`로 공유 캐시 연결을 막았으며 Neo4j는 같은 `zoop-poc` 인스턴스의 *진단용 투영*이다. DB·컨테이너는 프로토타입 검증을 위해 계속 켜 두었다. [출처: 이 조사에서 실행한 `docker compose ... exec ... CREATE DATABASE` 및 환경 우선순위 확인 결과; `compose.yaml:1-48`; `src/investmate/cli.py:109-129,191-218`]
- **선택한 자료와 정책:** 동결 자료 `runtime/real-news-batch-v1/dataset.jsonl`의 19건 중 `runtime/web-approval-live/eligible-articles.jsonl`의 **전체 본문 18건**만 처리했다. 두 입력의 `article_id` 집합을 비교해 적격 파일 18건 모두 원래 19건에 포함되고 부분 원문 1건만 빠진 것을 확인했다. `runtime/web-approval-live/final-settings.json`을 **사본 안에** `zoop-real-settings.json`으로 복사한 뒤 현재 `Settings` 계약에 없는 과거 `validation_confidence_threshold` 필드만 제거했다. 나머지 `policy_version`, `max_calls=200`, 기업 3개 등은 유지하고 기본 `DecisionPolicy(support_min=0.90,contradiction_max=0.05,reject_min=0.90)`를 사용했다. 모델 제공자는 사본 `.env`의 `VALIDATION_PROVIDER=jev` 설정 확인 후 실행했고 `--live --web-verify --web-sources-config runtime/web-approval-live/sources.json --web-refresh-revision 1 --web-max-steps 8`로 **웹 근거 + Jev 검증 경로**를 유지했다. [출처: 적격 입력 집합 비교의 관측 결과; `POC_SPEC.md:1331-1346,1350-1369`; `src/investmate/domain.py:198-215,410-425`; `src/investmate/cli.py:89-105,132-185`; `runtime/web-approval-live/final-settings.json:1-43`]
- **실행 명령(사본 루트):** `DATABASE_URL=\"$ZOOP_REAL_DSN\" REDIS_URL='' PYTHONDONTWRITEBYTECODE=1 uv run --offline --no-sync --env-file .env poc init-db --output /tmp/zoop-real-init.json` → 종료 코드 0, PostgreSQL/pgvector/Neo4j 초기화. 첫 회는 같은 접두어에 `poc run --live --web-verify --web-sources-config runtime/web-approval-live/sources.json --web-refresh-revision 1 --web-max-steps 8 --config zoop-real-settings.json --dataset runtime/web-approval-live/eligible-articles.jsonl --output /tmp/zoop-real-run-1.json`을 실행했고, 이후 두 회는 `--dataset` 없이 각각 `/tmp/zoop-real-run-2.json`, `/tmp/zoop-real-run-3.json`으로 저장하여 DB의 현재 기사에서 재개했다. `$ZOOP_REAL_DSN`은 위 전용 DB를 가리키는 명령 표기이며 실제 실행에서는 명시적 접속 문자열을 직접 전달했다. 세 `run`의 종료 코드는 **각각 1**이었다. 이는 남은 작업과 `errors`가 있어 CLI가 실패를 반환한 것으로, 성공으로 재표기하지 않는다. [출처: 이 조사에서 실행한 명령과 `/tmp/zoop-real-init.json`, `/tmp/zoop-real-run-1.json`, `/tmp/zoop-real-run-2.json`, `/tmp/zoop-real-run-3.json`; `src/investmate/cli.py:644-661,697-746,749-770`]
- **시도별 실제 결과:** 1회 `processed=20,approved=1,held=19,rejected=0,pending=11,errors=6,usage.calls=200,web_usage.source_requests=180,elapsed_seconds=1754.03`; 2회 `23,0,23,0,19,9,200,223,2177.69`; 3회 `22,0,22,0,4,12,200,262,2025.79`(숫자 순서는 동일 필드). 세 시도의 처리된 **사건 후보** 합계는 65개, 승인 1·보류 64·반려 0이고 모델 호출 600회, 보고 입력 7,896,703토큰·출력 577,694토큰, 모델 경과 5,342.65초, 출처 요청 665회·다운로드 38,604,515바이트, 전체 관측 경과 5,957.51초였다. 보고된 `estimated_cost`는 모두 `null`이므로 실제 과금액을 추정하지 않는다. 시도별 오류는 6/9/12개(반복된 기존 오류 포함 가능)이며 단계/유형 누계는 추출 `ProviderRequestError` 9, 추출 `ModelResponseError` 2, 사건 언급 `ModelResponseError` 16이다. **마지막 `pending=4`로 동결 코호트 처리가 전부 끝난 것은 아니다.** 승인 수를 채우기 위한 추가 비용을 쓰지 않도록 작업자가 세 번째 시도 이후의 유료 배치/재시도를 중단했다. [출처: `/tmp/zoop-real-run-1.json`, `/tmp/zoop-real-run-2.json`, `/tmp/zoop-real-run-3.json`; 이 조사에서 세 JSON의 `usage`, `web_usage`, `errors`를 집계한 결과; `src/investmate/domain.py:367-400`]
- **확정한 현재 승인 스냅샷:** `DATABASE_URL=\"$ZOOP_REAL_DSN\" PYTHONDONTWRITEBYTECODE=1 uv run --offline --no-sync poc inspect --with-evidence --output /Users/asqi/zoop/prototype/bff/fixtures/poc-real-inspect.json` → 종료 코드 0. 최종 `issues` **1개**, `candidates` 65개(현재 활성 65개; `ALLOW=1,HOLD=64`), 게시 `relations` **0개**, 오류 배열 0개다. 승인 이슈 `issue-47550385860ca5254883430c`의 제목은 **“NVIDIA Vera Rubin NVL72 Delivers Leading Performance in MLPerf Inference v6.1 Debut”**이며 `mentions[].evidence` 인용 1개·기사 1개를 담는다. `mentions[].participants`에는 기업 ID `NASDAQ:NVDA`가 있으나 **승인된 `INVOLVES` 간선이 없어 그래프에서 연결된 기업 수는 0개**다. 참여자 표기와 승인 기업 간선을 혼동하지 않는다. `prototype/bff/fixtures/poc-real-companies.json`에는 당시 설정의 `{companies:[{company_id,name,ticker,aliases}]}` 3개(삼성전자·SK하이닉스·NVIDIA)를 저장했다. 두 `poc-real-*` 원문/설정 fixture는 `prototype/bff/fixtures/.gitignore`의 `poc-real-*` 패턴으로 공개 버전 관리 대상에서 제외한다. [출처: `prototype/bff/fixtures/poc-real-inspect.json`, `poc-real-companies.json`, `.gitignore`; `zoop-real-settings.json:14-42`; `src/investmate/storage.py:618-694`]
- **수집 확대 판단과 남는 제약:** 승인 이슈가 8개 미만이어도 `examples/domestic-rss.json`은 `allow_store_body=false`여서 RSS 요약만 `Article.input_kind=\"summary\"`로 수집하고, `pipeline._rules`가 전체 본문이 없는 사건 후보를 거절한다. 연합뉴스 RSS에는 원문/전송 권한 제약도 기록되어 있다. 따라서 권한을 우회해 본문 저장/모델 전송을 허용하거나 요약만으로 근거 간선을 만드는 **2차 수집·실행은 하지 않았다**. 시연 데이터가 1개인 사실과 마지막 `pending=4`를 그대로 표시한다. [출처: `examples/domestic-rss.json:1-22`; `src/investmate/collection.py:531-579`; `src/investmate/pipeline.py:422-470`; `POC_REPORT.md:420-425,444-450`; 세 번째 실행 결과]
- **원본 무변경 확인의 한계:** 원본에서 요청된 `git status --porcelain`을 실행했으나 `fatal: not a git repository (or any of the parent directories): .git`으로 종료 코드 128이어서 Git 상태로는 증명할 수 없다. 대신 `diff -qr /Users/asqi/InvestMateLogicTest/src /tmp/investmate-sandbox/src`가 차이를 출력하지 않았고 종료 코드 0이었다. 원본의 `.env`를 읽거나 원본에 쓰는 명령은 실행하지 않았다. [출처: 이 조사에서 실행한 Git 명령의 오류와 `diff -qr` 실제 결과]

## 9. 완화 정책 재판정

### 9.1 보류 원인과 결정 경계

- **기존 정책·근거:** 활성 정책은 `real-news-web-approval-1:b43cfd24b4165ce2`, `DecisionPolicy(support_min=0.90, contradiction_max=0.05, reject_min=0.90)`와 필수 canonical 웹 자료였다. 이 임계값은 사람 정답으로 보정된 확률이 아니다. A/B 재검토에서 Jev 확대 프로파일(지지 0.65·반박 0.10)은 비교 가능한 22건 중 과잉 보류 4건·과잉 승인 1건이었고, 그래프 관계 13건에서는 12건 일치했다. 확대 정책이 **안전하다는 뜻은 아니며**, 과잉 승인의 실제 사례는 직접 역할 근거가 약한 `0:INVOLVES`다. 기존 문서가 과잉 보류를 지적하면서도 일괄 하향을 권장하지 않았으나, 이번 시연에서는 사용자의 명시적 완화 승인 아래 별도 정책으로만 실험했다. [출처: 사본 `POC_SPEC.md:959-969`; `POC_REPORT.md:271-285`; `POC_VERIFIER_AB_RESULTS.md:96-155`]
- **실제 DB 기준 분포(겹치는 범주):** 전용 DB `investmate_zoop_real`의 기존 정책 후보에 대한 PostgreSQL 집계에서 `ALLOW=1`, `HOLD=64`, 필수 웹 확인 질문 포함 64건, 수치적 판단 불가 진단 4건이었다. 변경 전 `inspect --with-evidence`의 64건을 질문별로 분석하면 이슈 자체 HOLD 64, 관계도 HOLD 63, 엄격 기준에서 `web_source_support` 지지 부족 64, 원문 핵심 필드 지지 부족 62(제목 46·참여자 역할 첫 항목 30·두 번째 항목 27), 선택 필드 보류 37, 카탈로그에 없는 참여자 ID를 하나 이상 포함한 후보 40, `INVOLVES` 후보 자체가 없는 경우 16이다. 서로 겹치므로 합산하지 않는다. 보류된 **후보**에 모델 오류는 0건이다. 기존 3회 실행 보고서의 추출/언급 모델 오류는 별도로 집계되며, 마지막 `pending=4`도 보류 후보와 구별한다. [출처: 전용 DB `investmate.candidates` 기존 정책 집계; 공개 fixture 갱신 전 백업 `/tmp/zoop-real-authority-inspect-before-review.json`의 비활성 기존 정책 후보·trace; `/tmp/zoop-real-run-{1,2,3}.json`]
- **변경한 판정만:** 새 설정 `/tmp/zoop-real-relaxed-settings.json`은 `policy_version=zoop-real-relaxed-no-web-1`, `support_min=0.65`, `contradiction_max=0.10`, `reject_min=0.90`으로 하며 필수 독립 웹 검증(`--web-verify`)은 이 시연에서 제외한다. 원문 인용 위치 검사, 출처의 `allow_store_body`·`allow_model_send` 및 본문 필수 조건은 손대지 않았다. 18건 모두 이전 적격 전체 본문 입력이며 신규 RSS나 권한 불명 자료는 추가하지 않는다. 웹 교차 검증 제거로 오승인 위험이 커진다. 기존 웹 검증 승인과 혼동되지 않도록 별도 해시 정책을 `activate-policy --expected-version real-news-web-approval-1:b43cfd24b4165ce2 --live --config /tmp/zoop-real-relaxed-settings.json`으로 활성화했고 실제 버전은 `zoop-real-relaxed-no-web-1:e981aca589fd5113`이다. 이전 정책 후보는 비활성 감사 기록으로 유지된다. [출처: 사본 `src/investmate/storage.py:135-170`, `pipeline.py:422-470`, `cli.py:89-106`; `/tmp/zoop-real-policy-activation.json`]
- **과거 응답 비교와 게시의 차이:** `poc review-export --snapshot <변경 전 inspect> --review-file /tmp/zoop-real-policy-review.json --judgments-file /tmp/zoop-real-policy-judgments.json` 후 `poc review-compare --review /tmp/zoop-real-policy-review.json --profiles /tmp/zoop-real-policy-profiles.json --output /tmp/zoop-real-policy-compare.json`은 외부 모델 호출 **0회**, 저장 질문 1,176개의 고정 응답에서 엄격 ALLOW 질문 611/1,176·대상 11/237, 완화 ALLOW 질문 983/1,176·대상 129/237을 산출했다. **이는 게시 시뮬레이션이나 정확도 검증이 아니다:** 사람 확정 라벨 0건, 질문 구성·기업 참조와 웹 검증 여부가 바뀌며, 서버는 새 정책의 후보/trace/출처 경계를 확인하므로 옛 응답을 새 승인으로 위조하거나 재사용하지 않았다. 새 정책 게시에는 실제 새 Jev 검증이 필요하다. [출처: `/tmp/zoop-real-policy-compare.json`; 사본 `src/investmate/decision_review.py:1-27`, `storage.py:454-525`, `jev.py:629-779`]
- **카탈로그 출처:** 기존 3개에 처리 기사 원문에 등장하는 상장기업 Intel·Google(Alphabet 티커에 대응하는 자회사)·Amazon·Microsoft·Meta·Apple·Pinterest·Dell·Fujitsu·Oracle·HPE를 더해 14개로 구성했다. 예컨대 NVIDIA의 AI 인프라 행사 기사에 Pinterest·Amazon Annapurna Labs, 에너지 연합 기사에 Google, SK하이닉스 입장문에 Intel이 직접 등장한다. 기업 등록은 사건 참여·공급 관계의 증거가 아니며, 별도 `basis_edges`는 0개다. SVG 9개는 Simple Icons npm 패키지의 원본을 그대로 복사하고 해당 패키지의 `hex`·출처로 색을 등록했다. Amazon의 `#FF9900`은 [공식 브랜드 가이드 11쪽](https://pages.awscloud.com/rs/112-TZM-766/images/Amazon%20Global_Brand%20Guidelines_DF_v3.pdf)에서 확인했다. 확인된 색·사용 가능한 원본 아이콘이 없는 기업에는 임의 이미지를 만들지 않았다. [출처: `runtime/web-approval-live/eligible-articles.jsonl` 해당 기사; `/tmp/si/package/data/simple-icons.json`, `/tmp/si/package/LICENSE.md`; `prototype/web/public/logos/LICENSE.md`]

### 9.2 실행·비용·전후 결과

- **명령과 종료 상태:** 사본 루트에서 `DATABASE_URL=<전용 실뉴스 DB> REDIS_URL='' PYTHONDONTWRITEBYTECODE=1 uv run --offline --no-sync --env-file .env poc run --live --config /tmp/zoop-real-relaxed-settings.json --dataset runtime/web-approval-live/eligible-articles.jsonl --output /tmp/zoop-real-relaxed-run-1.json`을 실행했다. 동일 명령에 `--retry-model-errors --output /tmp/zoop-real-relaxed-run-2.json`을 더해 중단점에서 재개했다. **두 실행 모두 종료 코드 1**이었다. `max_calls=200`을 각각 적용해 누적 상한에 닿자 추가 모델 호출을 멈췄다. 두 보고서는 첫 회 `processed=43, approved=15, held=28, pending=10, errors=2`, 둘째 회 `processed=41, skipped=43, approved=17, held=24, pending=4, errors=3`이었다. `pending=4`는 마지막 실행의 **남은 언급 작업 추정치**이지 이전 8절에서 보고한 네 작업과 동일하다는 뜻이 아니다. 마지막 추출 오류 3건은 규제 본문 인용 위치 불일치 1건과 요청 읽기 시간 초과 2건(삼성전자 기후산업국제박람회 기사 및 아랍에미리트 수출 규정)이다. 원문 인용 불일치를 허용하도록 바꾸지 않았다. [출처: `/tmp/zoop-real-relaxed-run-{1,2}.json`; 사본 `src/investmate/pipeline.py:832-1072`]
- **모델 사용량:** 첫 회 `calls=200`, 입력 1,313,162·출력 297,822토큰; 둘째 회 `calls=200`, 입력 1,401,246·출력 210,306토큰. **총 400회, 입력 2,714,408·출력 508,128토큰**, 두 회 경과 4,014.63초다. 두 회 모두 `web_usage.source_requests=0`, `estimated_cost=null`이다. 이전 엄격 정책의 600회와 **별도 작업 비용**이며 금액 청구액은 확인되지 않았다. 추가 재시도는 사용자의 400회 상한을 넘기므로 수행하지 않았다. [출처: `/tmp/zoop-real-relaxed-run-{1,2}.json`]

| 범위 | 이슈 | 게시 `REPORTS` | `INVOLVES` | `PROVIDES_BACKGROUND` | `FOLLOWS` | 직접 연결 기업 | 카탈로그 |
|---|---:|---:|---:|---:|---:|---:|---:|
| 기존 엄격 정책 원장 | 1 | 0 | 0 | 0 | 0 | 0 | 3 |
| 완화 정책 **원장·Neo4j 진단 투영** | 31 | 31 | 17 | 1 | 1 | 3 | 14 |
| 수동 검수 후 **공개 스냅샷** | 31 | 31 | 17 | 1 | **0** | 3 | 14 |

- **스냅샷 경계:** `poc inspect --with-evidence --output prototype/bff/fixtures/poc-real-inspect.json`을 새 정책 DB에 대해 실행해 이슈 31·승인 관계 50·후보 149(현재 활성 84: `ALLOW=32, HOLD=52`; 기존 비활성 65)·오류 배열 0을 관측했다. 승인 간선과 후보 승인 건수는 다른 단위다. 총 18개 저장 기사 중 최종 승인 이슈에는 11개 기사가 연결된다. 수동 점검 후 공개 fixture의 **이슈 승인 뷰에서만** 잘못 승인된 `relation-021ae4e61e1b08cd14affc58` 한 건을 제외하고 최상위 `review_exclusions`에 관계·후보 ID, 기존 원장 `ALLOW`, 제외 사유, 정책 버전을 남겼다. 보류/승인 후보의 원본 감사 데이터와 다른 간선 49개·근거는 그대로다. 공개 fixture는 따라서 **원장 `inspect`의 무가공 사본이 아니다**. `poc inspect --issue issue-48bcf76304253fea001492e3 --with-evidence --graph`에서 원장과 Neo4j 투영은 서로 같은 세 간선(`REPORTS` 2·`FOLLOWS` 1)을 보고했고 오류가 없었다. 라이브 DB를 직접 노출하면 제외 간선이 다시 보이므로 공개 시연 기본값은 검수 스냅샷으로 사용해야 한다. PoC에는 이미 승인된 단일 간선만 모델 호출 없이 철회하는 CLI·저장소 API가 없다; `reassign`은 새 검증을 수행하고 기사 철회·정책 전환은 후보 전체를 무효화한다. 출처 또는 검증 기록을 DB에서 직접 고쳐 원장 권위를 우회하지 않았다. [출처: 최종 fixture `review_exclusions`, `/tmp/zoop-real-authority-inspect-before-review.json`, `/tmp/zoop-real-authority-issue-projection.json`; 사본 `src/investmate/storage.py:135-170,454-572,618-683`, `pipeline.py:1107-1217`]

### 9.3 수동 점검 3건과 잔여 위험

1. **삼성전자 행사 주최 — 적합:** `issue-c24ac9a7d789a5f8db4c9361`의 `INVOLVES → KRX:005930` 역할 `host`. [삼성전자 원문](https://news.samsung.com/kr/%ec%82%bc%ec%84%b1%ec%a0%84%ec%9e%90-%ea%b0%80%ec%a0%84-%ed%85%8c%ed%81%ac%ec%84%b8%eb%af%b8%eb%82%98-%ea%b0%9c%ec%b5%9c%ec%a7%80%ec%97%ad-%eb%a7%9e%ec%b6%a4%ed%98%95-ai-%ea%b0%80%ec%a0%84)의 “삼성전자가 16일 인도 구루그람에서 가전 테크세미나 … 열고” 문구가 주최·개최를 직접 지지하고 저장된 인용 위치도 일치한다.
2. **Pinterest–NVIDIA 공동 연결 — 적합(역할 해석 주의):** `issue-6ccb6aba0ddd26896842832e`의 `INVOLVES → NYSE:PINS`(`adopter`)와 `INVOLVES → NASDAQ:NVDA`(`technology provider`). [NVIDIA 원문](https://blogs.nvidia.com/blog/ai-infra-summit-vera-rubin-dsx-energy-efficiencies-tokens-per-watt-ai-factories/)은 “Pinterest is using the NVIDIA Blackwell platform and NVIDIA Dynamo inference software …”라고 명시한다. 제품 사용 기업과 제품 제공 기업이라는 **직접 설명 가능한 연결**이며 제품 사용이 지분·공급 계약·주가 영향을 뜻하지는 않는다.
3. **One UI 해외 확대 `FOLLOWS` — 오승인, 공개 제외:** `issue-48bcf76304253fea001492e3 → issue-f571b945ddcd229404238448`의 원문은 “[국내 업데이트] 시작해 글로벌 시장으로 순차 확대한다”와 “지원 기기를 차례로 넓혀갈 계획이다”라고 한다. 같은 기사에서 향후 계획을 언급한 것으로 **별도의 이미 발생한 후속 사건**은 확인되지 않는다. 저장 인용은 정확히 일치하더라도 의미 승인은 별개다. 원장·투영에는 `ALLOW` 기록을 감사용으로 남기고 공개 스냅샷에서 해당 간선만 제외했다. [출처: [삼성전자 원문](https://news.samsung.com/kr/%ec%82%bc%ec%84%b1%ec%a0%84%ec%9e%90-one-ui-9-%ea%b3%b5%ec%8b%9d-%eb%b2%84%ec%a0%84-%ec%97%85%eb%8d%b0%ec%9d%b4%ed%8a%b8-%ec%8b%9c%ec%9e%91); 최종 fixture `review_exclusions`; 원장 조회 파일]

**한계:** 웹 독립 교차 확인을 끄고 문턱을 낮춰 오승인 가능성이 상승했다. 동일 보도자료의 상품 시연 문장들이 여러 개의 개별 승인 이슈로 분할되는 사례가 있으므로 이슈 31개를 독립 뉴스 31건·기업의 실적 영향으로 해석하지 않는다. 선택 필드는 계속 독립 판정되며, 관계 근거·본문 이용 허가·최신 원문 일치는 계속 요구된다. 문서의 세 건은 사람 정답셋이나 전체 정확도 측정이 아니다. 미완료 `pending=4`와 추출 오류 3건은 사용자가 추가 모델 예산을 허용하기 전에는 재시도하지 않는다.


## 10. 데이터 확장: 실제 기사 추가 수집과 새 원장

시연 피드백 “기업과 이슈가 적어 핵심 기능이 잘 안 보인다”에 대응해 공식 출처의 실제 기사를 더 모으고, PoC 판정을 샌드박스에서 **실제로 실행**했다. 합성 기사는 쓰지 않았다. 총 유료 모델 호출은 사용자 승인 상한 2,000회 안이다(아래 10.5).

### 10.1 원장 결정: 새 DB `investmate_zoop_real2`

- **무엇이 바뀌나:** 카탈로그를 늘리면 `Settings.policy_for()`의 입력(`companies`)이 바뀌어 정책 해시가 `zoop-real-relaxed-no-web-1:e981aca589fd5113` → `zoop-real-expanded-no-web-1:36ec6aced1831382`로 달라진다. 추출 캐시 키(`prompts.extraction_cache_key`)도 카탈로그를 포함하므로 기존 기사의 추출·검증이 모두 새 키가 된다. [출처: 샌드박스 `src/investmate/domain.py:443-454`, `prompts.py:155-165`]
- **기존 DB에 `activate-policy`를 하면(무료 명령으로 확인):** 기존 DB를 `pg_dump`로 임시 DB에 복사해 같은 명령(`poc activate-policy --expected-version zoop-real-relaxed-no-web-1:e981aca589fd5113 --live --config zoop-real-expanded-settings.json`)을 실행했다(모델 호출 0회). 활성 후보 `ALLOW 32 + HOLD 52`가 전부 `active=false`(`policy changed`)가 되어 사용자 이슈가 0건이 되고, 투영 취소 작업 178건이 outbox에 쌓였다. 코드 근거는 `storage.py:156-170`. 복사본은 확인 직후 삭제했고 원본은 전과 같다(`ALLOW t 32 / HOLD t 52`). 되돌리려면 같은 정책으로 400회 재처리가 필요하므로 **기존 DB는 그대로 두고 새 DB에서 기존 기사 18건과 신규 기사를 함께 처리**했다.
- **격리:** Neo4j 투영은 `issue_id`(기사·버전·언급 ID 해시)가 같으면 덮어쓰므로, 새 원장 전용 컨테이너 `zoop-poc-neo4j-real2`(127.0.0.1:58474/58687, 볼륨 `zoop-poc_neo4j-real2-data`)를 `docker run`으로 따로 띄웠다. 기존 `zoop-poc-*` 컨테이너는 건드리지 않았다. 정책 값은 완화 정책 그대로(support 0.65, contradiction 0.10, reject 0.90, 웹 검증 없음).

```bash
docker volume create zoop-poc_neo4j-real2-data
docker run -d --name zoop-poc-neo4j-real2 --restart unless-stopped -p 127.0.0.1:58474:7474 -p 127.0.0.1:58687:7687 \
  -e NEO4J_AUTH=neo4j/investmate-local-only -v zoop-poc_neo4j-real2-data:/data neo4j:5.26-community
docker exec zoop-poc-postgres-1 psql -U investmate -d postgres -c "CREATE DATABASE investmate_zoop_real2"
# 샌드박스 zoop-expansion/real2.sh 는 DATABASE_URL/NEO4J_URI 만 새 원장으로 바꿔 .env의 모델 키를 쓴다
zoop-expansion/real2.sh .venv/bin/poc init-db
zoop-expansion/real2.sh .venv/bin/poc activate-policy --expected-version - --live --config zoop-real-expanded-settings.json
```

### 10.2 출처와 권한

모든 본문은 PoC `SourceTools`(`read_document`)로 읽었다. 이 경로가 robots.txt, 호스트 허용 목록, 출처별 `allow_read_body`·`allow_model_send` 부여를 강제하며, `body_scope=full`인 문서만 썼다(부분 본문 제외). 출처 부여 설정은 샌드박스 `zoop-expansion/sources.json`이다.

| 출처 | 호스트 | 구분 | 근거 | 사용 |
|---|---|---|---|---|
| NVIDIA 블로그·뉴스룸 | blogs.nvidia.com, nvidianews.nvidia.com | 기존 부여(§8) | robots.txt 허용으로 읽기 성공. **약관(www.nvidia.com Terms of Service, “Single Copy License”)은 로봇·스크레이퍼 접근과 복제를 금지**한다. 기존 18건과 같은 성격이라는 운영자 승인 아래 같은 부여를 이어 썼다 | 사용 |
| 삼성전자 뉴스룸(국문·영문) | news.samsung.com | 기존 부여 | `robots.txt`: `Allow: /`. 영문 피드는 같은 호스트의 새 피드 URL | 사용 |
| SK하이닉스 뉴스룸 | news.skhynix.com | 기존 부여 | robots 허용. **약관(Terms of Use)은 로봇 접근·복제를 금지**한다. 기존 부여를 이어 쓰되 1건만 | 사용(1건) |
| OpenDART | opendart.fss.or.kr API | 기존 부여 | Open DART 이용약관: 저작권은 금융감독원, 저작권 관련은 저작권법·공공데이터법을 따른다. 본문은 API `document.xml`로 받았다(뷰어 `dart.fss.or.kr/dsaf001/main.do`는 robots가 금지하므로 쓰지 않았고 URL은 표기용) | 사용(5건) |
| AMD IR, Arm 뉴스룸, Microsoft News Center, LG에너지솔루션, SK텔레콤, Meta, Google, HPE | 각 사이트 | **새 후보** | AMD “personal and/or informational purposes only”, Arm “복제·복사 금지(1부 참고용 출력만)”, Microsoft “non-commercial … will not be copied or posted on any network computer”, LGES “personal, non-commercial use, one copy”처럼 저장·외부 전송을 허용하지 않거나 불분명(HPE는 접속 시간 초과, 나머지는 약관 미확인) | **쓰지 않음**(수집한 사본도 삭제) |

한계: 위 “기존 부여” 출처의 약관에도 복제·자동 수집 금지 문구가 있다. 이번 확장은 사용자가 승인한 “기존 18건과 같은 성격”의 범위에서만 했고, 팀 외부 배포나 상업 이용 전에는 출처별 허락을 다시 확인해야 한다.

### 10.3 수집 절차와 선정 기준

- 도구: 샌드박스 `zoop-expansion/acquire.py`(SourceTools 호출만), `build_datasets.py`(선정·배치 파일·수집 목록·카탈로그 생성). `src/`는 원본과 `diff -qr` 동일(10.8).
- 피드: NVIDIA 블로그 피드 1~9쪽, 삼성 뉴스룸 국문 1~10쪽·영문 1~5쪽, SK하이닉스 영문 1~3쪽, OpenDART 공시 검색(2026-06-01~10-01, 한국 상장사 18개).
- 선정(모델 호출 없는 문자열 일치): `body_scope=full`, 기존 18건 제외, 제목·본문에 후보 상장사 2곳 이상 등장(공시는 직접 고른 5건), 제품 출시·게임 소식 제외, 길이 1,000~16,000자. 비용이 큰 파트너 나열형 기사(25개 사 동시 등장 등)는 예비 배치로 돌려 이번 실행에서는 처리하지 않았다. 처리하지 않은 예비 18건은 아래 목록에서 제외했다.
- 기간: 보도 시각 2026-05-18 ~ 2026-10-01(약 136일). 기존 18건은 2026-09-14~17(+연방관보 2건).

처리 대상 신규 기사 35건(제목·게시자·보도 시각 UTC·URL, 권한 근거는 10.2의 출처 행):

| # | 배치 | 게시자 | 보도일 | 제목 | URL |
|---|---|---|---|---|---|
| 1 | batch-01 | NVIDIA official blog | 2026-05-18 | NVIDIA CEO Jensen Huang at Dell Technologies World: ‘Demand Is Going P | https://blogs.nvidia.com/blog/dell-technologies-agent-enterprise-ai/ |
| 2 | batch-01 | NVIDIA official blog | 2026-05-19 | NVIDIA and Google Cloud Empower the Next Wave of AI Builders | https://blogs.nvidia.com/blog/google-cloud-developer-community-ai-builders/ |
| 3 | batch-01 | NVIDIA official blog | 2026-06-01 | Taiwan’s Industry Titans Turbocharge World’s AI Infrastructure Buildou | https://blogs.nvidia.com/blog/taiwan-ecosystem-ai-infrastructure/ |
| 4 | batch-01 | NVIDIA official blog | 2026-06-01 | NVIDIA AI Cloud Ecosystem Expands Worldwide to Meet Global AI Compute  | https://blogs.nvidia.com/blog/ai-cloud-ecosystem/ |
| 5 | batch-01 | NVIDIA official blog | 2026-06-02 | NVIDIA Partners With Microsoft on Unified Stack for Agentic AI Deploym | https://blogs.nvidia.com/blog/microsoft-build-windows-local-cloud-devices/ |
| 6 | batch-01 | NVIDIA official blog | 2026-06-02 | Industrial Software Leaders Build Secure, Autonomous AI Engineers With | https://blogs.nvidia.com/blog/industrial-software-leaders-secure-autonomous-ai-engineers-nemoclaw/ |
| 7 | batch-01 | NVIDIA official blog | 2026-06-05 | Seoul Purpose: How NVIDIA and South Korea Are Building the Future of A | https://blogs.nvidia.com/blog/korea-ecosystem-2026/ |
| 8 | batch-01 | NVIDIA official blog | 2026-06-08 | NVIDIA and LG Group Build an AI Factory to Advance Physical AI, Mobili | https://blogs.nvidia.com/blog/nvidia-and-lg-group-ai-factory/ |
| 9 | batch-01 | NVIDIA official blog | 2026-06-09 | NVIDIA Confidential Computing to Help Expand Apple’s Private Cloud Com | https://blogs.nvidia.com/blog/nvidia-confidential-computing-apple-private-cloud-compute/ |
| 10 | batch-01 | NVIDIA official blog | 2026-06-16 | Fastest, Largest, Strongest: NVIDIA Blackwell Sweeps MLPerf Training 6 | https://blogs.nvidia.com/blog/blackwell-mlperf-training-6-0/ |
| 11 | batch-01 | NVIDIA official blog | 2026-06-23 | NVIDIA Brings Trusted, 24/7 AI Agents to Telecom Operations | https://blogs.nvidia.com/blog/telecom-ai-agents-dtw-ignite-2026/ |
| 12 | batch-01 | NVIDIA official blog | 2026-06-24 | NVIDIA and AWS Collaborate to Bring AI to Production at Scale | https://blogs.nvidia.com/blog/nvidia-aws-ai-production-scale/ |
| 13 | batch-02 | NVIDIA official blog | 2026-06-29 | Open Models, Closed Environments: Palantir Brings Secure AI to US Agen | https://blogs.nvidia.com/blog/palantir-secure-ai-us-agencies-nemotron-open-models/ |
| 14 | batch-02 | Samsung Electronics Newsroom | 2026-06-29 | 삼성, 협력회사와 상생 생태계 조성을 위한 협약 체결 | https://news.samsung.com/kr/%ec%82%bc%ec%84%b1-%ed%98%91%eb%a0%a5%ed%9a%8c%ec%82%ac%ec%99%80-%ec%83%81%ec%83%9d-%ec%83%9d%ed%83%9c%ea%b3%84-%ec%a1%b0%ec%84%b1%ec%9d%84-%ec%9c%84%ed%95%9c-%ed%98%91%ec%95%bd-%ec%b2%b4%ea%b2%b0 |
| 15 | batch-02 | Samsung Electronics Newsroom | 2026-06-29 | 삼성, 미래 성장 위해 2,655조원 투자 | https://news.samsung.com/kr/%ec%82%bc%ec%84%b1-%eb%af%b8%eb%9e%98-%ec%84%b1%ec%9e%a5-%ec%9c%84%ed%95%b4-2655%ec%a1%b0%ec%9b%90-%ed%88%ac%ec%9e%90 |
| 16 | batch-02 | NVIDIA official blog | 2026-06-29 | Claude Meets Blackwell Ultra: Anthropic’s Models Now Run on NVIDIA GB3 | https://blogs.nvidia.com/blog/anthropic-nvidia-gb300-blackwell-ultra-microsoft-azure/ |
| 17 | batch-02 | Samsung Electronics Newsroom | 2026-06-30 | 삼성, 미래 성장 위해 호남에 425조원 투자 | https://news.samsung.com/kr/%ec%82%bc%ec%84%b1-%eb%af%b8%eb%9e%98-%ec%84%b1%ec%9e%a5-%ec%9c%84%ed%95%b4-%ed%98%b8%eb%82%a8%ec%97%90-425%ec%a1%b0%ec%9b%90-%ed%88%ac%ec%9e%90 |
| 18 | batch-02 | Samsung Electronics Newsroom | 2026-07-02 | 삼성, 미래 성장 위해 충청에 140조원 투자 계획 | https://news.samsung.com/kr/%ec%82%bc%ec%84%b1-%eb%af%b8%eb%9e%98-%ec%84%b1%ec%9e%a5-%ec%9c%84%ed%95%b4-%ec%b6%a9%ec%b2%ad%ec%97%90-140%ec%a1%b0%ec%9b%90-%ed%88%ac%ec%9e%90-%ea%b3%84%ed%9a%8d |
| 19 | batch-02 | Samsung Electronics Newsroom | 2026-07-03 | 삼성, 미래 성장 위해 영남에 60조원 투자 계획 | https://news.samsung.com/kr/%ec%82%bc%ec%84%b1-%eb%af%b8%eb%9e%98-%ec%84%b1%ec%9e%a5-%ec%9c%84%ed%95%b4-%ec%98%81%eb%82%a8%ec%97%90-60%ec%a1%b0%ec%9b%90-%ed%88%ac%ec%9e%90-%ea%b3%84%ed%9a%8d |
| 20 | batch-02 | NVIDIA official blog | 2026-07-21 | Built for Vera Rubin, NVIDIA Spectrum-6 Arrives in Gigascale AI Factor | https://blogs.nvidia.com/blog/nvidia-spectrum-six-arrives-in-gigascale-ai-factories/ |
| 21 | batch-02 | Samsung Electronics Newsroom | 2026-07-22 | 삼성전자, ‘갤럭시 워치 울트라2·워치9’ 공개 | https://news.samsung.com/kr/%ec%82%bc%ec%84%b1%ec%a0%84%ec%9e%90-%ea%b0%a4%eb%9f%ad%ec%8b%9c-%ec%9b%8c%ec%b9%98-%ec%9a%b8%ed%8a%b8%eb%9d%bc2%c2%b7%ec%9b%8c%ec%b9%989-%ea%b3%b5%ea%b0%9c |
| 22 | batch-02 | OpenDART | 2026-07-23 | [기재정정]타법인주식및출자증권취득결정 | https://dart.fss.or.kr/dsaf001/main.do?rcpNo=20260723801025 |
| 23 | batch-02 | NVIDIA official blog | 2026-07-24 | At AI Summit, South Korea Outlines Its AI Future With NVIDIA and Partn | https://blogs.nvidia.com/blog/ai-summit-korea-partners-and-nvidia/ |
| 24 | batch-02 | Samsung Electronics Newsroom | 2026-07-27 | 삼성전자, ‘갤럭시 Z 폴드8 울트라·폴드8·플립8’, ‘갤럭시 워치 울트라2·워치9’ 사전 판매 시작 | https://news.samsung.com/kr/%ec%82%bc%ec%84%b1%ec%a0%84%ec%9e%90-%ea%b0%a4%eb%9f%ad%ec%8b%9c-z-%ed%8f%b4%eb%93%9c8-%ec%9a%b8%ed%8a%b8%eb%9d%bc%c2%b7%ed%8f%b4%eb%93%9c8%c2%b7%ed%94%8c%eb%a6%bd8-%ea%b0%a4%eb%9f%ad%ec%8b%9c |
| 25 | batch-03 | NVIDIA official blog | 2026-08-04 | As AI Increases Demands on Memory, Storage Steps Up | https://blogs.nvidia.com/blog/ai-storage-fms/ |
| 26 | batch-03 | OpenDART | 2026-08-07 | 타법인주식및출자증권처분결정 | https://dart.fss.or.kr/dsaf001/main.do?rcpNo=20260807800838 |
| 27 | batch-03 | OpenDART | 2026-08-11 | 투자판단관련주요경영사항 | https://dart.fss.or.kr/dsaf001/main.do?rcpNo=20260811800246 |
| 28 | batch-03 | OpenDART | 2026-08-14 | 동일인등출자계열회사와의상품ㆍ용역거래변경 | https://dart.fss.or.kr/dsaf001/main.do?rcpNo=20260814003055 |
| 29 | batch-03 | Samsung Electronics Newsroom | 2026-09-01 | 삼성전자, ‘New 갤럭시 북6’ 국내 출시 | https://news.samsung.com/kr/%ec%82%bc%ec%84%b1%ec%a0%84%ec%9e%90-new-%ea%b0%a4%eb%9f%ad%ec%8b%9c-%eb%b6%816-%ea%b5%ad%eb%82%b4-%ec%b6%9c%ec%8b%9c |
| 30 | batch-03 | Samsung Electronics Newsroom | 2026-09-08 | 삼성전자, ASML과 차세대 반도체 제조 협력 확대 | https://news.samsung.com/kr/%ec%82%bc%ec%84%b1%ec%a0%84%ec%9e%90-asml%ea%b3%bc-%ec%b0%a8%ec%84%b8%eb%8c%80-%eb%b0%98%eb%8f%84%ec%b2%b4-%ec%a0%9c%ec%a1%b0-%ed%98%91%eb%a0%a5-%ed%99%95%eb%8c%80 |
| 31 | batch-03 | Samsung Electronics Newsroom | 2026-09-23 | Samsung at the Forefront of Korea’s AI RAN Projects with KT and SK Tel | https://news.samsung.com/global/samsung-at-the-forefront-of-koreas-ai-ran-projects-with-kt-and-sk-telecom |
| 32 | batch-03 | Samsung Electronics Newsroom | 2026-09-28 | Samsung, SK Telecom, and Hana Financial Group Build Korea’s First Priv | https://news.samsung.com/global/samsung-sk-telecom-and-hana-financial-group-buildkoreas-first-private-5g-smart-office-in-the-financial-sector |
| 33 | batch-03 | Samsung Electronics Newsroom | 2026-09-29 | 삼성 6개사, 美 AI 인프라 기업 ‘헬릭스’에 10억 달러 투자 | https://news.samsung.com/kr/%ec%82%bc%ec%84%b1-6%ea%b0%9c%ec%82%ac-%e7%be%8e-ai-%ec%9d%b8%ed%94%84%eb%9d%bc-%ea%b8%b0%ec%97%85-%ed%97%ac%eb%a6%ad%ec%8a%a4%ec%97%90-10%ec%96%b5-%eb%8b%ac%eb%9f%ac-%ed%88%ac%ec%9e%90 |
| 34 | batch-03 | OpenDART | 2026-10-01 | [기재정정]단일판매ㆍ공급계약체결 | https://dart.fss.or.kr/dsaf001/main.do?rcpNo=20261001800119 |
| 35 | batch-03 | SK hynix Newsroom | 2026-10-01 | Clarification Regarding Recent Media Reports on Solidigm | https://news.skhynix.com/en/fact-11/ |

### 10.4 카탈로그와 로고

- `fixtures/poc-real-companies.json`: 14 → 58개. 처리 기사 본문(기존 18건 포함)에 실제로 이름이 나온 상장사만 넣었다(문자열 일치 + 사람이 문맥 확인; 파트너 나열 속 1회 등장도 포함). id는 `KRX:005930`·`NASDAQ:NVDA`·`NYSE:GM`·`TSE:6702` 형식(시세 매핑 규칙과 동일). 기업 등록은 사건 참여·공급 관계의 증거가 아니며 `basis_edges`는 0개다.
- 로고 18개 추가(Simple Icons 16.33.0, CC0 도형 데이터, 수정 없이 복사). 패키지에 없는 기업(SK하이닉스·Amazon·Microsoft·Micron·TSMC 등)은 모노그램을 그대로 쓴다. 목록·조건은 `web/public/logos/LICENSE.md`.

### 10.5 실행 기록과 총 사용량

실행은 모두 관리자 작업 러너의 새 작업 종류 `ingest-run`(“신규 기사 처리”: `poc run --live --config <작업별 settings> --dataset zoop-expansion/datasets/<파일>`)과 기존 `retry-model-errors`로 했고 BFF 포트 8823의 AI 사용량 화면에 기록됐다. 작업마다 `max_calls`를 걸었다. 샌드박스 `zoop-real-expanded-settings.json`의 `max_articles=20`, `max_retries=0`.

| 작업 | 종류 | 입력 | 상한 | 처리 | 승인 | 보류 | 반려 | 대기 | 오류 | 호출 | 입력 토큰 | 출력 토큰 | 경과(초) |
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|
| job-0009 | retry-model-errors | (원장의 기사 전체) | 250 | 54 | 10 | 44 | 0 | 18 | 6 | 250 | 1,746,260 | 281,012 | 1655 |
| job-0008 | ingest-run | batch-03.jsonl | 260 | 51 | 19 | 32 | 0 | 3 | 15 | 260 | 1,893,430 | 369,246 | 2296 |
| job-0007 | ingest-run | batch-02.jsonl | 250 | 53 | 19 | 34 | 0 | 17 | 7 | 250 | 1,877,302 | 447,352 | 2900 |
| job-0006 | ingest-run | batch-02.jsonl | 260 | 59 | 4 | 55 | 0 | 9 | 8 | 260 | 1,821,396 | 309,218 | 1907 |
| job-0005 | ingest-run | batch-01.jsonl | 200 | 41 | 5 | 36 | 0 | 2 | 9 | 200 | 1,217,498 | 240,059 | 1692 |
| job-0004 | ingest-run | batch-01.jsonl | 260 | 56 | 3 | 53 | 0 | 16 | 1 | 260 | 1,950,299 | 289,947 | 1553 |
| job-0003 | retry-model-errors | (원장의 기사 전체) | 90 | 13 | 6 | 6 | 1 | 0 | 2 | 61 | 405,886 | 83,316 | 581 |
| job-0002 | ingest-run | batch-00-initial-18.jsonl | 170 | 34 | 14 | 20 | 0 | 6 | 2 | 170 | 1,081,478 | 225,309 | 1350 |
| job-0001 | ingest-run | batch-00-initial-18.jsonl | 260 | 46 | 22 | 24 | 0 | 11 | 1 | 260 | 1,960,588 | 329,783 | 1845 |

- **총 모델 호출 1,971회**(상한 2,000), 입력 13,954,137·출력 2,575,242토큰. 웹 검색·외부 유료 도구 호출 0회, `estimated_cost`는 PoC가 `null`로 보고해 금액은 제공하지 않는다. 호출 수는 새 원장 `investmate.runs`의 보고서 합계와 같다.
- 배치 00은 기존 18건을 새 정책으로 다시 처리한 비용이다(기존 완화 실행은 400회였다). 추출 실패(`evidence quote not found`, `repeated evidence quote`, 읽기 시간 초과)는 일부만 마지막 재처리에서 복구됐고 남은 오류는 10.7에 적었다.

### 10.6 전후 규모(`/api/graph?mode=all`, 프로세스 내 측정)

| 지표 | 확장 전(기존 fixture) | 확장 후(새 fixture) |
|---|---:|---:|
| 카탈로그 기업 | 14 | 58 |
| 처리 기사 수 | 18 | 18 + 신규 21 = 39(승인 이슈에 연결된 기사 11 → 39) |
| 원장 승인 이슈(규칙 R1 미적용) | 31(공개 30) | 95 |
| 원장 승인 후보 / 전체 후보 | 32 / 149(활성 84) | 95 이슈 / 407 |
| 승인 `INVOLVES`로 연결된 기업 | 3 | 19 |
| 기업 2곳 이상을 잇는 승인 이슈 | 1 | 12 |
| **사용자 그래프(규칙 R1 적용) 사건 노드** | 45 | **138** |
| **연결된 기업 노드** | 7 | **26** |
| 직접 관련 `INVOLVES` 간선 | 34 | 130(R1@1에서는 131, NVIDIA–AWS의 AMZN 관계 제외) |
| 후속 사건 `FOLLOWS` 간선 | 0 | 2(R1@2: PoC 승인 1 + R1 발생 사건 1). R1@1에서는 9였고 그중 7이 계획 사건 |
| 사건 공유 `SHARES_ISSUE`(기업 쌍) | 7 | 38(R1@1에서는 39) |

“확장 전”은 저장소의 이전 `poc-real-inspect.json`+이전 카탈로그를 같은 BFF 코드(규칙 R1 포함)로 읽은 값이고, “확장 후”는 새 fixture+새 카탈로그의 `/api/graph?mode=all&limit=1000`(`truncated:false`)이다. 연결 없는 사건은 지도에 “연결 없는 사건 41”로 묶여 표시된다.

### 10.7 수동 검수

원문 인용과 대조한 표본 33건(후속 사건 FOLLOWS 전수 9건 + 기업 간 연결을 만드는 사건 24건, 원장 ALLOW·규칙 R1 공개분 포함). 판정 기준은 §9.3과 같다(인용이 관계를 직접 지지하는가, 후속 사건이 이미 발생했는가). **거부 8건**은 관리자 거부 기록(사유 포함, 8823 BFF 상태 DB `review_decisions` 1~8)으로 남겼고 스냅샷 `review_exclusions`에 같은 사유로 옮겼다(기존 제외 1건 포함 총 9건. 이후 #20의 AMZN 관계와 R1 공개 DART 후속 관계 1건을 더해 11건). 원장 ALLOW와 후보 감사 기록은 그대로다.

| # | 사건 → 관계 | 인용 요지 | 판정 |
|---|---|---|---|
| 1 | NVIDIA·Apple Private Cloud Compute (`issue-d3e0cac8…`) INVOLVES NVIDIA·Apple | “NVIDIA GPUs … used for confidential inference in Apple’s PCC” | 적합 |
| 2 | Apple Foundation Models (`issue-4ac67ce2…`) NVIDIA·Apple·Google | “server-side inference for Apple Foundation Models, custom-built by Apple and Google” | 적합 |
| 3 | Palantir–NVIDIA Nemotron 폐쇄망 (`issue-79a15e59…`) | “Palantir announcement brings NVIDIA Nemotron open models into air-gapped environments” | 적합 |
| 4 | 삼성전자·삼성SDS 구미 투자 (`issue-7b1d3400…`) | “삼성전자∙삼성SDS, 휴머노이드∙제조AX … 구축 예정” | 적합(계획 사건) |
| 5 | SK Group–NVIDIA 5,000억 달러+ 파트너십 (`issue-a8d0521c…`) | “SK Group and NVIDIA today announced plans for a $500-billion-plus … partnership” | 적합(발표된 계획) |
| 6 | 현대차그룹 피지컬 AI 전략 (`issue-d009f6f5…`) | “Hyundai Motor Group outlined a physical AI strategy anchored by a robot reference platform developed with NVIDIA” | 적합 |
| 7 | NVIDIA DRIVE Hyperion–현대차그룹 (`issue-02cf2206…`) | “integration of NVIDIA DRIVE Hyperion …” | 적합 |
| 8 | 삼성전자–ASML 대형 마스크 컨소시엄 (`issue-ab86647d…`) | “ASML이 주도하는 ‘대형 마스크 컨소시엄’에 참여하고 … 공동 개발” | 적합 |
| 9 | 삼성전자–ASML High NA EUV 협력 (`issue-25ac3f6d…`) | “2028년까지 … High NA EUV 도입을 위한 협력도 강화할 계획” | 적합(계획) |
| 10 | 삼성 AI RAN 계약 KT·SK텔레콤 (`issue-90249aed…`) | “signed contracts with KT and SK Telecom for their AI RAN projects” | 적합 |
| 11 | 삼성–KT 사족보행 용접 로봇 (`issue-4ee47caf…`) | “Samsung will support KT with … NIS” | 적합 |
| 12 | TSMC–NVIDIA CUDA-X (규칙 R1, `issue-403cdd9c…`) | “TSMC is applying NVIDIA CUDA-X libraries” | 적합(역할 비움) |
| 13 | Wistron·NVIDIA·Cadence 번인 시뮬레이션 (R1, `issue-32a894ad…`) | “Wistron is using … NVIDIA Omniverse DSX Blueprint … and Cadence Reality DC Design” | 적합(Wistron은 미등록 비상장 표기) |
| 14 | Palantir–NVIDIA 맞춤 모델 (R1, `issue-311fcc5c…`) | “Palantir will use NVIDIA Nemotron open models to build custom … models” | 적합 |
| 15 | Claude(Microsoft Foundry)–NVIDIA GB300 (R1, `issue-48601196…`) | “Claude models in Microsoft Foundry — hosted on Azure … NVIDIA GB300 … generally available” | 적합 |
| 16 | 삼성 6개사 헬릭스 10억 달러 투자 (R1, `issue-5076a08d…`) | “삼성전자와 삼성물산, 삼성SDS, 삼성SDI, 삼성생명, 삼성화재 등 6개사는 … 헬릭스 … 투자” | 적합(NVIDIA 연결은 같은 기사 언급 범위) |
| 17 | 삼성·SK텔레콤·하나금융 사설 5G (R1, `issue-952cc29d…`) | “In collaboration with SK Telecom and Samsung, Hana Financial Group built …” | 적합 |
| 18 | NVIDIA 스토리지·메모리 Storage-Next (R1, `issue-1f101747…`) | “NVIDIA and storage industry leaders are optimizing memory and storage … Storage-Next” | 적합(Micron 포함 나열) |
| 19 | Spectrum-6 도입 기업 6곳 (R1, `issue-a64478a1…`) | “including CoreWeave, Microsoft, Nebius, OCI, SpaceXAI and Tesla — will be among the first to bring in Spectrum-6” | 적합(도입 예정) |
| 20 | NVIDIA–AWS 벡터 인덱싱 (R1, `issue-99195142…`) | “It uses GPU-accelerated vector indexing, powered by NVIDIA cuVS” | **거부(관계 단위)**: 인용에 Amazon 명시 없음(대명사). `INVOLVES → AMZN`만 스냅샷 `review_exclusions`에 추가했다(R1@2는 관계 단위 제외를 적용해 사건·NVIDIA 연결은 남긴다) |
| 21 | Koa 이미 사용 중 FOLLOWS Koa 발표 | “Koa is already running inside Salesforce, powering an employee agent in Slack” | 유지(주의: 발표와 동시 상태) |
| 22 | One UI 9 해외 확대 FOLLOWS (`relation-c7d7570a…`) | “글로벌 시장으로 순차 확대한다 … 넓혀갈 계획” | **거부**: 계획 서술(기존 제외와 동일 사건 쌍) |
| 23 | 맨체스터 모델 해상도 확대 FOLLOWS 학습 데이터 생성 (`relation-af3900ca…`) | “plans to further increase the resolution” | **거부**: 계획 |
| 24 | 맨체스터 오픈소스 공개 FOLLOWS 학습 데이터 생성 (`relation-a76e7af0…`) | “plans to release open source training data” | **거부**: 계획 |
| 25 | Koa 정식 출시 예정 FOLLOWS Koa 발표 (`relation-ea08d42d…`) | “General availability is expected winter 2026” | **거부**: 예측 |
| 26 | Koa 정식 출시 예정 FOLLOWS Koa 사용 중 (`relation-758b0c3d…`) | 위와 같음 | **거부**: 예측 |
| 27 | 갤럭시 워치 7/28 사전 판매 FOLLOWS 공개 (`relation-8c48d9ce…`) | “7월 28일 … 사전 판매 시작” (예정) | **거부**: 예정 |
| 28 | 삼성SDI–GM 합작 종료 후 단독 운영 FOLLOWS (`relation-76e4169f…`) | “단독법인으로 운영할 계획” | **거부**: 계획 |
| 29 | AI Summit 무대 행사 → Broadcom INVOLVES (`relation-9ebc5d7a…`) | “The sheer gravity of the global AI boom was displayed Friday on stage …” (Broadcom 미언급) | **거부**: 직접 근거 없음 |
| 30 | 규칙 R1 FOLLOWS 6건(Koa 파일럿·갤럭시 워치 출시·KT/SKT 현장 시험·맨체스터 DGX Spark 등) | 대부분 `planned` 사건이 앞 사건의 후속으로 공개됨 | **해결(R1@2)**: 계획 사건 FOLLOWS 7개(Koa 파일럿 2·워치 출시 2·KT·SKT·DART 단독법인 계획)는 모두 부적합이라 R1@2가 발생(`occurred`)이 아닌 사건의 FOLLOWS를 게시하지 않는다. 맨체스터 DGX Spark(발생)는 적합이라 유지. DART 쌍은 `review_exclusions`에도 추가(`docs/evidence/review-policy.md` §6) |
| 31 | 삼성 상업용 에어컨·기후박람회 등 삼성 단독 INVOLVES(기존 18건 재처리분) | 인용이 삼성전자의 행동을 직접 서술 | 적합(기업 간 연결 없음) |
| 32 | SK하이닉스 입장문 INVOLVES (`relation-17e66057…`) | “nothing has been finalized regarding cooperation with any specific companies” | 적합(해명 사건, 협력 확정 아님) |
| 33 | DART SK텔레콤 → SK hynix NAND Product Solutions 출자 | “SK hynix NAND Product Solutions Corp. 지분 확보 추진” | 적합(Solidigm 자회사, 카탈로그 밖 법인) |

관측: 정확도 측정이 아니라 위 표본에 한한 점검이다. 거부 8건은 모두 “계획·예정을 후속 사건으로 승인”한 같은 유형이고, 기업 간 INVOLVES 표본 24건 중 명백한 오승인은 1건(#29)이었다.


### 10.8 재현·검증과 남은 위험

- 관리자 작업 러너 새 종류 `ingest-run`(`admin_jobs.py`, `admin_schemas.py`, `routers/admin_jobs.py`)과 `ZOOP_POC_SETTINGS`(`config.py`)를 추가하고 `tests/test_admin_jobs.py`에 동작 테스트 1개를 더했다. `uv run`과 같은 환경의 `pytest` 190개 통과(`PYTHONDONTWRITEBYTECODE=1 .venv/bin/python -m pytest tests`, 21초). `tests/test_review_exclusions.py`는 실제 스냅샷 변형을 “모든 제외 항목이 공개에서 빠지고 감사에는 남는다”로 일반화했다(기존 id 고정 단언은 합성 fixture에만 둠).
- 새 상태 디렉터리 BFF(8823, `ZOOP_SNAPSHOT_PATH`=새 fixture, `ZOOP_COMPANY_CATALOG`=새 카탈로그)와 웹(5273) 브라우저 스모크: 비회원으로 지도 진입 → 기업 26·사건 138·직접 관련 131·후속 사건 9·사건 공유 39 표시, 기업 상세 삼성전자(사건 27)·NVIDIA(46)·Apple(2)·현대자동차(3) 정상, 콘솔 오류 0. `pnpm typecheck` 통과, `src/api/schema.d.ts` 재생성.
- 샌드박스 `src/`는 원본과 `diff -qr` 차이 없음(원본의 `.DS_Store`만 다름).
- 남은 위험: (1) 이번 완화 정책(웹 검증 없음)의 신규 기사 ALLOW 비율은 낮고(NVIDIA 파트너 나열 기사 다수가 `title`·`role` 검사에서 보류) 기업 간 연결의 상당수는 규칙 R1(역할 비움)이 공개한다. (2) ~~R1이 공개한 계획·예측 `FOLLOWS`~~는 R1@2가 게시하지 않는다(#30). 단 앞 사건(target) 쪽 상태는 보지 않고, 발생 FOLLOWS 표본은 2건뿐이다. (3) 추출 실패(인용 위치 불일치·읽기 시간 초과) 기사 일부는 상한 때문에 복구하지 못했다(마지막 재처리 후 대기 18·오류 6). (4) 예비 18건과 25개 사 나열형 기사는 호출 예산 때문에 처리하지 않았다. (5) NVIDIA·SK하이닉스 약관의 자동 수집·복제 금지 문구(10.2). (6) 카탈로그는 이름 일치로 정했으므로 파트너 나열 속 1회 등장 기업도 있다. (7) 허브(NVIDIA 46·삼성전자 27)로 쏠린다. (8) 기존 제외 1건(`relation-021ae4e6…`)은 새 원장에 없는 id지만 같은 사건 쌍(One UI)을 새 id로 다시 제외했다.
- 운영 메모: 기본 원장·Neo4j·설정이 새 값(`investmate_zoop_real2`·58687·`zoop-real-expanded-settings.json`)으로 바뀌었다. 이전 원장은 `ZOOP_ADMIN_POC_DSN=…/investmate_zoop_real ZOOP_ADMIN_NEO4J_URI=bolt://127.0.0.1:57687 ZOOP_POC_SETTINGS=zoop-real-relaxed-settings.json`으로 열 수 있다. 새 Neo4j 컨테이너가 꺼져 있으면 `docker start zoop-poc-neo4j-real2`.
