# 브리핑 회차 지도: 원본과 재구성

발행본이 기록한 `graphVersion`과 회차 마감 시각으로 핵심 이슈·실제 관련 기업을 조회한다. 원본 버전이 없는 과거 로컬 재현 회차에는 별도 재구성 아티팩트를 만들 수 있다. 원래 발행 payload, public_snapshot, graph_version_id와 현재 공개 그래프 포인터는 변경하지 않는다.

## 조회 의미

`GET /api/v1/briefings/{id}/graph`의 `graphOrigin=publication_snapshot`은 원래 저장본, `reconstructed`는 나중에 저장 자료로 구성한 그래프다. `reconstructedAt`은 재구성 파일의 최초 등록 시각이며 브리핑 발행 시각이나 자료 마감 시각이 아니다. 재구성 사용 시 원래 브리핑의 graphVersion이 NULL인 것은 그대로다. 지도 응답의 `metadata.source=briefing_reconstructed_graph`와 banner의 재구성 표시를 함께 유지한다.

마감 이전 발행시각이 확인된 원문, 정확 인용과 버전, 발행본의 기업 연결만 사용한다. 추가 AI 생성·외부 검색·새 공급 관계 추정은 없다. 사건 시각·역할·국내/국제 분류가 저장되지 않았으면 그대로 미확정이다. 재구성 전용 reader만 미분류 geography=null을 허용하며 일반 공개 그래프 포맷의 검증을 완화하지 않는다. 구조 관계는 당시 basis 없이 INVOLVES로 바꿔 끼우지 않고 재구성을 거절한다.

원래 문안·인용은 회차 이슈 상세 API에서 읽는다. 이슈를 누르면 지도 전용 원문 복사나 최신 event 응답 대신 해당 회차의 상세·근거를 연다. 원래 metadata.graphVersion은 재구성 버전으로 바꾸지 않는다.

## 명시적 로컬 실행

일반 서버에서 자동 생성하지 않는다. `local` profile, loopback의 이름에 `briefing_replay`가 있는 별도 DB, non-web 모드, 기존 검증된 재현 manifest·권한·문서 아티팩트가 필요하다. 기존 실행 인자에 다음을 명시한다.

```text
--spring.main.web-application-type=none
--zoop.briefing.replay.read-enabled=true
--zoop.briefing.graph-reconstruction.enabled=true
--zoop.graph.snapshot.source=artifact
--zoop.graph.snapshot.artifact-root=<별도 그래프 파일 루트>
```

문서 아티팩트 루트(`zoop.document-read.artifact-root`)와 그래프 루트는 서로 다를 수 있다. 프로그램은 published·graphVersion NULL·replay marker가 있는 회차만 읽고 현재 권한·원래 문안/상세 검증 후 생성한다. 생성 CLI는 종료하며 일반 조회 서버에서 같은 그래프 루트와 재현 권한 설정으로 읽는다. 운영 배포·활성 공개 버전 생성 수단이 아니다.

## 보존·실패 경계

아티팩트 ID는 정책 버전·round ID·원래 payload와 public_snapshot의 정규화 SHA에 결속한다. 기존 artifacts 레지스트리의 graph_snapshot 종류로 별도 등록하고 graph_versions/graph_activations에는 넣지 않는다. 같은 입력의 재실행은 같은 파일·레지스트리 행을 재사용한다. 다른 회차의 graphVersion 사용은 422, round 없이 이 재구성 버전으로 직접 조회하는 것은 409다. 원문 권한 철회·파일 SHA/크기 불일치·현재 제외 목록·선정 대상 관계 누락은 실패로 닫고 원본/최신 그래프로 대체하지 않는다.

아무 저장본도 없는 회차는 snapshot_not_recorded 안내를 유지한다. 구조·DB migration·ERD 변경은 없다. 과거 본문이 당시와 동일했거나 당시 수집·공개 승인됐다고 주장하지 않는다.


## 모든 회차 소비자의 범위 (D-GRP-03/04/05)

공통 PublicGraphReader는 현재 제외·시각 필터 및 필수 대상 존재 검사 후, 선정 이슈와 그 연결 기업·관계·근거로 스냅샷을 제한한다. SHARES_ISSUE는 이 제한 이후 계산한다. 지도 노드만 줄여 놓고 기업·관계·사건 상세나 via에서 다른 이슈를 다시 확장하지 않는다.

관계·경로의 근거 창은 round를 보존한다. 원래 그래프는 회차 기준으로 선택한 버전의 실제 import receipt·인용 span·현재 S2-1 권한을 검증한다. 활성화가 자료 마감 이후여도 저장된 회차 결속으로 선택하며 round를 없애지 않는다. 재구성 그래프는 원래 회차 상세를 재검증한 정확 인용과 DB의 span을 사용하고, 원본 발행 graphVersion은 변경하지 않는다. 재구성에 가짜 import receipt나 관계 승인을 만들지 않는다.

원본 회차의 근거 범위에는 보이는 구조 basis의 기사 버전뿐 아니라, 회차에 남은 INVOLVES 관계가 직접 인용하는 기사 버전의 impact-only 후보 span도 유지한다. 구조 basis가 아직 검증되지 않은 마감 시각에도 영향 인용 후보가 사라지지 않도록 하되, 후보를 이슈·관계의 직접 근거 목록에 합치지는 않는다. 실제 근거 응답은 선택된 버전의 receipt에서 구조·영향 소속 증명을 모두 평가한 뒤 결정하며, 어느 한쪽의 잘못된 형태를 다른 쪽의 성공으로 우회하지 않는다. 영향 라벨·효과·제안과 S1 문서 요약은 공개 응답에 추가하지 않고 현재 권한·제외·정확한 span 검사를 그대로 적용한다. 재구성 회차는 이 handoff receipt 경로가 아니라 보존된 회차 상세의 별도 검증 경로를 유지한다.

기업 문서 요청도 round/version/asOf를 전달하며 개발 mock·최신 문서를 사용하지 않는다. 문서 cursor는 round까지 결속한다. 회차 조회에서는 이후 생성된 문서 분석을 덧붙이지 않는다. 시세·차트·지표는 별도 최신 관측 계약을 그대로 유지한다.

관계·기업·사건·문서·근거 metadata도 재구성 출처를 유지한다. 재구성 관계 verification은 not_applicable이며 미확인 role은 직접 역할을 확인했다는 표현으로 바꾸지 않는다. 배너 기업 수는 지도 전체 노드 수가 아니라 '브리핑에 기록된 기업' 수임을 명시한다.

과거 발행본의 evidence-grouped-* 등 저장 ID도 round 문맥에서만 선택된 스냅샷·상세·DB span과 일치하면 읽는다. 일반 비회차 근거 ID 검증을 완화하지 않는다.
