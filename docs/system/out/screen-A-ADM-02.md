# A-ADM-02 · 통계·AI 품질

[전체 목록](index.md) · [검사 결과](warnings.md)

- 라우트: `/admin/stats`
- 화면계획서 캡처 쪽수: **63**
- 원본: [docs/screen-plan/captures/slide-index.json:63 (slide-page)](../../../docs/screen-plan/captures/slide-index.json)

| 기능 | 목표 API | 경로 | 우선순위 |
| --- | --- | --- | --- |
| [FS065](feature-FS065.md) | [getInsightsOverview](../../api/out/zoop-api-spec.md#getinsightsoverview) | GET /api/v1/admin/insights/overview | P2 |
| [FS065](feature-FS065.md) | [getInsightsSummary](../../api/out/zoop-api-spec.md#getinsightssummary) | GET /api/v1/admin/insights/summary | P2 |
| [FS065](feature-FS065.md) | [listCompanyInsights](../../api/out/zoop-api-spec.md#listcompanyinsights) | GET /api/v1/admin/insights/companies | P2 |
| [FS065](feature-FS065.md) | [getCompanyInsights](../../api/out/zoop-api-spec.md#getcompanyinsights) | GET /api/v1/admin/insights/companies/{company_id} | P2 |

공통 품질: [NFS001](feature-NFS001.md) · [NFS002](feature-NFS002.md) · [NFS004](feature-NFS004.md) · [NFS008](feature-NFS008.md)
