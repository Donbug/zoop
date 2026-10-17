# D-MY-01 · 내 종목 관리

[전체 목록](index.md) · [검사 결과](warnings.md)

- 라우트: `/me/stocks`
- 화면계획서 캡처 쪽수: **45**
- 원본: [docs/screen-plan/captures/slide-index.json:45 (slide-page)](../../../docs/screen-plan/captures/slide-index.json)

| 기능 | 목표 API | 경로 | 우선순위 |
| --- | --- | --- | --- |
| [FS007](feature-FS007.md) | [logOut](../../api/out/zoop-api-spec.md#logout) | POST /api/v1/auth/logout | P1 |
| [FS008](feature-FS008.md) · [FS012](feature-FS012.md) · [FS013](feature-FS013.md) · [FS054](feature-FS054.md) | [getMySettings](../../api/out/zoop-api-spec.md#getmysettings) | GET /api/v1/me/settings | P1 |
| [FS027](feature-FS027.md) | [setWatchlistCompany](../../api/out/zoop-api-spec.md#setwatchlistcompany) | PUT /api/v1/me/watchlist/{id} | P1 |
| [FS009](feature-FS009.md) · [FS062](feature-FS062.md) · [FS010](feature-FS010.md) · [FS039](feature-FS039.md) · [FS054](feature-FS054.md) | [getMyPortfolio](../../api/out/zoop-api-spec.md#getmyportfolio) | GET /api/v1/portfolio | P1 |
| [FS009](feature-FS009.md) · [FS062](feature-FS062.md) | [disconnectVirtualAccount](../../api/out/zoop-api-spec.md#disconnectvirtualaccount) | DELETE /api/v1/portfolio/connections/{id} | P1 |
| [FS011-01](feature-FS011-01.md) · [FS026](feature-FS026.md) · [FS037](feature-FS037.md) | [searchCompanies](../../api/out/zoop-api-spec.md#searchcompanies) | GET /api/v1/companies | P1 |

공통 품질: [NFS001](feature-NFS001.md) · [NFS002](feature-NFS002.md) · [NFS004](feature-NFS004.md) · [NFS008](feature-NFS008.md) · [NFS003](feature-NFS003.md) · [NFS009](feature-NFS009.md)
