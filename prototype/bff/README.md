# 줍(Zoop) 프로토타입 BFF

InvestMate PoC([`Donbug/investmate-poc`](https://github.com/Donbug/investmate-poc), 패키지 `investmate`)의 **승인 이슈**(`PostgresRepository.inspect()` 형태)를 요구사항명세서 v0.2 §8 API 초안 경로로 제공하는 FastAPI 서버다. 배경·가정은 `docs/evidence/README.md`("프로토타입이 채택하는 가정")와 `docs/evidence/poc-backend.md`를 따른다.

- PoC는 **읽기 전용**이다. 비공개 저장소의 고정 커밋을 git 의존성으로 설치한다(`pyproject.toml`의 `[tool.uv.sources]`, 조직 구성원은 `gh auth setup-git` 필요). 이 서버는 PoC DB에 `inspect(None)`과 몇 개의 SELECT만 실행한다. PoC 원장을 바꾸는 일은 BFF가 아니라 관리자 작업이 띄우는 PoC CLI(샌드박스)만 한다.
- **사용자가 보는 그래프 = 활성 게시 버전(불변 스냅샷) + 관리자 검수 기록**이다. 사용자 API는 PoC DB를 직접 읽지 않는다(`ZOOP_SOURCE=live`는 폐지). 관리자가 원장에서 새 버전을 게시해야 사용자 화면이 바뀐다. 관리자 API는 아래 "관리자 API·운영".
- PoC에 없는 데이터(요약·감성·시세)는 지어내지 않고 `{"status":"unavailable","reason":...}`로 응답한다. 인증·계좌·관심종목·브리핑 편성·AI 예시 답변은 BFF mock/규칙이며 응답 `metadata.generatedBy`로 표시한다.
- `HOLD`/`REJECT`는 관리자가 허용하기 전에는 어떤 사용자 응답에도 나오지 않는다(`inspect().issues`만 사용, `candidates`는 모순 검사에만 사용). 관리자가 허용한 HOLD는 사건 상세의 `approval`(`관리자 승인`)로 표시된다.
- 소스 장애는 빈 결과로 위장하지 않고 `503 {"error":{"code":"source_unavailable",...}}`로 응답한다.

## 실행

```bash
cd prototype/bff
uv sync                                                   # PoC 저장소의 고정 커밋을 휠로 설치
uv run uvicorn zoop_bff.main:app --port 8787              # 첫 기동: fixtures/poc-synthetic-inspect.json이 v1로 등록된다
ZOOP_STATE_DIR=/tmp/zoop-state-me uv run uvicorn zoop_bff.main:app --port 8801   # 상태 디렉터리를 따로 쓰는 개발 인스턴스
uv run pytest                                             # 테스트(외부 시스템은 가짜 원장·Neo4j·샌드박스로 대체, DB·모델 호출 없음)
# 300노드 합성 스트레스 스냅샷(그래프 화면 시험용, 아래 "스트레스 스냅샷")
ZOOP_SNAPSHOT_PATH=$PWD/fixtures/synthetic-stress-300.json ZOOP_COMPANY_CATALOG=$PWD/fixtures/synthetic-stress-300.json \
  uv run uvicorn zoop_bff.main:app --port 8787
```

- OpenAPI: `http://127.0.0.1:8787/openapi.json` (Swagger UI `/docs`). 모든 JSON 필드는 camelCase, 응답 모델의 모든 필드는 `required`로 표시된다(값이 없으면 `null`).
- 세션은 **httpOnly 쿠키 `zoop_session`**(SameSite=Lax)이고, 회원·설정·관심종목·가상계좌 연결·튜토리얼 완료·투자 여부와 세션(토큰의 SHA-256만)은 상태 DB(`ZOOP_STATE_DIR/zoop-admin.sqlite3`, `accounts.py`)에 저장돼 **재시작 후에도 유지**된다. 세션 만료: 회원 14일, 비회원 1일(절대 만료).
- 프런트엔드는 Vite proxy(`/api → 127.0.0.1:8787`)로 same-origin 호출을 권장한다. 직접 호출하면 CORS(`credentials`)가 `ZOOP_CORS_ORIGINS` 목록(기본 `localhost`/`127.0.0.1`의 5173·3000·4173)에 한해 열린다. 쿠키는 호스트 단위이므로 `localhost`와 `127.0.0.1`을 섞어 쓰지 않는다.

### 환경변수

| 변수 | 기본값 | 설명 |
|---|---|---|
| `ZOOP_SOURCE` | (없음) | **폐지.** `live`로 두면 기동이 실패한다(사용자 API가 PoC DB를 직접 읽지 않는다) |
| `ZOOP_SNAPSHOT_PATH` | `fixtures/poc-synthetic-inspect.json` | inspect 형태 JSON. **상태 디렉터리가 비어 있을 때 한 번** `v1`(kind `seed`)로 등록된다. 이후 파일을 바꿔도 v1은 그대로이며 `/api/health`의 `warnings`에 차이가 표시된다(새 상태 디렉터리나 관리자 게시를 사용) |
| `ZOOP_STATE_DIR` | `prototype/bff/var/` | 관리자 상태(SQLite `zoop-admin.sqlite3`: 감사 로그·검수 기록·그래프 버전 메타·작업·브리핑 회차·AI 사용 기록)와 버전 파일(`graph/vN.json`, 읽기 전용), 작업 로그(`jobs/`). 인스턴스마다 따로 쓴다 |
| `ZOOP_ADMIN_POC_DSN` | PoC `compose.yaml`의 로컬 전용 접속 `…@127.0.0.1:55432/investmate_zoop_real` | 관리자 원장(실뉴스 DB). 응답·로그에 DSN을 노출하지 않는다 |
| `ZOOP_ADMIN_NEO4J_URI` / `_USER` / `_PASSWORD` | `bolt://127.0.0.1:57687` / `neo4j` / compose 로컬 값 | GraphDB 반영 상태 비교(읽기 전용)와 작업 러너에 주는 접속 |
| `ZOOP_POC_SANDBOX` | `~/.local/share/zoop/investmate-sandbox` | PoC 작업을 실행하는 샌드박스(아래 "샌드박스") |
| `ZOOP_ADMIN_MAX_MODEL_CALLS` | `200` | 유료 작업 한 번의 모델 호출 상한(요청 기본 50, 최소 1). 이 값이 50보다 작으면 기본도 이 값 |
| `ZOOP_ADMIN_IDLE_SECONDS` / `ZOOP_ADMIN_ABSOLUTE_SECONDS` | `1800` / `28800` | 관리자 세션 유휴·절대 만료 |
| `ZOOP_BRIEFING_SCHEDULER` | `true` | BFF 안 스케줄러(07:40·18:10 KST). 테스트는 끈다 |
| `ZOOP_COMPANY_CATALOG` | 소스 체크아웃: 같은 부모 폴더의 `InvestMateLogicTest/examples/synthetic/settings.json`(PoC 저장소를 다른 이름으로 받았다면 이 변수로 지정) | 최상위 `companies` 배열이 있는 JSON(PoC settings.json 형태). 실제 기사 시연은 `fixtures/poc-real-companies.json`. 기업 표시 확장 키(`brand_color`·`logo`·`brand_source`)는 아래 "기업 카탈로그 확장 키". 읽지 못하면 `/api/health`의 `warnings`에 표시하고 계속한다 |
| `ZOOP_CORS_ORIGINS` | 위 목록 | 쉼표 구분. 빈 문자열이면 CORS 미들웨어를 끈다 |
| `ZOOP_COOKIE_SECURE` | `false` | `true`면 쿠키에 `Secure` |

경로 이식성 개선은 `prototype/bff/src` 소스 체크아웃 배치에 한정된다. 패키지 설치에서는 `ZOOP_COMPANY_CATALOG`를 명시한다. 상대 경로 환경변수는 실행 시 작업 디렉터리 기준이다. `pyproject.toml`과 `uv.lock`의 PoC 의존성 절대 경로는 아직 남아 있으며, 설치 이식성은 검증하지 않았다.

### 계정·세션

| 항목 | 값 |
|---|---|
| 데모 계정 | 이메일 `demo@zoop.local`, 비밀번호 `zoop-demo`. 상태 DB에 없으면 기동 때 만든다 |
| 회원가입 | `POST /api/auth/signup {email,password,displayName,agreements:[termId]}` → 201 + 바로 로그인. 비밀번호는 `hashlib.scrypt` 해시로만 저장. 필수 약관은 `GET /api/auth/terms`(제목만, `bodyAvailable:false`) |
| 소셜 로그인 | 개발용 모의 제공자 `mock`만 있다(실제 IdP 자격 증명 없음). 아래 "소셜 로그인" |
| 비회원 | `POST /api/auth/guest` → `kind:"guest"`, `user:null`, `setup:{completed:false, tutorialCompleted}`(튜토리얼 완료는 그 비회원 세션에만 저장). 시장 데이터는 열람 가능, 개인 API는 403 `guest_forbidden`. AI 질문은 비회원도 가능(대화는 만든 세션만 읽을 수 있음) |
| 세션 없음 | `GET /api/auth/session`은 200 `kind:"anonymous"`. 개인 API는 401 |
| 차단 회원 | `members.status='blocked'`이면 로그인 403 `member_blocked`, 열린 세션은 모든 요청이 401 `member_blocked`(로그아웃할 때까지). 차단 해제(`AccountStore.set_status(id,"active")`)는 그 회원의 기존 세션을 모두 지운다 |

새 상태 디렉터리의 데모 계정은 설정 미완료(`completed:false`, `investor:null`), 관심 0개, 계좌 미연결이다. 초기화하려면 새 `ZOOP_STATE_DIR`을 쓴다.

### 소셜 로그인 (요구 4·70)

`GET /api/auth/social/{provider}/authorize?returnTo=/경로` → 302 제공자 동의 화면(`mock`은 웹 `/mock-idp`) + 일회용 `state`(10분, 상태 DB `oauth_states`) + 브라우저 바인딩 쿠키 `zoop_oauth` → 동의(`POST /api/auth/social/mock/idp/consent`가 일회용 code 발급) → `GET /api/auth/social/{provider}/callback?code&state`. callback은 state(존재·미사용·미만료·제공자·쿠키 바인딩)를 확인하고 code를 identity로 바꾼 뒤, 같은 `(provider, subject)` 회원이면 로그인(→ `returnTo`), 처음이면 계정을 만들고 `/onboarding`으로 보낸다. 취소 `error=access_denied` → `/login?social=cancelled`, state·code 실패 → `failed`, 이메일 가입자와 같은 주소 → `email_in_use`(자동 연결하지 않음), 차단 → `blocked`.

**실제 제공자 연동 지점**: `social.py`의 `SocialProvider` 프로토콜(`authorize_url(state, redirect_uri)`, `exchange(code, redirect_uri) -> SocialIdentity`)을 구현하고(토큰 교환 + ID 토큰 서명·aud·nonce 검증) `default_providers()`에 등록한다. `routers/auth.py`의 `mock/idp/consent`는 모의 제공자 전용이다.

## 엔드포인트

명세 v0.2 §8 경로를 그대로 쓴다. 경로 변수는 모두 `{id}`. 에러는 항상 `{"error":{"code","message","details?"}}`.

| Method | 경로 | 비고 |
|---|---|---|
| GET | `/api/health` | 소스 종류·연결 상태·이슈/기업/간선/근거 수. BFF가 살아 있으면 항상 200(`status: ok|degraded|unavailable`) |
| GET | `/api/auth/session` | `{authenticated, kind, user, setup:{completed, tutorialCompleted}}` |
| POST | `/api/auth/login` · `/api/auth/signup` · `/api/auth/guest` · `/api/auth/logout` | login 200 / 422 `login_invalid`(`details.fields`) / 401 `invalid_credentials` / 403 `member_blocked`; signup 201 / 422 `signup_invalid`(`details.fields`·`missingTerms`·`emailTaken`, 모든 항목 한 번에) / 409 `email_taken`(중복만 문제일 때); logout 204 |
| PUT | `/api/auth/tutorial` `{completed}` | 튜토리얼 완료·건너뛰기. 회원은 계정, 비회원은 비회원 세션에 저장. 같은 값 재전송은 변화 없음 |
| GET | `/api/auth/terms` · `/api/auth/social/providers` | 약관 제목 목록 · 소셜 제공자(`development:true`면 모의) |
| GET/PUT | `/api/me/settings` | `{mode, watchlistIds, tutorialCompleted, completed, investor, version}` (아래 규칙) |
| GET | `/api/me/recommendations?limit=` | 관심종목 추천: 활성 그래프의 승인 사건 수가 많은 기업(`reason:"승인된 사건 N건"`), 이미 관심인 기업 제외. 산업·테마 추천은 생산자가 없어 없다 |
| GET | `/api/portfolio/mock-portfolios` | **명세 추가 제안.** 연결 가능한 가상 계좌 `{id,label,holdingsCount}` |
| POST | `/api/portfolio/connections` `{mockPortfolioId}` | 201. 같은 프로필 재전송은 기존 연결 200(중복 연결 없음). 미지 ID 404 `mock_portfolio_not_found`, 다른 프로필이 연결돼 있으면 409 `already_connected` |
| GET | `/api/portfolio` | 보유 종목·수량·평균단가·매입금액·비중·asOf(연결 시각, 상태 DB에 함께 저장). 시세가 없어 `valuation`/`marketValue`는 unavailable, `weightBasis:"cost"`(비중은 **매입금액 기준**) |
| DELETE | `/api/portfolio/connections/{id}` | 204 |
| GET | `/api/graph?mode=all|personal&companyId=&depth=1..6&limit=` | 아래 "그래프". `depth`를 생략하면 중심에서 닿는 연결 요소 전체 |
| GET | `/api/graph/edges/{id}` | 방향·유형·역할·`summary`·assertionStatus·근거 ID·basis·검증 상태. 파생 간선은 `via` 이슈와 직접 관계가 아니라는 설명 |
| GET | `/api/companies?q=&limit=` | **명세 추가 제안.** 관심종목 선택용 검색(id·이름·티커·별칭 부분일치). 항목에 `brandColor`·`logoUrl` |
| GET | `/api/companies/{id}` | `directIssues`(INVOLVES 역방향, `role`), `structuralIssues`(`basis`), `brandColor`·`logoUrl`, `summary`/`price` unavailable, `holding`/`watch`(회원만, 아니면 `null`) |
| GET | `/api/companies/{id}/prices?period=1d|1m|1y` | 항상 unavailable |
| GET | `/api/companies/{id}/documents` | 기업 상세 문서 탭. 이 기업 승인 사건들의 근거 기사를 **중복 없이 최신 발행순**(발행 시각 미상은 뒤)으로. 문서마다 `events[]`(사건 id·제목·`relationType` REPORTS/PROVIDES_BACKGROUND)와 저장한 인용 `quotes[]`(근거 id·인용·`quoteVerified`). `url`이 없으면 `null` 그대로 |
| GET | `/api/events?companyId=&from=&to=` | 사건 목록(최신 사건순). 항목 `reportedAt` = 기사 발행 시각 중 가장 늦은 것(사건 시각으로 쓰지 않음). 아래 "시간" |
| GET | `/api/events/{id}` | mentions·articles·relations·companies·sourceSupport·fieldDecisions·evidenceIds·follows(이전/다음)·`summary` unavailable |
| GET | `/api/evidence/{id}` | `{quote,start,end,articleId,articleVersion,article,quoteVerified,eventIds}` |
| GET | `/api/briefings?date=&edition=morning|evening` | 발행된 출퇴근 브리핑 회차(모두에게 동일). 아래 "브리핑" |
| GET | `/api/briefings/rounds?limit=` | 열 수 있는(발행·제공 중단) 회차 목록 — 날짜·구분 선택용 |
| GET | `/api/briefings/{id}/evaluations` | 항상 unavailable("예측 평가 정책 미정") |
| POST | `/api/chat/sessions` `{contextIds}` | 201. 세션(회원 또는 비회원) 필요 |
| POST | `/api/chat/sessions/{id}/messages` `{question, contextIds?}` | 예시 답변 `bff-example-v0` |

### 설정 규칙 (`PUT /api/me/settings`)

본문 `{version, mode?, watchlistIds?, tutorialCompleted?, completed?, investor?}`. 생략한 필드는 유지하고, 바뀌면 `version`이 1 증가한다. 관심 종목 개수 제한은 없다.

| 상황 | 응답 |
|---|---|
| 요청이 아무것도 바꾸지 않음(같은 요청 재전송) | 200, 저장값 그대로(`version`이 낡아도 409가 아님, 요구 53) |
| `version` ≠ 저장된 값 | 409 `version_conflict` (`details.currentVersion`). 아무것도 바뀌지 않음 |
| 중복 ID | 422 `duplicate_watchlist_id` |
| 카탈로그에 없는 기업 ID | 422 `unknown_company` (`details.companyIds`) |
| `completed:true`, 관심 0개·계좌 미연결 | 200(시장 전체 지도로 시작, 요구 12) |
| 그 외 | 200 |

### 그래프 (`GET /api/graph`)

- 노드 ID는 원본 ID를 그대로 쓴다(기업 `company_id`, 이슈 `issue_id`). 기사는 노드가 아니며 `/api/events/{id}`의 `articles`로 제공한다.
- 간선(`edges[].relationType`): 승인 `INVOLVES`·`STRUCTURALLY_RELATED_TO`(이슈→기업), `FOLLOWS`(source 이슈가 target 이슈의 후속), **파생** `SHARES_ISSUE`(기업↔기업, `derived:true`, `via:[issueId…]`). 파생 간선은 같은 승인 이슈에 함께 연결된 기업 쌍일 뿐 PoC 승인 간선이 아니며 근거 ID가 없다.
- 간선 ID는 `(유형, source, target)`의 안정 해시다. PoC는 같은 관계를 후보별로 여러 `relation_id`로 남기므로 하나의 간선으로 합치고 `relationIds`/`evidenceIds`에 모두 담는다.
- `all`(기본): 공개 전체 그래프. `companyId`가 있으면 그 기업 중심 ego 그래프. `personal`: 회원 세션만(비회원 403 `guest_forbidden`, 세션 없음 401). 보유 종목과 관심 종목을 **함께** 중심으로 둔 ego 그래프이며, 보유가 없으면 관심 종목만으로 만든다. `companyId`는 어느 모드에서든 중심을 그 기업으로 바꾼다. 회원이면 두 모드 모두 기업 노드에 `holding`/`watch`가 따로 표시된다.
- `depth`(1..6, **생략 가능**): 생략하면 중심 기업에서 닿는 **연결 요소 전체**(기업→이슈→기업을 더 이상 새 노드가 없을 때까지, `FOLLOWS`로 이어진 이슈 포함)이고 `metadata.depth`는 `null`이다. 시장 모드(`companyId` 없음)는 `depth`와 무관하게 승인 그래프 전체다. 명시하면 한 단계마다 중심 기업의 이슈, 그 이슈에 연결된 기업을 추가한다(1이면 직접 공동 참여 기업까지). 명시한 `depth`에서 후속(`FOLLOWS`) 이슈는 이미 고른 이슈의 인접 이슈로만 함께 표시한다.
- `limit`(노드 수, 기본 500, 최대 1000): 초과하면 가까운 단계부터, 같은 단계 안에서는 최신 사건 순으로 자르고 `metadata.truncated:true`.
- 개인화인데 보유·관심이 모두 없음: 빈 그래프 + `metadata.emptyReason` = `no_personal_stocks`. 그 밖에 간선이 없으면 `no_approved_issues`(전체) / `no_related_issues`(ego).
- 노드: `{id, kind, label, isFocus, holding, watch, brandColor, logoUrl, eventTime, timePrecision, action, target, evidenceCount}`. `holding`/`watch`는 회원 세션일 때만 true가 될 수 있다. `brandColor`(`#RRGGBB`)·`logoUrl`(`/logos/<파일>`, 웹 `public/logos/`)은 기업 노드에서 카탈로그에 있을 때만 값이 있고 이슈 노드와 미지정 기업은 `null`이다. 카탈로그 값이 형식에 맞지 않으면 그 필드만 무시하고 `/api/health`의 `warnings`에 알린다.
- 노드 `evidenceCount`: 사건 노드는 그 사건의 근거 ID 수이며 `GET /api/events/{id}`의 `evidenceIds` 길이와 같다(사건 상세를 열지 않고 근거의 두터움을 그릴 수 있다). 기업 노드는 `null`이다.
- 간선 `evidenceIds`: 승인 간선(`INVOLVES`·`STRUCTURALLY_RELATED_TO`·`FOLLOWS`)을 뒷받침하는 근거 ID이며 `GET /api/graph/edges/{id}`의 `evidenceIds`와 같다(같은 관계가 후보별로 여럿이면 합집합, 처음 나온 순서). 파생 `SHARES_ISSUE`는 승인 간선이 아니므로 항상 `[]`이고, 그 근거는 상세의 `via[].evidenceIds`에서 사건별로 본다. 두 필드는 기존 응답에 더한 필드이며 OpenAPI에서 `required`다.
- 간선 `summary`(그래프 라벨용 한국어 명사구, 승인 데이터에서만 만든다). `GET /api/graph/edges/{id}`도 같은 값을 준다.

| 간선 | `summary` |
|---|---|
| `INVOLVES` | 기사가 적은 역할(`role`). 알려진 영어 값은 한국어로 옮기고(`technology provider`→`기술 제공사`, `presenter`→`발표자`, `technology provider and collaborator`→`기술 제공사·협력사`; 알려진 역할 사이 `/` 또는 `and`도 `·`로 결합), 한글 값은 그대로 쓰되 `,`·`;` 앞 첫 구절만 남기며 14자를 넘으면 `…`로 줄인다. 같은 이슈-기업 쌍에 역할이 여럿이면 옮길 수 있는 첫 값. 매핑에 없는 영어 값·역할 없음은 `직접 관련`(추측하지 않는다). 매핑표는 `src/zoop_bff/summaries.py`의 `ROLE_KO` |
| `STRUCTURALLY_RELATED_TO` | 근거(`basis[].relation_type`)의 관계 유형: `SUPPLIES`→`공급`, `PRODUCES`→`생산`, `USES`→`사용`, `MANUFACTURES`→`제조`, `BUYS`→`구매`, `DEVELOPS`→`개발`. 여러 개면 이 순서로 `·`로 잇는다(예 `공급·생산`). 알려진 유형이 없으면 `구조적 관계` |
| `FOLLOWS` | `후속 사건` |
| `SHARES_ISSUE`(파생) | `같은 사건 N건`(N = `via` 이슈 수) |

### 시간

- `eventTime`은 PoC가 **승인한** `event_time`만 담는다. 미승인이면 `null`, `timePrecision:"unknown"`이며 기사 발행일(`articles[].publishedAt`)로 채우지 않는다. 필드 판정(`field_decisions`)이 HOLD/REJECT인 `event_time`/`period`도 비운다.
- `timePrecision`: `year|month|day|datetime|unknown`.
- `/api/events?from=&to=`: 발생 시각 구간이 겹치는 사건만 `items`에 반환한다. 시각 미상 사건은 범위에 넣을 수 없으므로 `items`에서 빼고 `metadata.excludedUnknownTime`에 개수를 알린다. 그중 `reportedAt`의 KST 날짜(오프셋 없으면 KST)가 범위 안인 사건은 `unknownTimeItems`(최근 보도순)에 따로 담는다. 보도 시각은 묶음 기준일 뿐 `eventTime`은 계속 `null`이다. `from`/`to`가 없으면 `unknownTimeItems`는 빈 배열이다. `metadata.latestEventTime`·`latestReportedAt`은 같은 범위(기업 또는 전체)에서 기간과 무관하게 가장 최근 발생 시각·보도 시각이다(빈 기간 안내용).
- 정렬: 사건 시각 내림차순, 미상은 뒤. 동률은 최신 기사 발행일, 이슈 ID 순(발행일은 정렬 보조에만 쓴다).

### 근거

- 근거 ID = `ev-` + SHA-256(`article_id|article_version|start|end`)의 앞 24자.
- `quoteVerified`: PoC `Evidence.matches()`로 원문 본문 `[start:end]`와 대조한 결과. 본문이 없는 snapshot(`--with-evidence` 없이 만든 것)은 `null`. 대조 실패(`false`)인 근거는 AI 예시 답변에 인용하지 않는다.

### 브리핑

사용자 `GET /api/briefings`는 **관리자 화면과 같은 회차 저장소에서 발행된 회차**를 그대로 보여 준다(요구 26–33). 개인화(요구 34)는 범위 밖이라 회원·비회원·세션 없음 모두 같은 응답이고 `matchedCompanyIds`는 항상 `[]`이다.

- 회차 = (발행일 KST, `morning`·`evening`), 예정 시각 **07:40 / 18:10 KST**, id `brf-YYYY-MM-DD-morning|evening`. `date`·`edition`을 생략하면 지금 KST 기준 가장 최근에 **시작된** 회차. `GET /api/briefings/rounds`는 열 수 있는(발행·제공 중단) 회차 목록.
- **데이터 창**: 마감(`end`) = 그 회차의 예정 시각, 시작(`start`) = 직전 회차의 예정 시각. 출근(D) = (D-1 18:10, D 07:40], 퇴근(D) = (D 07:40, D 18:10]. 창은 달력으로만 정해지고 앞 회차의 발행 여부와 무관하다. 이슈는 기사 발행 시각 중 가장 늦은 것(`latest_published_at`, 오프셋이 없으면 KST)이 창 안일 때 대상이다. **최초 회차 규칙**: 이 서비스(상태 디렉터리)가 처음 만든 회차는 `start:null`(`dataWindow.openStart:true`)이고, 그보다 앞선 회차는 만들지 않는다(409 `round_not_allowed`).
- **선정**: 창 안의 승인 이슈를 사건 시각이 최근인 순(`sort_recent`)으로 **최대 3개**. 기준을 채우는 이슈가 모자라면 채우지 않는다(빈 회차는 `emptyReason:"no_issues_in_window"`). 항목의 `reason`은 규칙 기반 문구, `summary`·`marketSummary`·`marketVariables`는 생산자가 없어 `unavailable`.
- **상태·검증**: `generating → verifying → published | failed`. 검증은 실제로 확인 가능한 것만 한다: 항목 ≤ 3, 참조한 이슈·근거·기업이 같은 그래프 버전(검수 기록 반영)에 있는지, 근거가 해당 이슈의 것인지, 인용이 원문과 맞는지(`quoteVerified:false` 금지), 이슈가 데이터 창 안인지, 생성 중 그래프 버전·검수 기록이 바뀌지 않았는지. 실패 사유는 관리자 화면에만 있고 사용자에게는 공통 문구만 나간다.
- **불변**: 같은 회차는 한 번만 발행되고 발행본(`payload`)은 수정·삭제할 수 없다(SQLite 트리거). 재처리는 미발행(`missing`·`failed`) 회차만, 정정·제공 중단은 발행본 옆에 별도 기록으로 둔다(`status:"suspended"`이면 `items:[]`와 `notice.reason`=관리자 사유).
- 스케줄러는 BFF 프로세스 안 스레드다(`ZOOP_BRIEFING_SCHEDULER`). 기동 때와 15초마다 "시각이 지났는데 기록이 없는 회차"를 만들되 6시간 안의 것만 따라잡고, 실패한 회차는 자동 재시도하지 않는다. 비정상 종료로 `generating`에 남은 회차는 기동 때 `failed`(`interrupted_by_restart`)로 정리한다.
- `metadata.schedule = {morning:"07:40", evening:"18:10", confirmed:true}`, `metadata.generatedBy = "bff-rule-v1"`, `metadata.selection = {basis:"market", reason:"recent_in_window"}`. 예측·확률·호재/악재 필드는 없다.

### AI 예시 답변 (규칙 기반)

맥락(`contextIds`: 이슈·기업·간선·근거 ID)에 연결된 승인 근거 인용을 질문과의 단어 겹침 순으로 최대 3개 나열하는 템플릿이다. `status: answered|insufficient_evidence`, `reason`(insufficient일 때), `sources:[evidenceId]`, `citations`, `graphTargets`, `metadata.generatedBy="bff-example-v0"`. 맥락 없음, 맥락에 근거 없음, 원문 대조 실패, 주가 예측·매매·호재/악재 성격의 질문은 `insufficient_evidence`다. 대화는 만든 세션만 읽을 수 있다(다른 세션 403).

## 응답 `metadata`

모든 데이터 응답에 `metadata`가 있다.

| 필드 | 뜻 |
|---|---|
| `datasetKind` | `approved-snapshot`(실제 기사 승인 버전), `synthetic-preview`(합성 기사 포함·기사 출처 미확인·빈 데이터). `approved-live`는 더 이상 만들지 않는다(사용자 API는 PoC DB를 직접 읽지 않음). 기사별 `synthetic:false`를 확인한다. |
| `source` | `snapshot:<파일명>`(시드 v1) / `ledger:<DB 이름>`(원장에서 게시한 버전) / `bff-mock` |
| `asOf` | 버전: 등록·게시 시각 또는 `zoop.asOf`, mock: 생성 시각 |
| `sourceMode` | `snapshot`(저장된 게시 버전) / `mock` |
| `graphVersion` | 응답을 만든 활성 게시 버전 id(`v1`, `v2`…). BFF mock 내용은 `null`. `/api/health`에도 있다 |
| `synthetic` | 합성 데이터 여부 |
| `generatedBy` | BFF가 만든 내용이면 생성 주체(`bff-rule-v1`, `bff-example-v0`, `bff-mock-*`), PoC 데이터면 `null` |

원장에서 게시한 버전(`ledger:…`)과 시드 스냅샷은 모두 `sourceMode:"snapshot"`이다. 어느 쪽인지는 `source`와 `graphVersion`으로 구분하고, 실제·합성 기사 여부는 `datasetKind`로 구분한다.

관심종목을 저장한 뒤 튜토리얼 완료 상태만 PUT으로 갱신해도 기존 관심목록을 보존한다. 저장된 종목도 현재 기업 카탈로그로 검증한다.

## PoC에서 오는 것과 mock인 것

| 구분 | 필드 | 출처 |
|---|---|---|
| **PoC (승인 원장)** | 이슈(사건) ID·제목·행동·대상·`event_time`·`period`·`assertion_status`·참여 기업 역할, 기사(제목·발행처·URL·발행일), 관계 5종(`REPORTS`/`PROVIDES_BACKGROUND`→기사 목록, `INVOLVES`/`STRUCTURALLY_RELATED_TO`/`FOLLOWS`→그래프), 근거(인용·위치·기사 버전), `basis`, `source_support`, `field_decisions` | `inspect().issues` |
| PoC + 카탈로그 | 기업 이름·티커·별칭, 표시용 `brandColor`·`logoUrl`(카탈로그에 있을 때만) | PoC `settings.json` companies < snapshot `zoop.companies` < 승인 언급의 participants 이름 < 기업 ID(이 순서로 덮어씀). 같은 `company_id`는 뒤 항목이 레코드째 덮어쓴다(필드 병합 없음) |
| BFF 파생 | 기업–기업 `SHARES_ISSUE`, 근거 ID, `quoteVerified`, 시간 정밀도, 간선 ID, 정렬 | 승인 데이터에서 계산 |
| **unavailable** | 사건·기업 요약(`summary`), 감성, 시세·가격(`price`, `/prices`), 평가금액, 브리핑 예측 평가 | 생산자 없음 |
| **BFF mock/규칙** | 인증·세션, 설정, 가상 계좌(`mockPortfolios`), 관심종목, 브리핑 편성, AI 예시 답변 | `metadata.generatedBy` |

## Snapshot 확장 키 (`zoop`)

snapshot JSON은 `poc inspect --with-evidence --output` 형태(`{issues, candidates?, errors}`)이며, 데모 픽스처는 선택 확장 키 `zoop`을 최상위에 더할 수 있다. 시드 스냅샷과 원장에서 게시한 버전 모두에서 `mockPortfolios`가 없으면 BFF 기본 계좌 `mock-basic` 1개를 만든다(가상 계좌에 연결하는 순간 보유 종목이 회원 기록에 고정되므로, 이후 버전 게시·되돌리기가 연결된 계좌와 저장된 관심종목을 무효로 만들지 않는다).

```jsonc
{
  "issues": [ /* inspect() 원형 */ ],
  "candidates": [ /* 선택. 없어도 됨 */ ],
  "errors": [],
  "zoop": {
    "asOf": "2026-09-29T00:00:00+00:00",          // 선택. 없으면 파일 수정 시각
    "companies": [                                 // 선택. company_id로 PoC settings 카탈로그를 덮어씀
      { "company_id": "KR-005930", "name": "삼성전자", "ticker": "005930",
        "aliases": ["Samsung Electronics"], "sector": "반도체",   // ticker/aliases/sector는 선택
        "brand_color": "#1428A0", "logo": "samsung.svg", "brand_source": "https://…" }   // 표시 확장(선택)
    ],
    "mockPortfolios": [                            // 선택. 없으면 BFF 기본 mock-basic
      { "id": "mock-growth", "label": "가상 성장주 계좌",
        "holdings": [ { "companyId": "KR-005930", "quantity": 10, "avgPrice": 70000 } ] }
    ]
  }
}
```

| 키 | 규칙 |
|---|---|
| `zoop.companies[]` | `company_id`·`name` 문자열 필수. `aliases`는 문자열 배열, `ticker`/`sector`는 문자열 또는 생략/`null`. 표시 확장 키는 아래 "기업 카탈로그 확장 키" |
| `zoop.mockPortfolios[]` | `id`·`label`·`holdings[]` 필수. `holdings[]`는 `companyId` 문자열, `quantity` > 0, `avgPrice` ≥ 0(숫자). 카탈로그에 없는 `companyId`는 이름 대신 ID로 표시되므로 `zoop.companies`에 넣을 것. `avgPrice`의 통화 단위는 정의하지 않는다(mock) |
| `zoop.asOf` | ISO8601 문자열 |
| 형식 오류 | 서버는 기동되지만 데이터 요청은 503 `source_unavailable`(`details.reason`에 원인) |

### 기업 카탈로그 확장 키 (`brand_color`·`logo`·`brand_source`)

`ZOOP_COMPANY_CATALOG`의 `companies[]`와 snapshot `zoop.companies[]`에 같은 선택 키를 더할 수 있다. 모두 생략하거나 `null`이어도 된다.

| 키 | 규칙 | 응답 |
|---|---|---|
| `brand_color` | `#RRGGBB`(16진수 6자리, `#` 필수). 그 외 형식은 무시 | `brandColor`(그래프 기업 노드, `/api/companies`, `/api/companies/{id}`) |
| `logo` | 웹 `public/logos/` 안의 **파일명만**(`nvidia.svg`). 영문·숫자로 시작하고 영문·숫자·`.`·`_`·`-`만 허용하며 `..`·`/`·`?`·`#`은 거부 | `logoUrl` = `/logos/<파일명>`(서버는 파일 존재를 확인하지 않는다) |
| `brand_source` | 색·로고 출처 URL(문서용). 응답에는 나오지 않는다 | — |

형식이 틀린 `brand_color`·`logo`는 그 필드만 `null`로 두고(다른 필드·다른 기업은 그대로) `/api/health`의 `warnings`에 `<출처>: <키> of <company_id> ignored (invalid format)`을 남긴다(잘못된 값 자체는 응답에 싣지 않는다). `warnings`가 있으면 `status`는 `degraded`다.

수작업 픽스처 작성 시 주의:

- 이슈는 `inspect()` 원형(`issue_id`, `mentions[]`, `articles[]`, `relations[]`, `candidate_ids`, `field_decisions`, `source_support`)을 따른다. 승인된 관계(`relations`)만 그래프에 나온다.
- `quoteVerified`가 `true`가 되려면 `articles[].body`가 있고 `evidence.article_version`이 PoC 기사 버전과 같고 `body[start:end] == quote`여야 한다. 기사 버전 계산: `uv run python -c "import json,sys; from investmate.domain import Article; print(Article(**json.load(sys.stdin)).version)" < article.json` (`collected_at`은 버전에서 제외됨).
- 승인되지 않은 필드는 PoC처럼 언급에서 키를 제거한다(`event_time`이 없으면 사건 시각 미상).
- `candidates`에 `HOLD`/`REJECT`가 있어도 공개 데이터에는 나오지 않는다. `issues[].candidate_ids`가 HOLD/REJECT/비활성 후보를 가리키면 그 이슈는 공개하지 않는다.

## 스트레스 스냅샷 (`fixtures/synthetic-stress-300.json`)

그래프 화면(레이아웃·LOD·고립 사건·포커스)을 시험하려고 `scripts/make_stress_fixture.py`가 만든 **합성** 스냅샷이다(기업 40 + 사건 260 = 300노드, `datasetKind:"synthetic-preview"`). 모든 기사는 `synthetic:true`이고 기업명은 `가상전자`·`시험반도체`처럼 명백한 가상 이름이며 로고·브랜드 색은 없다. 실제 기사 검수 결과가 아니므로 화면에서 실제 데이터처럼 보이게 하지 않는다.

```bash
cd prototype/bff
ZOOP_SNAPSHOT_PATH=$PWD/fixtures/synthetic-stress-300.json ZOOP_COMPANY_CATALOG=$PWD/fixtures/synthetic-stress-300.json \
  uv run uvicorn zoop_bff.main:app --port 8787
uv run python scripts/make_stress_fixture.py           # 다시 만들기(seed 고정: 같은 코드면 같은 바이트)
uv run python scripts/make_stress_fixture.py --check   # 커밋된 파일과 다르면 종료 코드 1
```

`ZOOP_COMPANY_CATALOG`를 스냅샷 파일 자신으로 두는 것은 PoC 기본 카탈로그(`SYNTH-ALPHA`)가 섞이지 않게 하려는 것이다(최상위 `companies`가 없는 파일은 빈 카탈로그로 읽힌다). 기업 이름은 스냅샷의 `zoop.companies`에서 온다. 기사 버전·관계 ID·`source_support`는 PoC 코드(`investmate`)로 계산하고 생성 때마다 PoC 모델로 검증한다.

| 구조 | 내용 (시장 그래프 `/api/graph`) |
|---|---|
| 규모 | 노드 300(기업 40·사건 260), 간선 483(승인 368 = `INVOLVES` 342·`STRUCTURALLY_RELATED_TO` 14·`FOLLOWS` 12, 파생 `SHARES_ISSUE` 115), 근거 531 |
| 고립 사건 | 39건(15%). 승인 관계가 `REPORTS`뿐이라 연결이 0인 사건(참여자에 `company_id` 없음) |
| 허브 | `STRESS-C01`(25건)·`STRESS-C02`(19)·`STRESS-C03`(17). 다른 기업은 15건 미만 |
| 함께 등장하는 쌍 | 여러 사건을 공유하는 기업 쌍(최대 5건, 라벨 `같은 사건 N건`) |
| 후속 사건 | `FOLLOWS` 사슬 5개(갈래가 있는 사슬 1개, 다른 기업의 사건으로 이어지는 사슬 1개 포함) |
| 구조적 관계 | `STRUCTURALLY_RELATED_TO` 14건, 카탈로그 `basis` 1~2개 |
| 2단계 포커스 | `companyId=STRESS-C10`: `depth=1`은 8노드, `depth=2`는 43노드(C10 → 사건 → C11~C13 → 그 기업의 사건 → C14~C19) |
| 시간 | 사건 시각 2026-07-01~2026-09-24(불규칙하게 몰림). 일 단위 대부분, 월 단위 20건, 시각 미상 5건 |
| 근거 | 인용은 기사 본문 `[start:end]`와 정확히 일치해 모든 근거가 `quoteVerified:true`. 사건마다 근거 1~6개 |
| 비공개 | `candidates`에 `HOLD` 5건·`REJECT` 2건(허브·`STRESS-C10`과 이어지는 기업 포함)만 있고(ALLOW 후보 감사 행은 없다) 어떤 공개 응답에도 나오지 않는다 |

## 관리자 API·운영

`/api/admin/*`은 회원 세션과 **완전히 분리된** 관리자 세션만 받는다. 요청·응답 형태는 `/openapi.json`(스키마 이름은 `admin_schemas.py`)이 기준이다. 오류는 같은 `{"error":{"code","message","details?"}}`이고, 모든 변경 요청은 `reason`(1~500자)이 필수이며 감사 로그에 남는다.

### 인증 (요구 82)

| 항목 | 내용 |
|---|---|
| 쿠키 | `zoop_admin_session`(HttpOnly, SameSite=Lax, Path=/). 회원 쿠키 `zoop_session`과 저장소·발급이 따로다 |
| 데모 관리자(개발 전용) | `admin@zoop.local` / `zoop-admin`. 비밀번호는 PBKDF2-SHA256 해시로만 저장(SQLite) |
| 만료 | 유휴 30분(`ZOOP_ADMIN_IDLE_SECONDS`) · 절대 8시간(`ZOOP_ADMIN_ABSOLUTE_SECONDS`). 관리자 API 호출은 유휴 시간을 갱신하고 `GET /api/admin/auth/session`은 갱신하지 않는다 |
| 오류 | 401 `admin_auth_required` · 401 `admin_session_expired`(`details.reason: idle|absolute`) · 403 `admin_forbidden`(회원·비회원 쿠키만 있음) |
| SSO | **구현하지 않았다.** 이 프로토타입에는 IdP가 없다 |
| 감사 로그 | `GET /api/admin/audit-log?action=&actor=&targetType=&q=&limit=&cursor=` — 로그인·로그아웃·검수·버전 게시/활성화·작업·브리핑 변경의 누가·언제·무엇·사유. 비밀번호·쿠키 값은 어디에도 남기지 않는다 |

### 관제·검수·그래프 버전 (요구 76)

- 원장 = Docker `zoop-poc` Postgres의 실뉴스 DB `investmate_zoop_real`(`docker start zoop-poc-postgres-1 zoop-poc-neo4j-1`). 관리자는 `PostgresRepository.inspect()`의 승인 `issues`와 `candidates`(ALLOW/HOLD/REJECT·active·reasons)를 본다. 원장이 죽으면 원장 조회 API만 503 `ledger_unavailable`이고 사용자 그래프·버전·작업·대시보드는 계속 동작한다.
- **검수 기록**: PoC DB는 수정하지 않는다. `POST /api/admin/pipeline/candidates/{id}/decision {decision: allow|reject, reason, relationId?}`는 BFF 상태 디렉터리에 결정(대상·사유·시각·관리자)을 남기고 **활성 버전 위에 덮어 적용**한다. reject는 즉시 사용자 그래프에서 빠지고, HOLD를 allow하면 후보의 mention·기사·근거 있는 관계로 공개 이슈를 구성해 `관리자 승인`으로 표시한다(원문 인용이 없으면 422 `evidence_required`, REJECT 상태 409 `status_not_reviewable`, 비활성 409 `candidate_inactive`). 같은 결정을 다시 보내면 `idempotent:true`로 기존 기록을 돌려주고 새 기록·감사 로그·리비전을 만들지 않는다. 스냅샷의 `review_exclusions`(FOLLOWS 오승인 1건)는 최초 기동 때 `origin:"snapshot-migration"` reject 기록으로 이관된다.
- **그래프 버전**: 사용자 그래프 = 활성 게시 버전(읽기 전용 파일 + SHA-256, 읽을 때마다 해시 확인) + 검수 기록. 첫 기동 때 `ZOOP_SNAPSHOT_PATH`가 `v1`(seed)이 된다. `POST /api/admin/graph/versions`는 현재 원장 `inspect()`를 새 불변 버전으로 저장하고 곧바로 활성화한다(원장이 활성 버전과 같으면 409 `version_unchanged`). `POST /api/admin/graph/versions/{id}/activate`로 되돌린다. 버전을 게시하거나 되돌려도 **저장된 회원 설정(관심종목·연결한 가상 계좌)은 무효가 되지 않는다**: 관심종목 검증은 카탈로그와 등록된 모든 버전의 기업, 회원이 이미 저장한 ID를 기준으로 하고 활성 버전에만 의존하지 않는다.
- **GraphDB 반영**: PoC outbox의 미완료 투영 작업 수(`pendingJobs`)와 Neo4j를 **원장 이슈 단위**로 비교한다. `issuesProjected`는 "원장 이슈 중 Neo4j가 모든 관계와 함께 가진 수"라서 `issuesInLedger`와 같은 단위다. `missingIssueIds` = 원장에는 있는데 Neo4j에 없거나 관계가 모자란 이슈(→ `mismatch`), `staleIssueIds` = Neo4j에만 있는 이슈(원장에 아예 없으면 **외부 이슈**로 보고만 하고 상태를 바꾸지 않는다. `zoop-poc` Neo4j는 합성 원장의 투영도 담는다). 버전 게시·되돌리기는 GraphDB를 건드리지 않는다.

### 작업 러너 (요구 76·59)

`GET|POST /api/admin/jobs`, `GET /{id}`, `POST /{id}/retry`, `POST /{id}/cancel`. PoC CLI를 **샌드박스에서 실제로 실행**하고 동시에 하나만 돈다.

| kind | 실행 | 비용 |
|---|---|---|
| `flush-graph` | `poc flush-graph` (GraphDB 반영 재시도) | 모델 호출 없음 |
| `retry-model-errors` | `poc run --live --retry-model-errors --config <작업별 settings.json>` | **유료.** `confirmPaid:true`(정확히 JSON true)가 없으면 422 `paid_confirmation_required`, `maxModelCalls`는 기본 50 · 1~`ZOOP_ADMIN_MAX_MODEL_CALLS`(기본 200)이며 벗어나면 422 `max_model_calls_invalid`. 작업별 설정 파일의 `max_calls`로 PoC가 그 횟수에서 모델 호출을 멈춘다 |

- 이미 `queued|running` 작업이 있으면 같은 kind는 그 작업을 돌려주고(200, `deduplicated:true`), 다른 kind는 409 `job_in_progress`다. 상태는 `queued/running/succeeded/failed/cancelled`, 시작·종료 시각, 종료 코드, RunReport(processed·approved·held·rejected·pending·errors·usage), 실행 전후 원장 수치, 로그 꼬리(300줄, 비밀값 마스킹), 취소(SIGINT → SIGTERM → SIGKILL)를 기록한다. CLI가 남은 오류로 종료 코드 1을 내면 `failed`(`cli_nonzero_exit`)로 두되 보고서는 그대로 싣는다.
- 작업 기록은 상태 디렉터리에 영속한다. BFF가 재시작될 때 `queued|running`이던 작업은 남은 프로세스를 정리하고 `failed` + `recovered:true` + `interrupted_by_restart`로 확정한다(출력된 보고서가 있으면 첨부).
- 작업이 끝나도 **사용자 그래프는 바뀌지 않는다.** 원장이 바뀐 것을 반영하려면 관리자가 버전을 게시해야 한다.

### 샌드박스 (`ZOOP_POC_SANDBOX`, 기본 `~/.local/share/zoop/investmate-sandbox`)

PoC 원본은 건드리지 않고 사본에서 실행한다. 사본은 이 절차로 만들었다.

```bash
SRC=/Users/asqi/InvestMateLogicTest; DST=$HOME/.local/share/zoop/investmate-sandbox
rsync -a --exclude .venv --exclude .pytest_cache --exclude .ruff_cache --exclude __pycache__ "$SRC"/ "$DST"/   # .env는 파일 복사만(값을 읽거나 출력하지 않는다)
cd "$DST" && uv sync --offline --locked               # 실패하면 온라인 동기화 허용
diff -qr "$SRC/src" "$DST/src"                        # 차이 없음이어야 한다
# 완화 정책 설정: runtime/web-approval-live/final-settings.json 기반 zoop-real-relaxed-settings.json
#   (policy_version=zoop-real-relaxed-no-web-1, support_min 0.65, contradiction_max 0.10, reject_min 0.90, 웹 검증 없음 — docs/evidence/poc-backend.md §9)
```

- 작업 자식 프로세스의 환경은 샌드박스 `.env`에 BFF가 정한 `DATABASE_URL`(`ZOOP_ADMIN_POC_DSN`)·Neo4j 접속·`REDIS_URL=''`를 덮어쓴 것이다. 비밀값은 자식 환경에만 있고 API·로그에는 `[redacted]`로 나간다.
- **유료 작업 전 정책 해시 확인**: `GET /api/admin/jobs`의 `sandbox.policy`가 샌드박스 설정이 활성화할 정책(`expected`, 샌드박스 인터프리터가 `Settings.policy_for()`로 계산)과 DB의 활성 정책(`active`, `poc policy-status`와 같은 `investmate.policy`)을 비교한다. `match`가 `true`가 아니면 유료 작업은 409 `policy_mismatch`/`sandbox_not_ready`로 시작하지 않는다. **`activate-policy`는 BFF가 절대 자동 실행하지 않는다**(원인을 사람이 확인한다).
- 비용 상한: 요청마다 `max_calls`, 서버 전체 상한 `ZOOP_ADMIN_MAX_MODEL_CALLS`. PoC `estimated_cost`가 `null`이라 실제·추정 비용은 제공하지 않고(`status:"unavailable"`) 단가를 만들지 않는다.

### AI 사용량·비용 (요구 77)

`GET /api/admin/ai-usage?window=24h|7d|30d|all`. 챗봇·브리핑은 규칙 기반이라 `modelBacked:false`·모델 호출 0회로 표기하되 요청·실패·처리 시간은 실측한다(클라이언트 오류 4xx는 AI 요청으로 세지 않음). 뉴스 분석은 기간 안의 관리자 재처리 작업 합계이고, `window=all`은 원장 `investmate.runs`의 과거 실행(엄격 600회·완화 400회 등)을 읽는다. 원장을 못 읽으면 `docs/evidence/poc-backend.md` §8·§9.2 기록 값을 `source:"document"`로 제공하며 문서가 말하지 않는 값은 `null`이다.

### 브리핑 운영 (요구 79·80)

`GET /api/admin/briefings[?from=&to=]`, `GET /{id}`, `POST /{id}/reprocess`(미발행 회차만, 모델 호출 없음), `POST /{id}/corrections`(원문·정정·사유·시점을 따로 보존하는 append-only), `POST /{id}/suspension {action: suspend|resume}`. 발행본은 어떤 경로로도 바뀌지 않는다(위 "브리핑").

### 이용 통계·선호도·회원 관리 (요구 74·75·78)

**수집** — `POST /api/telemetry`(회원·비회원 세션 필요, 202). 허용 이벤트는 `screen_view{screen: main|briefing, viewId}`, `graph_node_select`·`graph_edge_select{targetId, viewId?}`, `briefing_view{targetId=회차 id}`, `briefing_issue_open{targetId=이슈 id, roundId}` 뿐이고 그 밖의 필드·타입은 422다. 배치 최대 20개, 본문 16KiB 초과 413, 세션당 분당 60요청·240이벤트 초과 429(배치를 통째로 거절). 저장 주체는 회원 id 또는 비회원 세션의 키 해시(`insights_common.SubjectKeys`; 이름·이메일·IP는 저장하지 않는다). 기업·이슈 연결은 받은 시점의 활성 그래프로 한 번 풀어 저장한다. AI 질문은 서버의 대화 기록(`chat_messages`), 온보딩은 회원 설정에서 센다(클라이언트 이벤트에 의존하지 않음).
**통계** — `GET /api/admin/insights/{overview|summary|companies|companies/{id}}?window=7d|30d|all`. 기간은 KST 달력일. 모든 지표는 산식·정의 문장을 응답에 담고, **분모가 5 미만이면 비율은 null(`sampleHidden`)이고 건수만** 준다. 노드·간선 클릭률은 "메인 노출(`viewId`) 중 한 번이라도 고른 노출의 비율"이다.
**선호도** — `PUT|DELETE|GET /api/feedback`: 대상은 챗봇 답변(`chatbot_answer`, 질문한 본인만), 발행된 브리핑 회차(`briefing_round`)·핵심 이슈(`briefing_issue`, `<회차 id>/<이슈 id>`). 1인 1표(`feedback` 기본키), 같은 값 재전송은 변화 없음, 반대 값은 표를 바꾸고, DELETE로 취소한다. 사유(≤200자)는 싫어요에만. 뉴스 요약은 생산자가 없어 대상이 없다(관리자 응답 `unsupported`에 이유 표시). `GET /api/admin/feedback/{summary|dislikes}`, `GET /api/admin/transcripts[/{id}]`.
**대화록 마스킹** — 대화는 `chat_sessions`·`chat_messages`(statedb)에 원문 그대로 영속하고, 관리자 응답에서만 `masking.Masker`가 이메일·전화번호·주민등록번호·카드번호·계좌번호와 작성 회원의 표시 이름·이메일을 `[이메일]` 같은 표지로 바꾼다. 대화록 열람은 감사 로그 `transcript.view`에 남는다. 사용자는 가명 id(`M-XXXXXXXX`/`G-XXXXXXXX`)로만 보인다.
**회원** — `GET /api/admin/members[?status=&q=]`, `GET /{id}`, `POST /{id}/block|unblock {reason}`. 목록은 가명 id·가린 이메일(`d***@zoop.local`)·가입 방식·시각·활동(세션·그래프 선택·AI 질문·브리핑 조회)·상태만 준다. 사유는 공백만으로는 안 되고, 차단·해제는 멱등이며(이미 같은 상태면 `changed:false`, 감사 기록 없음) 상태 변경과 감사 기록이 한 트랜잭션이다. 차단하면 열린 세션의 다음 요청이 401 `member_blocked`, 로그인은 403 `member_blocked`(회원 저장소는 `accounts.AccountStore.set_status`). 데모 관리자는 관리자 계정이라 회원 목록에 나오지 않는다.

### 대시보드 (요구 81)

`GET /api/admin/dashboard`: 활성 버전·검수 대기(HOLD)·GraphDB 반영·최근 작업(실패 24시간)·AI 사용 요약·최근 브리핑 회차 상태·회원 수 요약(BFF mock 기준). 원장이 죽어도 200이고 해당 구역만 비운다.

## 명세 v0.2 §8 대비 차이

| 항목 | 내용 |
|---|---|
| 추가(명세 추가 제안) | `GET /api/companies`(관심종목 선택, FR-08~15), `GET /api/portfolio/mock-portfolios`, `POST /api/auth/guest`(비회원, UI-01), `GET /api/health` |
| 미구현 | `POST /api/auth/signup`(가입은 데모 계정 1개로 대체), `POST /api/portfolio/sync`, `GET /api/events`의 `scope`·`cursor`, `GET /api/graph`의 `asOf`(PoC는 현재 승인 상태만 제공), 페이지네이션 |
| 응답 | `GET /api/companies/{id}`의 "기준 시각"은 `metadata.asOf`. 사건 목록은 `items` 배열. `GET /api/auth/session`은 세션이 없어도 200(`kind:"anonymous"`) |
| 경계 | `GET /api/companies/{id}/prices`, `GET /api/briefings/{id}/evaluations`는 명세상 200이지만 데이터 생산자가 없어 본문이 `unavailable` |
| 미정 사항 | 브리핑 시각은 07:40/18:10 KST + `confirmed:true`(요구 확정). 계좌 성공 후 관심 선택 강제 여부는 정하지 않음(계좌만 연결해도 설정 완료 가능) |

## Offline review-exclusion regression

`fixtures/reviewed-follows-regression.json` is a small synthetic reproduction of the manually excluded One UI FOLLOWS relation `relation-021ae4e61e1b08cd14affc58`. It retains the audit candidate but omits the relation from the public issue view. `tests/test_review_exclusions.py` checks fixture integrity, graph/event/evidence publication, and the non-derived graph used as path input. It also checks the local reviewed real snapshot when present; that optional snapshot is not required by the deterministic tests.

`review_exclusions` is no longer inert metadata: on the first start the snapshot's entries are registered once as relation rejections (`origin:"snapshot-migration"`) in the review records, which are applied over every graph version. The regression therefore holds even if a relation is re-inserted into `issues[].relations` (`test_review_exclusions.py`). Shared mention evidence remains public; evidence found only in the audit candidate is not registered. No BFF path endpoint or browser path implementation is tested.

Run with the existing environment, without installation or service startup (the whole suite is offline: the ledger, Neo4j, the sandbox and the CLI child process are replaced by fakes):

```bash
PYTHONDONTWRITEBYTECODE=1 .venv/bin/python -m pytest -p no:cacheprovider --basetemp=/tmp/zoop-bff-tests tests
```
