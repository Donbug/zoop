# D-COM-01b · 차트·시간 버킷·인과관계 고지

[전체 목록](index.md) · [검사 결과](warnings.md)

- 라우트: `/companies/KRX%3A005930?asOf=2026-10-06T03%3A41%3A18.068Z&tab=events`
- 화면계획서 캡처 쪽수: **39**
- 원본: [docs/screen-plan/captures/slide-index.json:39 (slide-page)](../../../docs/screen-plan/captures/slide-index.json)

| 기능 | 목표 API | 경로 | 우선순위 |
| --- | --- | --- | --- |
| [FS038](feature-FS038.md) · [FS040](feature-FS040.md) | [getCompanyPrices](../../api/out/zoop-api-spec.md#getcompanyprices) | GET /api/v1/companies/{id}/prices | P1 |
| [FS040](feature-FS040.md) · [FS041](feature-FS041.md) · [FS056](feature-FS056.md) | [listEvents](../../api/out/zoop-api-spec.md#listevents) | GET /api/v1/events | P1 |
| [FS038](feature-FS038.md) · [FS040](feature-FS040.md) · [FS041](feature-FS041.md) · [FS055](feature-FS055.md) | [getCompanyGraphAsOf](../../api/out/zoop-api-spec.md#getcompanygraphasof) | GET /api/v1/companies/{id}/graph | P1 |

공통 품질: [NFS001](feature-NFS001.md) · [NFS002](feature-NFS002.md) · [NFS004](feature-NFS004.md) · [NFS008](feature-NFS008.md) · [NFS005](feature-NFS005.md)
