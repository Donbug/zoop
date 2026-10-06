# M-COM-01 · 기업 상세·문서 전환

[전체 목록](index.md) · [검사 결과](warnings.md)

- 라우트: `/companies/KRX%3A005930?asOf=2026-10-06T03%3A46%3A24.749Z`
- 화면계획서 캡처 쪽수: **57**
- 원본: [docs/screen-plan/captures/slide-index.json:57 (slide-page)](../../../docs/screen-plan/captures/slide-index.json)

| 기능 | 목표 API | 경로 | 우선순위 |
| --- | --- | --- | --- |
| [FS039](feature-FS039.md) · [FS054](feature-FS054.md) | [getMyPortfolio](../../api/out/zoop-api-spec.md#getmyportfolio) | GET /api/v1/portfolio | P1 |
| [FS011-01](feature-FS011-01.md) · [FS026](feature-FS026.md) · [FS037](feature-FS037.md) | [searchCompanies](../../api/out/zoop-api-spec.md#searchcompanies) | GET /api/v1/companies | P1 |
| [FS020](feature-FS020.md) · [FS038](feature-FS038.md) · [FS044](feature-FS044.md) | [getCompany](../../api/out/zoop-api-spec.md#getcompany) | GET /api/v1/companies/{id} | P1 |
| [FS020](feature-FS020.md) · [FS038](feature-FS038.md) · [FS063](feature-FS063.md) | [getCompanyQuote](../../api/out/zoop-api-spec.md#getcompanyquote) | GET /api/v1/companies/{id}/quote | P1 |
| [FS020](feature-FS020.md) · [FS042](feature-FS042.md) | [getCompanyMetrics](../../api/out/zoop-api-spec.md#getcompanymetrics) | GET /api/v1/companies/{id}/metrics | P1 |
| [FS038](feature-FS038.md) · [FS040](feature-FS040.md) | [getCompanyPrices](../../api/out/zoop-api-spec.md#getcompanyprices) | GET /api/v1/companies/{id}/prices | P1 |
| [FS021](feature-FS021.md) · [FS043](feature-FS043.md) · [FS056](feature-FS056.md) · [FS063](feature-FS063.md) · [FS064](feature-FS064.md) | [listCompanyDocuments](../../api/out/zoop-api-spec.md#listcompanydocuments) | GET /api/v1/companies/{id}/documents | P1 |
| [FS040](feature-FS040.md) · [FS041](feature-FS041.md) · [FS056](feature-FS056.md) | [listEvents](../../api/out/zoop-api-spec.md#listevents) | GET /api/v1/events | P1 |
| [FS042](feature-FS042.md) | [getCompanyFinancials](../../api/out/zoop-api-spec.md#getcompanyfinancials) | GET /api/v1/companies/{id}/financials | P1 |
| [FS038](feature-FS038.md) · [FS040](feature-FS040.md) · [FS041](feature-FS041.md) · [FS055](feature-FS055.md) | [getCompanyGraphAsOf](../../api/out/zoop-api-spec.md#getcompanygraphasof) | GET /api/v1/companies/{id}/graph | P1 |

공통 품질: [NFS001](feature-NFS001.md) · [NFS002](feature-NFS002.md) · [NFS004](feature-NFS004.md) · [NFS008](feature-NFS008.md) · [NFS005](feature-NFS005.md) · [NFS006](feature-NFS006.md)

화면 구현 요구: [NFS010](feature-NFS010.md)
