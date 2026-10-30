# D-BRF-02 · 퇴근 브리핑·회차 비교

[전체 목록](index.md) · [검사 결과](warnings.md)

- 라우트: `/briefing?date=2026-09-17&edition=evening`
- 화면계획서 캡처 쪽수: **47**
- 원본: [docs/screen-plan/captures/slide-index.json:47 (slide-page)](../../../docs/screen-plan/captures/slide-index.json)

| 기능 | 목표 API | 경로 | 우선순위 |
| --- | --- | --- | --- |
| [FS028](feature-FS028.md) · [FS029](feature-FS029.md) · [FS030](feature-FS030.md) · [FS031](feature-FS031.md) · [FS033](feature-FS033.md) · [FS034](feature-FS034.md) · [FS035](feature-FS035.md) | [getBriefing](../../api/out/zoop-api-spec.md#getbriefing) | GET /api/v1/briefings | P1 |
| [FS033](feature-FS033.md) · [FS035](feature-FS035.md) | [listBriefingRounds](../../api/out/zoop-api-spec.md#listbriefingrounds) | GET /api/v1/briefings/rounds | P1 |
| [FS028](feature-FS028.md) · [FS029](feature-FS029.md) · [FS033](feature-FS033.md) · [FS035](feature-FS035.md) | [getBriefingRecap](../../api/out/zoop-api-spec.md#getbriefingrecap) | GET /api/v1/briefings/{id}/recap | P1 |
| [FS030](feature-FS030.md) · [FS033](feature-FS033.md) | [getBriefingItemImpacts](../../api/out/zoop-api-spec.md#getbriefingitemimpacts) | GET /api/v1/briefings/{roundId}/items/{eventId}/impacts | P1 |
| [FS030](feature-FS030.md) · [FS033](feature-FS033.md) | [getBriefingItemImpactReviews](../../api/out/zoop-api-spec.md#getbriefingitemimpactreviews) | GET /api/v1/briefings/{roundId}/items/{eventId}/impact-reviews | P1 |
| [FS030](feature-FS030.md) · [FS033](feature-FS033.md) · [FS035](feature-FS035.md) | [getBriefingItemDetail](../../api/out/zoop-api-spec.md#getbriefingitemdetail) | GET /api/v1/briefings/{roundId}/items/{eventId} | P1 |
| [FS036](feature-FS036.md) | [getPersonalizedBriefingIssues](../../api/out/zoop-api-spec.md#getpersonalizedbriefingissues) | GET /api/v1/briefings/{id}/personalized/issues | P2 |
| [FS036](feature-FS036.md) | [getPersonalizedBriefing](../../api/out/zoop-api-spec.md#getpersonalizedbriefing) | GET /api/v1/briefings/{id}/personalized | P2 |
| [FS036](feature-FS036.md) | [getBriefingPersonalizationOptions](../../api/out/zoop-api-spec.md#getbriefingpersonalizationoptions) | GET /api/v1/briefings/personalization/options | P2 |
| [FS036](feature-FS036.md) | [selectPersonalBriefingIssues](../../api/out/zoop-api-spec.md#selectpersonalbriefingissues) | POST /api/v1/briefings/{id}/personalized/selection | P2 |
| [FS036](feature-FS036.md) | [createPersonalBriefingGeneration](../../api/out/zoop-api-spec.md#createpersonalbriefinggeneration) | POST /api/v1/briefings/{id}/personalized/generations | P2 |
| [FS036](feature-FS036.md) | [getPersonalBriefingGeneration](../../api/out/zoop-api-spec.md#getpersonalbriefinggeneration) | GET /api/v1/briefings/{id}/personalized/generations/{jobId} | P2 |
| [FS036](feature-FS036.md) | [retryPersonalBriefingGeneration](../../api/out/zoop-api-spec.md#retrypersonalbriefinggeneration) | POST /api/v1/briefings/{id}/personalized/generations/{jobId}/retry | P2 |
| [FS036](feature-FS036.md) | [getPersonalBriefingSettings](../../api/out/zoop-api-spec.md#getpersonalbriefingsettings) | GET /api/v1/briefings/personalization/settings | P2 |
| [FS036](feature-FS036.md) | [savePersonalBriefingSettings](../../api/out/zoop-api-spec.md#savepersonalbriefingsettings) | PUT /api/v1/briefings/personalization/settings | P2 |
| [FS036](feature-FS036.md) | [initializePersonalBriefingSettings](../../api/out/zoop-api-spec.md#initializepersonalbriefingsettings) | POST /api/v1/briefings/personalization/settings/initialize | P2 |
| [FS036](feature-FS036.md) | [getPersonalBriefingDelivery](../../api/out/zoop-api-spec.md#getpersonalbriefingdelivery) | GET /api/v1/briefings/{id}/personalized/delivery | P2 |
| [FS036](feature-FS036.md) | [createPersonalBriefingDemo](../../api/out/zoop-api-spec.md#createpersonalbriefingdemo) | POST /api/v1/briefings/{id}/personalized/demo | P2 |

공통 품질: [NFS001](feature-NFS001.md) · [NFS002](feature-NFS002.md) · [NFS004](feature-NFS004.md) · [NFS008](feature-NFS008.md) · [NFS005](feature-NFS005.md) · [NFS006](feature-NFS006.md)
