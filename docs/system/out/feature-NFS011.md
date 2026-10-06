# NFS011 · 웹 접근성

[전체 목록](index.md) · [검사 결과](warnings.md)

| 항목 | 원본/연결 |
| --- | --- |
| 우선순위·상태 | P2 · 추가 제안 · 검토 전 |
| 요구사항 번호 | 64 |
| API 대응 | API 불필요 |
| 사유 | 키보드·스크린리더·대비 등 화면 접근성은 화면 구현과 점검표의 책임이다. |
| 프로토타입 문서 판정 | 부분 |
| 코드 위치(실행 증거 아님) |  |

## 원본과 의미

[docs/evidence/raw/functional-spec_2026-10-06/00-명세-목차.csv:102 (xlsx-row)](../../../docs/evidence/raw/functional-spec_2026-10-06/00-명세-목차.csv)

- [docs/evidence/raw/functional-spec_2026-10-06/12-비기능-상세.csv:149 (xlsx-row)](../../../docs/evidence/raw/functional-spec_2026-10-06/12-비기능-상세.csv) — 웹 접근성: 현재 초점 위치가 시각적으로 표시되어야 하며, 색상만으로 긍정·부정·오류 상태를 구분해서는 안 된다. 버튼, 링크, 차트 및 상태 메시지에는 스크린리더가 인식할 수 있는 대체 이름과 설명을 제공해야 한다.

문서 판정 출처: [docs/evidence/spec-v1.2-gap.md:291 (text-line)](../../../docs/evidence/spec-v1.2-gap.md). 기준선에 반영 현황의 마지막 행을 적용한 판정이며 이번 생성기의 실행 검증은 아니다.

## 화면·목표 API

[STATE-01](screen-STATE-01.md) · [M-RULE-01](screen-M-RULE-01.md)

| 작업 | 메서드·목표 경로 | WBS | 권한 |
| --- | --- | --- | --- |
