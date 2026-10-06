# NFS003 · 작업 일관성과 복구

[전체 목록](index.md) · [검사 결과](warnings.md)

| 항목 | 원본/연결 |
| --- | --- |
| 우선순위·상태 | P1 · 확정 |
| 요구사항 번호 | 56 |
| API 대응 | 연결됨 |
| 사유 |  |
| 프로토타입 문서 판정 | 부분 |
| 코드 위치(실행 증거 아님) |  |

## 원본과 의미

[docs/evidence/raw/functional-spec_2026-10-06/00-명세-목차.csv:94 (xlsx-row)](../../../docs/evidence/raw/functional-spec_2026-10-06/00-명세-목차.csv)

- [docs/evidence/raw/functional-spec_2026-10-06/12-비기능-상세.csv:37 (xlsx-row)](../../../docs/evidence/raw/functional-spec_2026-10-06/12-비기능-상세.csv) — 작업 일관성과 복구: 관심 종목 등록, 계좌 연결, AI 답변 생성, 브리핑 생성 등 상태를 변경하거나 결과를 생성하는 요청에는 중복 실행 방지 기준을 적용해야 한다. 동일한 작업 식별자로 요청을 재전송한 경우 결과를 중복 생성하거나 상태를 중복 변경해서는 안 된다. 네트워크 또는 서버 오류 이후 재시도할 때 기존 작업의 처리 상태를 먼저 확인해야 한다.

문서 판정 출처: [docs/evidence/spec-v1.2-gap.md:283 (text-line)](../../../docs/evidence/spec-v1.2-gap.md). 기준선에 반영 현황의 마지막 행을 적용한 판정이며 이번 생성기의 실행 검증은 아니다.

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
