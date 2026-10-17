# 윤서진 할당 이슈 분류 — 2026-10-14

조회 계정은 `SJY051`, 저장소는 `Donbug/zoop`이다. 23개 이슈 모두 OPEN이며, 현재 전체 수용 기준을 충족해 닫을 수 있는 이슈는 확인하지 못했다. GitHub 상태·담당·일정은 변경하지 않았다. `main c3d0344`와 로컬 문서 등록·평가 도구 변경까지 대조했다. 이슈 본문은 10/12 동결 WBS를 바탕으로 생성됐으므로 최신 공유 시트의 09–18 운영·야간 복구·브리핑 09:20/17:30 조건도 함께 적용해야 한다.

‘이미 한 것’은 아래 각 행의 완료 부분이며 이슈 전체 완료와 다르다. authored replay는 호출·저장·검증 경로의 시험이지 실모델 품질의 증거가 아니다. 후순위는 범위 제외나 일정 연장을 뜻하지 않는다.

## 전체 분류

| 이슈 / WBS | 원래 일정 | 분류 | 이미 한 부분 / 남은 일 |
|---|---|---|---|
| [#52](https://github.com/Donbug/zoop/issues/52) / 6.5.1 | 10/7–16 | 다음 연결 | 관계·인용 후보와 S3 검증·HTTP 있음. 앱 evidence·공개 GraphDB 연결 남음 |
| [#53](https://github.com/Donbug/zoop/issues/53) / 6.5.2 | 10/7–14 | 지금 / 부분 구현 | 로컬 Spring 문서·불변 버전 등록과 PostgreSQL 검증 완료. 사건/기업 연결·목표 조회 API까지 완료 아님 |
| [#54](https://github.com/Donbug/zoop/issues/54) / 6.5.3 | 10/13–16 | 담당 연계 우선 | S1 outlook 보존. 홍정현 브리핑 저장 브랜치와 분석 재료 계약을 연결하고 중복 테이블 생성 금지. 원문 FS057 의미 추적 필요 |
| [#55](https://github.com/Donbug/zoop/issues/55) / 6.5.4 | 10/7–21 | 부분 구현 / 운영 후속 | 오프라인 단계·HTTP·복구 있음. 실공급원·05/35 수집·운영 구간·야간 미처리 자료 처리 남음. #72–79와 중복 공수 계산 금지 |
| [#56](https://github.com/Donbug/zoop/issues/56) / 6.5.5 | 10/16–23 | 다음 연결 | AI 결과 전달 gate 있음. Spring 결과 수입·공개 버전·GraphDB 반영 남음 |
| [#57](https://github.com/Donbug/zoop/issues/57) / 6.5.6 | 10/7–16 | 외부 선행 확인 | 공급원 이용권리·인증·지원 범위 확인 필요. 합성 replay를 실제 시장·뉴스 연동으로 취급하지 않음 |
| [#58](https://github.com/Donbug/zoop/issues/58) / 6.5.7 | 10/16–23 | 지금 | S1 Java client와 S2/S3 HTTP 완료. S2/S3 Java 소비·앱 작업 결속·수입 남음. 다음 구현 대상 |
| [#59](https://github.com/Donbug/zoop/issues/59) / 6.5.8 | 10/16–23 | 통합 후속 | 내부 통합 시험 있음. 실공급원·앱·운영 E2E는 #52–58 연결 후 검증 |
| [#72](https://github.com/Donbug/zoop/issues/72) / 6.6.13 | 9/21–10/15 | 부분 구현 / 운영 후속 | 오프라인 회차·raw·checkpoint·재개 있음. 실수집·정기 운영·앱 연계 남음 |
| [#73](https://github.com/Donbug/zoop/issues/73) / 6.6.14 | 9/21–10/15 | 지금 / 부분 구현 | 정제·중복·버전·원문 좌표와 로컬 앱 등록 완료. 실자료 정책·사건 참조·공개 조회 남음 |
| [#74](https://github.com/Donbug/zoop/issues/74) / 6.6.15 | 9/21–10/15 | 부분 구현 | S2 사건·주제 후보·HTTP·복구 있음. live 추출 품질·앱 후보 등록 남음 |
| [#75](https://github.com/Donbug/zoop/issues/75) / 6.6.16 | 9/21–10/15 | 부분 구현 / 다음 연결 | SAME/HOLD·오병합 방지 시험 있음. 병합된 기업 master와 canonical ID 연결 남음 |
| [#76](https://github.com/Donbug/zoop/issues/76) / 6.6.17 | 9/21–10/15 | 부분 구현 | 관계·방향·경로·근거 replay와 S3 HTTP 있음. 실제 품질·공통 관계키·GraphDB 연결 남음 |
| [#77](https://github.com/Donbug/zoop/issues/77) / 6.6.18 | 9/21–10/15 | 부분 구현 | 영향 후보·독립 검증·HOLD 검수/재검증 HTTP 있음. 실제 품질·앱 공개 제외·출력 연결 남음 |
| [#78](https://github.com/Donbug/zoop/issues/78) / 6.6.19 | 9/21–10/15 | 선행 계약 후속 | 실제 GraphDB upsert·두 조회 준비·공개 전환 미구현. 정세빈 조회·저장 경계와 공동 연결; 담당을 임의 재배정하지 않음 |
| [#79](https://github.com/Donbug/zoop/issues/79) / 6.6.20 | 9/21–10/15 | 부분 구현 / GraphDB 후속 | S4 영향 대상 조회와 중복 없는 저장/실행 복구 있음. 실제 철회·비활성화·공개 차단은 남음 |
| [#83](https://github.com/Donbug/zoop/issues/83) / 6.6.27 | 10/19–20 | 후순위 공동 검증 | 공개 그래프·기업 상세·버전·권한 연결 후 정세빈·김도현과 전체 흐름 검증 |
| [#142](https://github.com/Donbug/zoop/issues/142) / 6.10.16 | 10/12–16 | 가까운 마감 / API 선행 | AI측 검수·재처리 있음. 본개발 관리자 화면·앱 관리자 인증/API 연결 남음. 가짜 성공 UI로 대체하지 않음 |
| [#145](https://github.com/Donbug/zoop/issues/145) / 6.10.19 | 10/22–24 | 후순위 공동 검증 | 서비스 principal 권한 시험과 앱 관리자 권한 E2E는 다름. 앱 인증·운영 기능 후 검증 |
| [#146](https://github.com/Donbug/zoop/issues/146) / 6.11.1 | 10/12–20 | 지금 / 지속 점검 | 생성 계약·drift·source revision 점검 수행. 모든 목표 API 구현 완료는 아니며 변경 때 계속 점검 |
| [#149](https://github.com/Donbug/zoop/issues/149) / 6.11.4 | 10/12–27 | 병행 / 부분 검증 | 로컬 문서 등록·근거/버전·S2→S3 시험 및 benchmark 채점 기반 있음. 실제 GraphDB·공개 데이터 정합성 남음 |
| [#152](https://github.com/Donbug/zoop/issues/152) / 6.11.7 | 10/25–28 | 후순위 최종 회귀 | 지금 발견한 결함은 즉시 고침. 전체 제품 결함 수정·회귀 단계 완료로 계산하지 않음 |
| [#154](https://github.com/Donbug/zoop/issues/154) / 6.11.9 | 10/26–28 | 후순위 | 기존 프로토타입 설명 자료 있음. 본개발 실제 실행 기준 최종 시연·발표본은 추후 |

## 현재 증거와 다음 작업

- 원격 반영된 AI 실행·HTTP: [service 안내](../../ai/service/README.md), [AI 계약](../design/ai-system.md). 이전 마감 검증은 서비스 461개·pipeline HTTP 96개와 실제 S2→S3 smoke, 원격 CI 통과다.
- 현재 로컬 문서 등록: [DOCUMENT_IMPORT](../../api/docs/DOCUMENT_IMPORT.md). Java 157개·pipeline 229개, 실제 Spring+PostgreSQL 17.11의 16단계 검사 및 SQL 제약 검증 통과. 새 팀 기업 migration 이후 순서와 재실행은 이번 후속에서 확인한다.
- 로컬 평가 도구: [benchmark](../design/ai-benchmark.md), [CLI](../../ai/evaluation/README.md). 88개 테스트·실제 CLI 통과, 측정된 모델 성능 0건. 경쟁 비교·KPI 요구는 추가 평가 작업이며 기존 이슈를 자동 완료시키지 않는다.

다음 구현은 #58의 S2/S3 Spring 소비다. 회사 테이블은 main에 들어왔지만, 회사 존재만으로 문서와 회사의 연관 권위가 생기지 않는다. summary의 회사 문맥과 ERD의 company_id=NULL 대응, 현재 grant의 model-send/purpose/recipient, 분석 원본·검증·영수증 수입 계약을 정리하지 않고 전체 AI 결과 import를 서둘러 만들지 않는다. 현재 문서 migration은 아직 공유하지 않은 파일이므로 새 main migration 뒤로 버전을 조정한 뒤 빈 DB/업그레이드 경로를 검증한다.

## 분류 뒤 진행한 작업

- **#58의 Java 전송 계층:** S2 `ExtractionClient`와 S3 `RelationClient`를 추가했다. 승인 입력 digest, 원천 버전/revision, 검수 operation ID를 구분하고, 응답의 작업·입력·operation 결속과 보류 결과를 검사한다. 실제 Java→HTTP→설치된 pipeline을 연결한 13개 사례와 기존 S1 연결 9개 사례가 통과했다. 앱 DB 결과 수입·사용자 권한·공개 API는 아직 남아 있어 #58 전체는 닫지 않는다.
- **#53/#73의 migration 통합:** 아직 공유하지 않은 문서 migration을 `V20261014120000`으로 옮겨 최신 팀 migration `V20261014102810` 뒤에 적용되도록 했다. PostgreSQL에서 팀 버전까지 먼저 적용한 뒤 문서 등록을 실행한 17단계 검사와 제약 SQL이 통과했다. 기존 공유 migration은 수정하지 않았다.
- **회귀 근거:** 최종 Java 기본 테스트 187개(실패·건너뜀 0), 실제 Java S2/S3 연결 13개와 앞서 확인한 S1 연결 9개, 문서 등록 36회 실행·문서 3개/버전 5개/artifact 5개. 외부 모델 호출은 없었다. 생성물 275개 차이 없음·하드 오류 0·문서 시스템 테스트 21개 통과. 이 기록은 로컬 작업 트리에 대한 것이며 이번 변경의 커밋·푸시·원격 CI는 하지 않았다.

위 표와 검증 수치는 각 단계의 확인 시점 기록이다. 아래 최신 완료 범위를 우선하며, 하위 구현 완료를 전체 이슈 종료로 해석하지 않는다.

## 오늘 마무리한 범위 — 앱 문서 분석 저장까지

| 관련 이슈 | 완료한 하위 작업 | 아직 남은 수용 기준 |
|---|---|---|
| #53·#73 | 문서·불변 버전의 앱 등록, 현재 저장 권한 확인, 명시적 버전 포인터 CAS, 팀 migration 이후 업그레이드 검증 | 사건·기업의 운영 정규 ID 연결과 공개 조회·실자료 정책 |
| #58 | S1/S2/S3 Java 전송 계층과 운영자용 S1 요약·기업 판정의 앱 작업 결속 | 웹·관리자 인증/작업 API, S2/S3 후보의 앱 저장, 실제 모델 품질 |
| #56 | `prepare`에서 AI jobId·불변 submit을 먼저 저장하고 `advance`에서 검증된 요약·판정·근거·호출 기록을 PostgreSQL에 원자 수입 | GraphDB upsert·공개 버전·화면 조회와 전체 철회 |
| #146 | 새 Java 전송·분석 저장 계약, 현재 grant·원천·검증 claims 결속과 생성물 검증 | 모든 목표 API의 구현·공개 계약 통합 |
| #149 | 실제 문서→분석→검증→앱 저장·캐시·응답 유실·중단 복구와 평가 도구 기반 검증 | 운영 자료·GraphDB·실모델·공개 읽기 경로 검증 |

최신 실행 근거: Java **301개** 테스트 통과(실패·건너뜀 0), 실제 Spring jar→AI HTTP→worker→PostgreSQL 17.11의 **28단계·65회 JVM 실행** 통과. 분석 16건, 호출 기록 27건이 worker 호출 원장 27건과 일치하고 근거 10건을 저장했다. 의미 검증이 보지 않은 주장으로 결과를 바꾸면 보류하고, prepare 이후 권리 철회 시 새 전송을 거부하며, DB 행 잠금 대기 중 철회·만료된 권리는 내용 저장 직전에 다시 검사해 영수증만 보존했다. 캐시 수입·저장 재시도는 사용량을 중복 집계하지 않았다. SQL 제약 검증도 통과했다.

이 증거는 합성 replay와 로컬 PostgreSQL에 대한 것이며 외부 모델 호출은 0건이다. 검증용 DB 컨테이너는 정리했다. 현재 작업은 미커밋이며 GitHub 이슈·공유 WBS·원격 CI는 이번에 변경하지 않았다. **전체 이슈를 닫을 수 있다고 새로 판정한 항목은 0개**다. 대신 위 완료 하위 작업은 인계·리뷰 대상으로 준비됐다.

다음 구현은 공개 읽기 권한·회사 문맥을 갖춘 결과 조회 또는 S2/S3 후보의 앱 작업 저장이며, GraphDB 담당과 참조/공개 버전 경계를 맞춰 선정한다. 운영자용 저장이 사용자 공개를 자동 허가하지 않는다. 오늘 당장 실수집·실모델·GraphDB·화면 전체를 완료시키는 일정으로 확대하지 않는다.

## 2026-10-15 추가 — 공개 `getEvidence` 부분 구현

| 관련 이슈 | 이번에 완료한 하위 작업 | 아직 남은 수용 기준 |
|---|---|---|
| #52 | 저장된 S1 요약 인용 한 건을 읽는 실제 `GET /api/v1/evidence/{id}`(Spring·PostgreSQL). 현재 문서 상태와 현재 grant registry를 요청마다 다시 판정, 캐시로 돌려준 요약은 exact receipt 한 건 읽기 전용 증명 | GraphDB 사건 연결(`eventIds`는 실패 구역), 고정 `round`·`graphVersion`·`asOf` 읽기(409) |
| #53 | 위 읽기가 등록된 문서·불변 버전·`access_status`·현재 버전 규칙을 응답 때마다 적용 | `listCompanyDocuments`, 사건·기업 연결, 실자료 정책 |
| #56 | 수입된 근거·요약 결과를 공개 경로로 읽는 첫 한 건(`documentSummary`는 최신 요청이 available일 때만, 옛 요약 대체 없음) | GraphDB upsert·공개 버전·승인·전체 철회, 기업 판정(`sentiment`는 항상 `null`) |
| #146 | 목표 OpenAPI의 `getEvidence`를 Java로 구현(필드 추가 없음, `EVIDENCE_UNAVAILABLE`·`VERSION_UNAVAILABLE` 오류 코드) | 나머지 모든 목표 API |
| #149 | 실제 Spring HTTP→PostgreSQL 17 읽기 smoke: 저장된 evidence 10건 전부(캐시 적중 포함), GET 294건, grant·registry·옛 버전·최신 pending·캐시 증명 불량·hash·권한·운영자 잠금 | 실제 GraphDB·운영 자료·실모델·화면 E2E |

실행 근거(로컬 작업 트리·미커밋, Main 실행): Java **341개** 통과(실패·건너뜀 0)와 `assemble`, 실제 Spring jar→PostgreSQL 17의 smoke **41단계**. GET은 DB·파일·AI·모델에 쓰지 않았고 provider·모델 호출은 0이다. 규칙·한계는 [문서 분석 § 근거 읽기](../../api/docs/DOCUMENT_ANALYSIS.md#근거-읽기-getevidence-부분-구현). 이 날 **전체 이슈를 닫을 수 있다고 판정한 항목은 0개**이며 GitHub 이슈·공유 WBS·원격 CI·커밋·푸시는 변경하지 않았다. `listCompanyDocuments`·공개 읽기용 GraphDB 연결·기업 판정 문맥은 여전히 없다(S3의 비공개 Neo4j stage는 아래 추가 절).

## 2026-10-15 추가 — 비공개 Neo4j version projection (#78·#79 일부, 이슈는 닫지 않음)

| 관련 이슈 | 이번에 완료한 하위 작업 | 아직 남은 수용 기준 |
|---|---|---|
| #78 / 6.6.19 | 완료된 S3 job 하나를 서버 소유 canonical 결정으로 **비공개** 불변 Neo4j 5 version 하나로 stage하는 `zoop-ai-graph`(`init/freeze/project/recover/inspect/read/focus`). 다섯 관계 유형, version마다 별도 노드·간선(version 사이 공유·삭제 없음), explicit 단일 transaction, unknown commit의 전체 그래프 복구, 매 read의 현재 gate와 전체 그래프 digest 검증, 읽기 전용 깊이 1–3 focus. 상세는 [AI 실행 계약](../design/ai-system.md#s3--비공개-neo4j-버전-projection-fs080-일부게시fs081-철회-아님) | 공개 version 전환과 두 조회 경로 readiness(FS059), 앱 `graph_versions`/`graph_db_state` 등록, Spring 연동, 영향 라벨 projection, 운영 Neo4j 위상·인증·TLS. **활성 공개 상태는 없고** 출력 `publication`은 항상 `not-published`다 |
| #79 / 6.6.20 | 기존 S4 영향 대상 조회는 그대로이고, 저장된 Neo4j version은 현재 gate가 닫히면 `read`/`focus`가 내용 없이 withheld한다 | 실제 철회·비활성화·purge(물리 삭제 없음), graph 원장의 `zoop-ai-dependents` 스캔 포함, 공개 차단은 전부 남음. FS081은 부분 상태 그대로다 |

실행 근거(로컬 작업 트리·미커밋, Main 실행. 원격 CI·커밋·푸시 없음): `ai/pipeline` 시험 전체 **265개** 통과. 실제 Neo4j 5.26 Community(격리된 `--rm` tmpfs 임시 컨테이너, 종료·정리 완료)에서 독립 검토 R1–R4 회귀 **11개**는 수정 전 모두 RED로 재현됐고 수정 뒤 모두 통과했다. 새 빈 database의 정상 smoke는 다섯 관계 유형 전부, 노드 6·간선 6의 `v1`, 노드를 공유하지 않는 `v2`와 `v1` 원본 바이트 불변, 깊이 1·2·3 focus, 반복 `init` 멱등, 권한 철회 withheld, unknown commit·SIGKILL 뒤 rollback·변조 fail-closed를 모두 통과했다. provider·모델 호출은 0이고 원천 원장은 읽기 전용이었다. 직접 의존성 `neo4j==6.3.1`은 lock 검사와 실제 sync를 통과했고 `make pipeline-graph-smoke`를 추가했다. 공개 계약 생성물 275개 차이 없음·하드 오류 0·문서 시스템 시험 21개 통과, 병합된 인증 작업 트리의 Java는 시험 374개 실행에 실패 0·건너뜀 9, build 성공이다(건너뜀 9를 포함하므로 374개 통과로 세지 않는다).

이 검증은 기능에 한정된다. **성능·지연·부하는 측정하지 않았고** 실제 provider·모델·운영 Neo4j는 쓰지 않았다. 이 날 **전체 이슈를 닫을 수 있다고 판정한 항목은 0개**이며 GitHub 이슈·공유 WBS·원격 CI·커밋·푸시는 변경하지 않았다.
