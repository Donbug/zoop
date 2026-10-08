# D-GRP-03 · 기업 패널·시세·1개월 추이

[전체 목록](index.md) · [검사 결과](warnings.md)

- 라우트: `/?mode=all&select=node%3AKRX%3A005930`
- 화면계획서 캡처 쪽수: **31**
- 원본: [docs/screen-plan/captures/slide-index.json:31 (slide-page)](../../../docs/screen-plan/captures/slide-index.json)

| 기능 | 목표 API | 경로 | 우선순위 |
| --- | --- | --- | --- |
| [FS027](feature-FS027.md) | [setWatchlistCompany](../../api/out/zoop-api-spec.md#setwatchlistcompany) | PUT /api/v1/me/watchlist/{id} | P1 |
| [FS020](feature-FS020.md) · [FS038](feature-FS038.md) · [FS044](feature-FS044.md) | [getCompany](../../api/out/zoop-api-spec.md#getcompany) | GET /api/v1/companies/{id} | P1 |
| [FS020](feature-FS020.md) · [FS038](feature-FS038.md) · [FS063](feature-FS063.md) | [getCompanyQuote](../../api/out/zoop-api-spec.md#getcompanyquote) | GET /api/v1/companies/{id}/quote | P1 |
| [FS020](feature-FS020.md) · [FS038](feature-FS038.md) | [getCompanyMetrics](../../api/out/zoop-api-spec.md#getcompanymetrics) | GET /api/v1/companies/{id}/metrics | P1 |

공통 품질: [NFS001](feature-NFS001.md) · [NFS002](feature-NFS002.md) · [NFS004](feature-NFS004.md) · [NFS008](feature-NFS008.md) · [NFS003](feature-NFS003.md) · [NFS009](feature-NFS009.md)
