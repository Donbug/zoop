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
