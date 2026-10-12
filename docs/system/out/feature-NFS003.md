# NFS003 · 작업 일관성과 복구

[전체 목록](index.md) · [검사 결과](warnings.md) · [범위 예외·상세 권한](detail-authority.md)

| 항목 | 원본/연결 |
| --- | --- |
| 원본 우선순위·상태 | P1 · 확정 |
| 원문 범위 분류 | existing |
| 유효 구현 범위 | 팀합의요구/설계대상 |
| 유효 기준 | user-2026-10-10-feedback · docs/share/day-work-2026-10-10.md |
| 완료·실행 경계 | 요구 범위 포함은 구현 완료·유료 실행 승인·본개발 채택이 아님 |
| 요구사항 번호(원문) | 56 |
| 의미 기준 요구사항 | 56 |
| API 대응 | 연결됨 |
| 사유 |  |
| 프로토타입 문서 판정 | 부분 |
| 코드 위치(실행 증거 아님) |  |

## 원본과 의미

[docs/evidence/raw/functional-spec_2026-10-12/00-명세-목차.csv:90 (xlsx-row)](../../../docs/evidence/raw/functional-spec_2026-10-12/00-명세-목차.csv)

- [docs/evidence/raw/functional-spec_2026-10-12/12-비기능-상세.csv:37 (xlsx-row)](../../../docs/evidence/raw/functional-spec_2026-10-12/12-비기능-상세.csv) — 작업 일관성과 복구: 관심 종목 등록, 계좌 연결, AI 답변 생성, 브리핑 생성 등 상태를 변경하거나 결과를 생성하는 요청에는 중복 실행 방지 기준을 적용해야 한다. 동일한 작업 식별자로 요청을 재전송한 경우 결과를 중복 생성하거나 상태를 중복 변경해서는 안 된다. 네트워크 또는 서버 오류 이후 재시도할 때 기존 작업의 처리 상태를 먼저 확인해야 한다.

## 상세 권한과 의미 이행

- 옛 FS046 AI 권한과 중복 작업 통제에서 이행됨(단일 신규 ID 없음 · 서버 공통 의무로 분산 보존). 보존: 로그인·대화 소유권·근거 접근 권한 재검증, 같은 작업 ID의 내용 불일치 거절, 같은 대화에 서로 다른 작업 ID가 동시에 와도 유효 실행 하나, 상태 조회·결과 회수는 신규 접수와 구분. 버튼 비활성화만으로 대체하지 않는다. 공통 규칙 aiJobs·idempotency와 NFS001/003이 서버 계약으로 유지한다.
- 옛 FS049 답변 검증과 제공에서 이행됨(다른 번호로 이동). 보존: 인용·원문 구간·그래프 참조 검증, 현재 유효 실행만 저장, 저장 후 완료, 검증 실패의 자동 재생성 금지, 보존 결과는 모델 재호출 없는 저장 복구.
- 옛 FS053 AI 결과 회수와 재시도에서 이행됨(병합·번호 이동). 보존: 상태 조회·결과 회수 먼저, 조회 장애를 미등록·실패로 단정하지 않음, 서버가 확정한 일시 장애만 같은 맥락으로 허용된 방식의 재시도, 검증 실패·권한 오류·결과 소실의 자동 재생성 금지.

문서 판정 출처: [docs/evidence/spec-v1.2-gap.md:297 (text-line)](../../../docs/evidence/spec-v1.2-gap.md). 기준선에 반영 현황의 마지막 행을 적용한 판정이며 번호가 재사용된 AI ID는 의미 이행표가 정한 곳에만 적용한다. 이번 생성기의 실행 검증은 아니다.

## WBS 편집 연결

| WBS | 역할 | 현재 업무 | 연결 근거 |
| --- | --- | --- | --- |
| 6.9.1 | BE | (BE) AI 질문 진입·맥락 전달 | 질문 진입·맥락 접수 시 옛 FS046의 회원 권한·대화 소유·근거 권한·작업 ID 멱등·동시 접수 통제를 공통 서버 의무(NFS001/003, aiJobs)로 함께 적용한다. 현 FS046은 질문 해석이다. |
| 6.9.7 | BE | (BE) 패널 상태 유지·결과 재조회 | 패널 상태 유지·결과 재조회는 AI v2 FS051 의미다. 원문 산출물은 10-10까지 옛 FS052-02+FS053이었고 10-12 공유 시트에서 FS051로 정정됐다. 복구 기준은 NFS003/009와 함께 본다. |
| 6.9.9 | BE | (BE) AI 결과 회수와 재시도 | 결과 회수·재시도는 AI v2 FS051의 결과 재조회 의미다. 원문 산출물은 10-10까지 옛 FS053이었고 10-12 공유 시트에서 FS051로 정정됐다. |
| 6.9.13 | FE | (FE) D-AI-02 AI 비동기 작업 상태·결과·재시도 API 연동 | 작업 상태·결과·재시도 UI는 검증된 답변(FS048)과 결과 재조회(FS051), 권한·중복 통제 공통 의무(NFS001/003, 옛 FS046)를 소비한다. |
| 6.9.14 | FE | (FE) D-AI-02b 대화 이력·후속 질문·답변 재조회 API 연동 | 대화 이력·후속 질문·재조회는 근거 탐색(FS049)·새 대화/후속 질문(FS050)·결과 재조회(FS051)·질문 기록(FS060)을 소비한다. |
| 6.9.15 | 공통/통합 | AI 챗봇 통합 테스트 | AI v2 FS045~051과 질문 기록, 권한·작업 일관성 공통 의무를 통합 시험 대상으로 연결한다. 원문 종료일이 시작일보다 앞서는 오류는 별도 경고로 보존한다. |

## 화면·목표 API

[D-AUT-02](screen-D-AUT-02.md) · [D-AUT-01](screen-D-AUT-01.md) · [M-GRP-01](screen-M-GRP-01.md) · [D-MY-01](screen-D-MY-01.md) · [D-GRP-T](screen-D-GRP-T.md) · [D-GRP-T2](screen-D-GRP-T2.md) · [D-GRP-T3](screen-D-GRP-T3.md) · [D-GRP-T4](screen-D-GRP-T4.md) · [D-GRP-T5](screen-D-GRP-T5.md) · [D-ONB-01](screen-D-ONB-01.md) · [D-ONB-02](screen-D-ONB-02.md) · [D-WAT-01](screen-D-WAT-01.md) · [D-WAT-01b](screen-D-WAT-01b.md) · [D-GRP-03](screen-D-GRP-03.md) · [D-STK-01](screen-D-STK-01.md) · [M-STK-01](screen-M-STK-01.md) · [D-AI-01](screen-D-AI-01.md) · [M-AI-01](screen-M-AI-01.md) · [D-AI-02b](screen-D-AI-02b.md) · [D-AI-01b](screen-D-AI-01b.md) · [D-AI-02](screen-D-AI-02.md) · [A-ADM-05c](screen-A-ADM-05c.md) · [A-ADM-01](screen-A-ADM-01.md) · [A-ADM-03](screen-A-ADM-03.md) · [A-ADM-04](screen-A-ADM-04.md) · [D-GRP-01](screen-D-GRP-01.md) · [D-BRF-01](screen-D-BRF-01.md) · [D-COM-02](screen-D-COM-02.md) · [A-ADM-05](screen-A-ADM-05.md)

| 도메인 | 연결 작업 수 | 작업 목록 |
| --- | --- | --- |
| auth | 5 | [전체 API 목록](../../api/out/zoop-api-spec.md#작업-목록) |
| me | 2 | [전체 API 목록](../../api/out/zoop-api-spec.md#작업-목록) |
| portfolio | 2 | [전체 API 목록](../../api/out/zoop-api-spec.md#작업-목록) |
| chat | 7 | [전체 API 목록](../../api/out/zoop-api-spec.md#작업-목록) |
| admin | 14 | [전체 API 목록](../../api/out/zoop-api-spec.md#작업-목록) |
| telemetry | 1 | [전체 API 목록](../../api/out/zoop-api-spec.md#작업-목록) |
| feedback | 1 | [전체 API 목록](../../api/out/zoop-api-spec.md#작업-목록) |

작업별 FS/NFS 역링크와 전체 연결은 API 명세서 및 xlsx 추적표에 보존한다.
