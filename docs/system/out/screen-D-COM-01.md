# D-COM-01 · 기업 상세·시세·모의 보유

[전체 목록](index.md) · [검사 결과](warnings.md)

- 라우트: `/companies/KRX%3A005930?asOf=2026-10-06T03%3A41%3A18.068Z`
- 화면계획서 캡처 쪽수: **38**
- 원본: [docs/screen-plan/captures/slide-index.json:38 (slide-page)](../../../docs/screen-plan/captures/slide-index.json)

| 기능 | 목표 API | 경로 | 우선순위 |
| --- | --- | --- | --- |
| [FS039](feature-FS039.md) · [FS054](feature-FS054.md) | [getMyPortfolio](../../api/out/zoop-api-spec.md#getmyportfolio) | GET /api/v1/portfolio | P1 |
| [FS011-01](feature-FS011-01.md) · [FS026](feature-FS026.md) · [FS037](feature-FS037.md) | [searchCompanies](../../api/out/zoop-api-spec.md#searchcompanies) | GET /api/v1/companies | P1 |
| [FS020](feature-FS020.md) · [FS038](feature-FS038.md) · [FS044](feature-FS044.md) | [getCompany](../../api/out/zoop-api-spec.md#getcompany) | GET /api/v1/companies/{id} | P1 |
| [FS020](feature-FS020.md) · [FS038](feature-FS038.md) · [FS063](feature-FS063.md) | [getCompanyQuote](../../api/out/zoop-api-spec.md#getcompanyquote) | GET /api/v1/companies/{id}/quote | P1 |
| [FS020](feature-FS020.md) · [FS042](feature-FS042.md) | [getCompanyMetrics](../../api/out/zoop-api-spec.md#getcompanymetrics) | GET /api/v1/companies/{id}/metrics | P1 |
| [FS042](feature-FS042.md) | [getCompanyFinancials](../../api/out/zoop-api-spec.md#getcompanyfinancials) | GET /api/v1/companies/{id}/financials | P1 |

공통 품질: [NFS001](feature-NFS001.md) · [NFS002](feature-NFS002.md) · [NFS004](feature-NFS004.md) · [NFS008](feature-NFS008.md) · [NFS005](feature-NFS005.md)
