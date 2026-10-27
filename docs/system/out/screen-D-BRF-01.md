# D-BRF-01 · 출근 브리핑

[전체 목록](index.md) · [검사 결과](warnings.md)

- 라우트: `/briefing?date=2026-09-17&edition=morning`
- 화면계획서 캡처 쪽수: **46**
- 원본: [docs/screen-plan/captures/slide-index.json:46 (slide-page)](../../../docs/screen-plan/captures/slide-index.json)

| 기능 | 목표 API | 경로 | 우선순위 |
| --- | --- | --- | --- |
| [FS028](feature-FS028.md) · [FS029](feature-FS029.md) · [FS030](feature-FS030.md) · [FS031](feature-FS031.md) · [FS033](feature-FS033.md) · [FS034](feature-FS034.md) · [FS035](feature-FS035.md) | [getBriefing](../../api/out/zoop-api-spec.md#getbriefing) | GET /api/v1/briefings | P1 |
| [FS033](feature-FS033.md) · [FS035](feature-FS035.md) | [listBriefingRounds](../../api/out/zoop-api-spec.md#listbriefingrounds) | GET /api/v1/briefings/rounds | P1 |
| [FS028](feature-FS028.md) · [FS029](feature-FS029.md) · [FS033](feature-FS033.md) · [FS035](feature-FS035.md) | [getBriefingRecap](../../api/out/zoop-api-spec.md#getbriefingrecap) | GET /api/v1/briefings/{id}/recap | P1 |
| [FS030](feature-FS030.md) · [FS033](feature-FS033.md) | [getBriefingItemImpacts](../../api/out/zoop-api-spec.md#getbriefingitemimpacts) | GET /api/v1/briefings/{roundId}/items/{eventId}/impacts | P1 |
| [FS030](feature-FS030.md) · [FS033](feature-FS033.md) | [getBriefingItemImpactReviews](../../api/out/zoop-api-spec.md#getbriefingitemimpactreviews) | GET /api/v1/briefings/{roundId}/items/{eventId}/impact-reviews | P1 |
| [FS030](feature-FS030.md) · [FS033](feature-FS033.md) · [FS035](feature-FS035.md) | [getBriefingItemDetail](../../api/out/zoop-api-spec.md#getbriefingitemdetail) | GET /api/v1/briefings/{roundId}/items/{eventId} | P1 |
| [FS066-01](feature-FS066-01.md) | [getMyFeedback](../../api/out/zoop-api-spec.md#getmyfeedback) | GET /api/v1/feedback | P2 |
| [FS066-01](feature-FS066-01.md) | [setFeedback](../../api/out/zoop-api-spec.md#setfeedback) | PUT /api/v1/feedback | P2 |
| [FS036](feature-FS036.md) | [getPersonalizedBriefing](../../api/out/zoop-api-spec.md#getpersonalizedbriefing) | GET /api/v1/briefings/{id}/personalized | P2 |

공통 품질: [NFS001](feature-NFS001.md) · [NFS002](feature-NFS002.md) · [NFS004](feature-NFS004.md) · [NFS008](feature-NFS008.md) · [NFS005](feature-NFS005.md) · [NFS006](feature-NFS006.md) · [NFS003](feature-NFS003.md) · [NFS009](feature-NFS009.md)
