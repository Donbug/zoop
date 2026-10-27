# NFS009 · 중단 작업 복구

[전체 목록](index.md) · [검사 결과](warnings.md) · [범위 예외·상세 권한](detail-authority.md)

| 항목 | 원본/연결 |
| --- | --- |
| 원본 우선순위·상태 | P1 · 추가 제안 · 검토 전 |
| 원문 범위 분류 | existing |
| 유효 구현 범위 | 팀합의요구/설계대상 |
| 유효 기준 | user-2026-10-10-feedback · docs/share/day-work-2026-10-10.md |
| 완료·실행 경계 | 요구 범위 포함은 구현 완료·유료 실행 승인·본개발 채택이 아님 |
| 요구사항 번호(원문) | 62 |
| 의미 기준 요구사항 | 62 |
| API 대응 | 연결됨 |
| 사유 |  |
| 프로토타입 문서 판정 | 부분 |
| 코드 위치(실행 증거 아님) |  |

## 원본과 의미

[docs/evidence/raw/functional-spec_2026-10-18/00-명세-목차.csv:96 (xlsx-row)](../../../docs/evidence/raw/functional-spec_2026-10-18/00-명세-목차.csv)

- [docs/evidence/raw/functional-spec_2026-10-18/12-비기능-상세.csv:121 (xlsx-row)](../../../docs/evidence/raw/functional-spec_2026-10-18/12-비기능-상세.csv) — 중단 작업 복구: 작업이 중단되면 기존 작업 상태를 확인한 뒤 허용된 복구만 수행해야 한다. 복구로 AI 답변이나 브리핑이 중복 생성·발행되어서는 안 된다. 복구할 수 없으면 실패 사유와 가능한 다음 조치를 안내하며, 재실행이 금지된 작업에 재실행을 안내하지 않는다.

## 상세 권한과 의미 이행

- 옛 FS053 AI 결과 회수와 재시도에서 이행됨(병합·번호 이동). 보존: 상태 조회·결과 회수 먼저, 조회 장애를 미등록·실패로 단정하지 않음, 서버가 확정한 일시 장애만 같은 맥락으로 허용된 방식의 재시도, 검증 실패·권한 오류·결과 소실의 자동 재생성 금지.

문서 판정 출처: [docs/evidence/spec-v1.2-gap.md:303 (text-line)](../../../docs/evidence/spec-v1.2-gap.md). 기준선에 반영 현황의 마지막 행을 적용한 판정이며 번호가 재사용된 AI ID는 의미 이행표가 정한 곳에만 적용한다. 이번 생성기의 실행 검증은 아니다.

## WBS 편집 연결

| WBS | 역할 | 현재 업무 | 연결 근거 |
| --- | --- | --- | --- |
| 6.9.7 | BE | (BE) 패널 상태 유지·결과 재조회 | 패널 상태 유지·결과 재조회는 AI v2 FS051 의미다. 원문 산출물은 10-10까지 옛 FS052-02+FS053이었고 10-12 공유 시트에서 FS051로 정정됐다. 복구 기준은 NFS003/009와 함께 본다. |
| 6.9.9 | BE | (BE) AI 결과 회수와 재시도 | 결과 회수·재시도는 AI v2 FS051의 결과 재조회 의미다. 원문 산출물은 10-10까지 옛 FS053이었고 10-12 공유 시트에서 FS051로 정정됐다. |

## 화면·목표 API

[D-AUT-02](screen-D-AUT-02.md) · [D-AUT-01](screen-D-AUT-01.md) · [M-GRP-01](screen-M-GRP-01.md) · [D-MY-01](screen-D-MY-01.md) · [D-GRP-T](screen-D-GRP-T.md) · [D-GRP-T2](screen-D-GRP-T2.md) · [D-GRP-T3](screen-D-GRP-T3.md) · [D-GRP-T4](screen-D-GRP-T4.md) · [D-GRP-T5](screen-D-GRP-T5.md) · [D-ONB-01](screen-D-ONB-01.md) · [D-ONB-02](screen-D-ONB-02.md) · [D-WAT-01](screen-D-WAT-01.md) · [D-WAT-01b](screen-D-WAT-01b.md) · [D-GRP-03](screen-D-GRP-03.md) · [D-STK-01](screen-D-STK-01.md) · [M-STK-01](screen-M-STK-01.md) · [D-AI-02](screen-D-AI-02.md) · [D-AI-01](screen-D-AI-01.md) · [M-AI-01](screen-M-AI-01.md) · [D-AI-02b](screen-D-AI-02b.md) · [D-AI-01b](screen-D-AI-01b.md) · [A-ADM-05c](screen-A-ADM-05c.md) · [A-ADM-01](screen-A-ADM-01.md) · [A-ADM-03](screen-A-ADM-03.md) · [A-ADM-04](screen-A-ADM-04.md) · [D-GRP-01](screen-D-GRP-01.md) · [D-BRF-01](screen-D-BRF-01.md) · [D-COM-02](screen-D-COM-02.md) · [A-ADM-05](screen-A-ADM-05.md)

| 도메인 | 연결 작업 수 | 작업 목록 |
| --- | --- | --- |
| auth | 5 | [전체 API 목록](../../api/out/zoop-api-spec.md#작업-목록) |
| me | 2 | [전체 API 목록](../../api/out/zoop-api-spec.md#작업-목록) |
| portfolio | 2 | [전체 API 목록](../../api/out/zoop-api-spec.md#작업-목록) |
| chat | 9 | [전체 API 목록](../../api/out/zoop-api-spec.md#작업-목록) |
| admin | 14 | [전체 API 목록](../../api/out/zoop-api-spec.md#작업-목록) |
| telemetry | 1 | [전체 API 목록](../../api/out/zoop-api-spec.md#작업-목록) |
| feedback | 1 | [전체 API 목록](../../api/out/zoop-api-spec.md#작업-목록) |

작업별 FS/NFS 역링크와 전체 연결은 API 명세서 및 xlsx 추적표에 보존한다.
