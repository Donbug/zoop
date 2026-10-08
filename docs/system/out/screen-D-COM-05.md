# D-COM-05 · 타임라인 버킷·차트·그래프 연동

[전체 목록](index.md) · [검사 결과](warnings.md)

- 라우트: `/companies/KRX%3A005930?period=1m&asOf=2026-09-30T23%3A59%3A59%2B09%3A00&tab=events`
- 화면계획서 캡처 쪽수: **43**
- 원본: [docs/screen-plan/captures/slide-index.json:43 (slide-page)](../../../docs/screen-plan/captures/slide-index.json)

| 기능 | 목표 API | 경로 | 우선순위 |
| --- | --- | --- | --- |
| [FS038](feature-FS038.md) · [FS040](feature-FS040.md) | [getCompanyPrices](../../api/out/zoop-api-spec.md#getcompanyprices) | GET /api/v1/companies/{id}/prices | P1 |
| [FS040](feature-FS040.md) · [FS041](feature-FS041.md) · [FS056](feature-FS056.md) | [listEvents](../../api/out/zoop-api-spec.md#listevents) | GET /api/v1/events | P1 |
| [FS021](feature-FS021.md) · [FS041](feature-FS041.md) · [FS056](feature-FS056.md) | [getEvent](../../api/out/zoop-api-spec.md#getevent) | GET /api/v1/events/{id} | P1 |
| [FS038](feature-FS038.md) · [FS040](feature-FS040.md) · [FS041](feature-FS041.md) · [FS042](feature-FS042.md) · [FS055](feature-FS055.md) | [getCompanyGraphAsOf](../../api/out/zoop-api-spec.md#getcompanygraphasof) | GET /api/v1/companies/{id}/graph | P1 |

공통 품질: [NFS001](feature-NFS001.md) · [NFS002](feature-NFS002.md) · [NFS004](feature-NFS004.md) · [NFS008](feature-NFS008.md) · [NFS005](feature-NFS005.md)

화면 구현 요구: [FS044](feature-FS044.md)
