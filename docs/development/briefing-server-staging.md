# 저장 브리핑의 서버 반입 준비

#553의 조회·표시 계약에 기존 생성 결과를 연결하는 준비 도구다. 모델 호출이나 DB 연결은 하지 않는다. 실제 뉴스·생성 문안·개인 설정은 공개 저장소에 포함하지 않는다.

## 저장 위치와 원본 보존

| 내용 | 서버 테이블·필드 |
| --- | --- |
| 공통 회차·시장 지표·기존 조회 필드 | `briefing_rounds.published_payload` |
| 새 공통 이슈·영향·전망 | `briefing_rounds.public_snapshot.commonPriority` |
| 새 공통 시장 요약 | `briefing_rounds.public_snapshot.prioritySummary` |
| 시장·거래 세션·이전 요약 참조 원본 | `public_snapshot.priorityContext` 및 `contexts.jsonl` |
| 회차별 보존 후보 풀 | `briefing_personal_pools` |
| 해당 실험의 고정 설정 | `briefing_personal_preferences` |
| 개인화 이슈·영향·전망 | `briefing_personal_deliveries.result_snapshot.presentation.personalPriority` |
| 같은 버전 원문·정확 인용 | `artifacts`, `articles`, `article_versions`, `evidence` |

원본 24개 JSON은 `archive/`에 바이트 그대로 보관한다. 새 테이블 형식은 별도 사본이다. 문장·긍부정·전망·가격 관측을 다시 생성하지 않는다. 재선정 전 개인화 시장 요약은 원본에 남기고, 새 개인화 카드와 함께 새 요약인 것처럼 내보내지 않는다.

`context:market`, `context:sessions`, `context:previous`는 기사 인용이 아니다. 기사 근거 목록에 가짜 evidence 행을 만들지 않고, 원래 참조 목록·스냅샷·해시를 별도 보관한다. 실제 공개 시에는 이 맥락과 저장된 시장 데이터·이전 회차의 연결도 검토해야 한다.

## 1. 비공개 자료 준비

```sh
python3 scripts/prepare_briefing_server_bundle.py \
  --input-sqlite /private/source/briefing.sqlite3 \
  --native-root /private/source/native \
  --release-root /private/source/common \
  --personal-release-root /private/source/personal \
  --profile-file /private/source/test-profile-private.json \
  --output /private/output/new-bundle
```

출력 경로는 새 경로여야 한다. 파일은 0600, 최상위 디렉터리는 0700으로 생성한다. 원본 DB는 읽기 전용으로 열고, 원본 SHA·인용·본문 SHA·회차 시점을 대조한다. 언어 혼입 발견은 `language-findings.json`에 위치·해시만 기록하며 원본을 수정하지 않는다. 정확 인용 영수증은 문자 범위 일치만 입증하며 의미 검증·공개 권한을 승인하지 않는다.

문서 버전은 native 관측에 저장된 ID를 유지한다. `article_versions.collected_at`은 보존 수집 기록의 실제 `observedAt`이며 기사 발행 시각으로 대체하지 않는다. 실제 수집이 뒤늦게 이뤄진 과거 시뮬레이션이라는 점도 보존한다.

## 2. 대상 서버 사전 확인

운영자가 읽기 전용으로 다음을 확인한다. 이 문서는 실제 서버에 접속하거나 실행하지 않는다.

```sql
SELECT version, description, success
FROM flyway_schema_history ORDER BY installed_rank DESC LIMIT 10;

SELECT id, round_date, edition, status, published_at, payload_sha256
FROM briefing_rounds
WHERE round_date BETWEEN DATE '2026-10-28' AND DATE '2026-11-02'
ORDER BY scheduled_at;

SELECT id, active FROM graph_versions ORDER BY created_at DESC LIMIT 10;

-- 실제 회원 ID는 담당자가 바인딩한다. 계정·설정을 생성하거나 덮어쓰지 않는다.
SELECT id, status FROM members WHERE id = :target_member_id;
SELECT id, revision, created_at, effective_from
FROM briefing_personal_preferences WHERE member_id = :target_member_id ORDER BY revision DESC;
```

동일 회차·슬롯에 기존 발행본이 있으면 덮어쓰지 않는다. 문서·근거 ID가 이미 존재하는 경우에도 값이 다르면 중단하고 기존 버전과 대조한다. 대상 회원·설정 리비전·현재 공개 권한·고정 그래프 연결이 확인돼야 한다. 실험 회원의 포트폴리오를 다른 회원의 보유 종목이라고 표시하지 않는다.

## 3. 반입 SQL 작성과 검토

```sh
python3 scripts/render_briefing_staging_sql.py \
  --bundle /private/output/new-bundle \
  --member-id TARGET_MEMBER_ID \
  --preference-revision UNUSED_POSITIVE_REVISION \
  --artifact-uri-base artifact-root:artifacts \
  --output /private/output/stage.sql
```

이 명령도 DB에 연결하지 않는다. 담당자가 서버의 `ZOOP_DOCUMENT_READ_ARTIFACT_ROOT` 아래 `artifacts/`에 파일을 복사하고 소유자·권한(디렉터리 0700, 파일 0600)을 맞춰야 한다. DB URI는 서버 reader가 지원하는 `artifact-root:<디렉터리>/<파일>` 형식이다. S3 URL이나 로컬 절대 파일 URI를 그대로 넣으면 이 reader에서 읽을 수 없다. SQL은 한 트랜잭션에서 INSERT만 수행하며 기존 행과 같을 때만 재실행을 허용한다. 값·슬롯·설정 리비전 충돌은 전체 롤백한다. 기업 카탈로그의 기존 이름·별칭·프로필은 보존한다. JSONB 해시는 PostgreSQL의 `jsonb::text`로 계산한다.

반입본은 **공통 scheduled/unpublished, 기사 private, 개인화 demo**다. 과거 운영 발행이나 자동 제공 실적으로 위장하지 않는다. grant ID·리비전·수신자와 그래프 버전을 자동 생성하지 않는다. 운영 스케줄러는 활성화하지 않는다. 후보 풀은 저장 결과의 검토용 입력이며, 직접·간접 관계를 추정해 신규 선정용 풀로 승인하지 않는다.

## 공개 전 남은 조건

1. 문서 담당자가 실제 문서 버전의 현재 사용 권한·등록부를 제공한다.
2. 해당 자료의 고정 그래프 버전과 출처 결속을 등록한다. 최신 활성 그래프로 과거 기준을 바꾸지 않는다.
3. 대상 회원과 비공개 실험 범위를 확정한다. 설정 변경이나 기존 평가 이관을 자동 수행하지 않는다.
4. 시장 맥락·이전 회차 참조 연결 및 발견된 언어 품질 문제를 별도 수정 버전으로 검토한다.
5. 서버 적재·공개 API·회원 격리·실제 화면 검증 후 별도 발행 절차를 진행한다.

`publicationReady=false`는 의도된 상태다. #553만 병합하거나 SQL을 적재하는 것만으로 기존 비공개 자료가 서버 사용자에게 공개되는 구조가 아니다.

## 회원·권한·최소 내부 근거 연결 준비

과거 지도 화면을 추가하지 않는다. 아래 도구는 기존 후보 풀과 인용을 재사용해 **조회 검증에 필요한 ID 연결 요청서**만 만든다. 새 지도 선택기나 native graph publication을 생성하지 않는다.

```sh
python3 scripts/prepare_briefing_read_bindings.py \
  --bundle /private/output/new-bundle \
  --profile-file /private/source/test-profile-private.json \
  --source-registry /private/source/native/corpus-v2/registry.json \
  --output /private/output/new-read-bindings
```

대상 서버 회원을 정했다면 `--target-member-id`를 명시한다. 생략하면 대상은 미지정이며 로컬 시험 회원을 서버 회원으로 간주하지 않는다. 지정해도 DB 확인 전에는 mappingVerified=false다.

| 출력 | 역할 |
| --- | --- |
| member-mapping.json | 원래 회원·설정 리비전·적용 시각, 명시적인 대상 회원, demo 범위와 소급 제공 금지 |
| document-authority-requests.json | 문서 ID·버전·본문 SHA·원래 공급자 ID와 현재 grant의 관측값, 아직 승인되지 않은 용도·수신자 연결 요청 |
| internal-basis/ 및 index | 회차 cutoff에 맞는 후보·기업·근거 ID 연결, 등록할 내부 근거 범위의 해시. graphVersion은 미지정 |
| server-preflight-readonly.sql | 대상 회원·설정·문서 버전·기존 회차와 그래프 메타데이터를 확인하는 SELECT/ROLLBACK. 자동 실행하지 않음 |
| gates.json | 자료 무결성/참조 검증과 실제 회원·권한·등록 상태를 분리 |

내부 근거 범위에는 회차별 전체 보존 후보를 사용해 개인화 전용 사건도 빠뜨리지 않는다. 회원 ID·보유/관심·개인 선정 표시는 이 범위 파일에 넣지 않는다. 동일 기업의 독립 사건은 유지하며, 저장된 기업 참조를 새로운 영향 검증 PASS나 긍부정으로 바꾸지 않는다.

이 파일은 승인된 grant 등록부나 native 그래프가 아니다. pending 값이나 scope hash를 실제 graphVersion으로 채우면 안 된다. 현재 source authority와 문서별 권한을 확인하고 지원되는 등록 절차에서 받은 버전·publication receipt를 연결한 뒤, 서버의 기존 조회 검사로 검증해야 한다. 과거 자료는 뒤늦게 수집한 재구성본이며 당시 운영 스냅샷으로 표시하지 않는다.

서버에서 보이는 시점은 대상 회원 확인·문서 권한 근거·내부 결속 검증을 완료하고, 승인된 코드 반영/데이터 반입/배포/공통·회원 조회 검증을 마친 뒤다. 기존 결과 재사용은 새 AI 생성이나 다음 09:20/17:30 회차를 기다릴 필요가 없다. 이 준비 명령만으로 공개하거나 배포하지 않는다.

## 로컬 수집 기본값과 실제 사용 권한 구분

`private_intake.py`의 `USE`는 모든 비공개 시험 수집 기록에 `rights=unconfirmed`, `publicUse=false`, `modelSend=false`를 일괄 기록한다. `private_retained.describe_record`도 별도의 비공개 처리 경로를 위해 비활성·unknown grant를 만든다. 이 값은 **수집기 기본값이며 출처의 명시적 이용 금지 결정이 아니다**. 반대로 공개 표시 허가를 증명하는 값도 아니다. robots 조회 성공이나 사용자 시험 승인을 출처의 서비스 표시 허가로 간주하지 않는다.

해당 준비본이 이 경로에서 나왔는지 다음 명령으로 확인할 수 있다.

```sh
python3 scripts/audit_briefing_retained_rights.py \
  --bundle /private/output/new-bundle \
  --units-file /private/source/native/corpus-v2/units.json \
  --output /private/output/new-rights-audit.json
```

도구는 manifest에 고정된 수집 기록·문서 버전·본문 SHA와 원래 PLAN 해시를 대조하고, 현재 수집기의 기본값 선언 위치·해시를 남긴다. 기본값과 다르거나 출처·본문·해시가 바뀐 자료는 정상 기본값으로 처리하지 않는다. 출력은 0600이며 기존 감사 파일을 덮어쓰지 않는다. 원문·grant·DB를 변경하거나 승인본을 생성하지 않는다. 기록에 없는 출처의 이용 조건은 `not_recorded`로 구분해 확인해야 한다.

저장된 브리핑 조회와 새 AI 실행은 다음처럼 분리한다.

| 용도 | 필요한 operation | 필요한 purpose |
| --- | --- | --- |
| 기존 공통·개인화 브리핑 및 후보 조회 | read, quote-display | briefing-outlook |
| 새 AI 생성·독립 검증 | read, store, model-send, quote-display | briefing-outlook, semantic-verification |

조회에서 새 저장·모델 전송·검증 권한을 추가로 요구하지 않는다. 다만 현재 grant의 `known`·활성 상태·권한 근거·source/revision·수신자·만료 검사와 기사 공개 상태, 정확 인용·고정 그래프 검사는 유지한다. unknown/denied/비활성 grant는 조회용으로 자동 승격하지 않으며, 수집 기록의 false를 true로 바꾸지 않는다. 기존 승인 범위에 읽기·인용 표시만 있더라도 새 모델 호출은 계속 거부된다. 문서 분석·모델 worker의 기존 전체 권한 검사는 변경하지 않는다.
