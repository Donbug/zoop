# A-ADM-04 · AI·브리핑 운영

[전체 목록](index.md) · [검사 결과](warnings.md)

- 라우트: `/admin/briefings`
- 화면계획서 캡처 쪽수: **66**
- 원본: [docs/screen-plan/captures/slide-index.json:66 (slide-page)](../../../docs/screen-plan/captures/slide-index.json)

| 기능 | 목표 API | 경로 | 우선순위 |
| --- | --- | --- | --- |
| [FS070-01](feature-FS070-01.md) | [listAdminBriefingRounds](../../api/out/zoop-api-spec.md#listadminbriefingrounds) | GET /api/v1/admin/briefings | P1 |
| [FS070-01](feature-FS070-01.md) | [getAdminBriefingRound](../../api/out/zoop-api-spec.md#getadminbriefinground) | GET /api/v1/admin/briefings/{round_id} | P1 |
| [FS028](feature-FS028.md) · [FS029](feature-FS029.md) · [FS034](feature-FS034.md) · [FS070-02](feature-FS070-02.md) | [reprocessBriefingRound](../../api/out/zoop-api-spec.md#reprocessbriefinground) | POST /api/v1/admin/briefings/{round_id}/reprocess | P1 |
| [FS035](feature-FS035.md) · [FS071-01](feature-FS071-01.md) | [appendBriefingCorrection](../../api/out/zoop-api-spec.md#appendbriefingcorrection) | POST /api/v1/admin/briefings/{round_id}/corrections | P1 |
| [FS071-02](feature-FS071-02.md) | [setBriefingSuspension](../../api/out/zoop-api-spec.md#setbriefingsuspension) | POST /api/v1/admin/briefings/{round_id}/suspension | P1 |

공통 품질: [NFS001](feature-NFS001.md) · [NFS002](feature-NFS002.md) · [NFS004](feature-NFS004.md) · [NFS008](feature-NFS008.md) · [NFS003](feature-NFS003.md) · [NFS009](feature-NFS009.md)
