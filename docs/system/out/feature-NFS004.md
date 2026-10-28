# NFS004 · 부분 실패 내성

[전체 목록](index.md) · [검사 결과](warnings.md) · [범위 예외·상세 권한](detail-authority.md)

| 항목 | 원본/연결 |
| --- | --- |
| 원본 우선순위·상태 | P1 · 팀 검토 전 |
| 원문 범위 분류 | existing |
| 유효 구현 범위 | 팀합의요구/설계대상 |
| 유효 기준 | user-2026-10-10-feedback · docs/share/day-work-2026-10-10.md |
| 완료·실행 경계 | 요구 범위 포함은 구현 완료·유료 실행 승인·본개발 채택이 아님 |
| 요구사항 번호(원문) | 57 |
| 의미 기준 요구사항 | 57 |
| API 대응 | 연결됨 |
| 사유 |  |
| 프로토타입 문서 판정 | 구현 |
| 코드 위치(실행 증거 아님) |  |

## 원본과 의미

[docs/evidence/raw/functional-spec_2026-10-18/00-명세-목차.csv:91 (xlsx-row)](../../../docs/evidence/raw/functional-spec_2026-10-18/00-명세-목차.csv)

- [docs/evidence/raw/functional-spec_2026-10-18/12-비기능-상세.csv:51 (xlsx-row)](../../../docs/evidence/raw/functional-spec_2026-10-18/12-비기능-상세.csv) — 부분 실패 내성: 기업 상세, 관계 그래프, 브리핑 등 여러 영역으로 구성된 화면에서 한 영역의 조회가 실패하더라도 정상적으로 조회된 다른 영역은 유지해야 한다. 실패 영역에는 오류 안내와 재시도 기능을 제공해야 하며, 재시도 시 해당 영역만 다시 조회해야 한다.

문서 판정 출처: [docs/evidence/spec-v1.2-gap.md:71 (text-line)](../../../docs/evidence/spec-v1.2-gap.md). 기준선에 반영 현황의 마지막 행을 적용한 판정이며 번호가 재사용된 AI ID는 의미 이행표가 정한 곳에만 적용한다. 이번 생성기의 실행 검증은 아니다.

## WBS 편집 연결

| WBS | 역할 | 현재 업무 | 연결 근거 |
| --- | --- | --- | --- |

## 화면·목표 API

[D-AUT-01](screen-D-AUT-01.md) · [D-ONB-01](screen-D-ONB-01.md) · [D-AUT-02](screen-D-AUT-02.md) · [M-GRP-01](screen-M-GRP-01.md) · [D-MY-01](screen-D-MY-01.md) · [D-GRP-T](screen-D-GRP-T.md) · [D-GRP-T2](screen-D-GRP-T2.md) · [D-GRP-T3](screen-D-GRP-T3.md) · [D-GRP-T4](screen-D-GRP-T4.md) · [D-GRP-T5](screen-D-GRP-T5.md) · [D-WAT-01](screen-D-WAT-01.md) · [D-ONB-02](screen-D-ONB-02.md) · [D-WAT-01b](screen-D-WAT-01b.md) · [D-GRP-03](screen-D-GRP-03.md) · [D-STK-01](screen-D-STK-01.md) · [M-STK-01](screen-M-STK-01.md) · [D-COM-01](screen-D-COM-01.md) · [M-COM-01](screen-M-COM-01.md) · [D-GRP-01](screen-D-GRP-01.md) · [D-GRP-01b](screen-D-GRP-01b.md) · [D-GRP-07](screen-D-GRP-07.md) · [D-GRP-07b](screen-D-GRP-07b.md) · [D-BRF-04](screen-D-BRF-04.md) · [D-COM-04](screen-D-COM-04.md) · [D-GRP-04](screen-D-GRP-04.md) · [D-COM-03](screen-D-COM-03.md) · [M-COM-02](screen-M-COM-02.md) · [D-COM-01b](screen-D-COM-01b.md) · [D-COM-05](screen-D-COM-05.md) · [D-COM-06](screen-D-COM-06.md) · [D-COM-02](screen-D-COM-02.md) · [D-SEN-01](screen-D-SEN-01.md) · [D-GRP-02](screen-D-GRP-02.md) · [D-GRP-05](screen-D-GRP-05.md) · [D-AI-01](screen-D-AI-01.md) · [D-BRF-01](screen-D-BRF-01.md) · [D-BRF-02](screen-D-BRF-02.md) · [M-BRF-01](screen-M-BRF-01.md) · [D-SEN-02](screen-D-SEN-02.md) · [D-AI-02](screen-D-AI-02.md) · [M-AI-01](screen-M-AI-01.md) · [D-AI-02b](screen-D-AI-02b.md) · [D-AI-01b](screen-D-AI-01b.md) · [A-ADM-05c](screen-A-ADM-05c.md) · [A-ADM-01](screen-A-ADM-01.md) · [A-ADM-05b](screen-A-ADM-05b.md) · [A-ADM-03](screen-A-ADM-03.md) · [A-ADM-04b](screen-A-ADM-04b.md) · [A-ADM-04](screen-A-ADM-04.md) · [A-ADM-02](screen-A-ADM-02.md) · [A-ADM-02b](screen-A-ADM-02b.md) · [A-ADM-05](screen-A-ADM-05.md) · [D-GRP-06](screen-D-GRP-06.md)

| 도메인 | 연결 작업 수 | 작업 목록 |
| --- | --- | --- |
| auth | 12 | [전체 API 목록](../../api/out/zoop-api-spec.md#작업-목록) |
| me | 4 | [전체 API 목록](../../api/out/zoop-api-spec.md#작업-목록) |
| portfolio | 5 | [전체 API 목록](../../api/out/zoop-api-spec.md#작업-목록) |
| graph | 2 | [전체 API 목록](../../api/out/zoop-api-spec.md#작업-목록) |
| companies | 9 | [전체 API 목록](../../api/out/zoop-api-spec.md#작업-목록) |
| events | 2 | [전체 API 목록](../../api/out/zoop-api-spec.md#작업-목록) |
| evidence | 1 | [전체 API 목록](../../api/out/zoop-api-spec.md#작업-목록) |
| briefings | 8 | [전체 API 목록](../../api/out/zoop-api-spec.md#작업-목록) |
| chat | 9 | [전체 API 목록](../../api/out/zoop-api-spec.md#작업-목록) |
| admin | 37 | [전체 API 목록](../../api/out/zoop-api-spec.md#작업-목록) |
| telemetry | 1 | [전체 API 목록](../../api/out/zoop-api-spec.md#작업-목록) |
| feedback | 2 | [전체 API 목록](../../api/out/zoop-api-spec.md#작업-목록) |

작업별 FS/NFS 역링크와 전체 연결은 API 명세서 및 xlsx 추적표에 보존한다.
