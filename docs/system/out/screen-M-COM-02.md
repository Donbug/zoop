# M-COM-02 · 모바일 기업 전환 시트

[전체 목록](index.md) · [검사 결과](warnings.md)

- 라우트: `/companies/KRX%3A005930?period=1m&asOf=2026-09-30T23%3A59%3A59%2B09%3A00&tab=events`
- 화면계획서 캡처 쪽수: **58**
- 원본: [docs/screen-plan/captures/slide-index.json:58 (slide-page)](../../../docs/screen-plan/captures/slide-index.json)

| 기능 | 목표 API | 경로 | 우선순위 |
| --- | --- | --- | --- |
| [FS011-01](feature-FS011-01.md) · [FS026](feature-FS026.md) · [FS037](feature-FS037.md) | [searchCompanies](../../api/out/zoop-api-spec.md#searchcompanies) | GET /api/v1/companies | P1 |
| [FS020](feature-FS020.md) · [FS038](feature-FS038.md) · [FS044](feature-FS044.md) | [getCompany](../../api/out/zoop-api-spec.md#getcompany) | GET /api/v1/companies/{id} | P1 |
| [FS020](feature-FS020.md) · [FS038](feature-FS038.md) · [FS063](feature-FS063.md) | [getCompanyQuote](../../api/out/zoop-api-spec.md#getcompanyquote) | GET /api/v1/companies/{id}/quote | P1 |

공통 품질: [NFS001](feature-NFS001.md) · [NFS002](feature-NFS002.md) · [NFS004](feature-NFS004.md) · [NFS008](feature-NFS008.md)

화면 구현 요구: [FS044](feature-FS044.md)
