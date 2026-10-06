# D-COM-04 · 기업 중심 관계 그래프

[전체 목록](index.md) · [검사 결과](warnings.md)

- 라우트: `/companies/KRX%3A005930?period=1m&asOf=2026-09-30T23%3A59%3A59%2B09%3A00&tab=events`
- 화면계획서 캡처 쪽수: **42**
- 원본: [docs/screen-plan/captures/slide-index.json:42 (slide-page)](../../../docs/screen-plan/captures/slide-index.json)

| 기능 | 목표 API | 경로 | 우선순위 |
| --- | --- | --- | --- |
| [FS014](feature-FS014.md) · [FS017](feature-FS017.md) · [FS018](feature-FS018.md) · [FS019](feature-FS019.md) · [FS026](feature-FS026.md) · [FS032](feature-FS032.md) · [FS040](feature-FS040.md) · [FS044](feature-FS044.md) · [FS055](feature-FS055.md) | [getGraph](../../api/out/zoop-api-spec.md#getgraph) | GET /api/v1/graph | P1 |
| [FS020](feature-FS020.md) · [FS038](feature-FS038.md) · [FS044](feature-FS044.md) | [getCompany](../../api/out/zoop-api-spec.md#getcompany) | GET /api/v1/companies/{id} | P1 |
| [FS038](feature-FS038.md) · [FS040](feature-FS040.md) · [FS041](feature-FS041.md) · [FS055](feature-FS055.md) | [getCompanyGraphAsOf](../../api/out/zoop-api-spec.md#getcompanygraphasof) | GET /api/v1/companies/{id}/graph | P1 |

공통 품질: [NFS001](feature-NFS001.md) · [NFS002](feature-NFS002.md) · [NFS004](feature-NFS004.md) · [NFS008](feature-NFS008.md) · [NFS005](feature-NFS005.md)

화면 구현 요구: [FS044](feature-FS044.md)
