# A-ADM-02b · 선호도·대화록

[전체 목록](index.md) · [검사 결과](warnings.md)

- 라우트: `/admin/feedback`
- 화면계획서 캡처 쪽수: **64**
- 원본: [docs/screen-plan/captures/slide-index.json:64 (slide-page)](../../../docs/screen-plan/captures/slide-index.json)

| 기능 | 목표 API | 경로 | 우선순위 |
| --- | --- | --- | --- |
| [FS066-02](feature-FS066-02.md) | [getFeedbackSummary](../../api/out/zoop-api-spec.md#getfeedbacksummary) | GET /api/v1/admin/feedback/summary | P2 |
| [FS066-02](feature-FS066-02.md) | [listDislikedResults](../../api/out/zoop-api-spec.md#listdislikedresults) | GET /api/v1/admin/feedback/dislikes | P2 |
| [FS066-03](feature-FS066-03.md) | [listMaskedTranscripts](../../api/out/zoop-api-spec.md#listmaskedtranscripts) | GET /api/v1/admin/transcripts | P2 |
| [FS066-03](feature-FS066-03.md) | [getMaskedTranscript](../../api/out/zoop-api-spec.md#getmaskedtranscript) | GET /api/v1/admin/transcripts/{session_id} | P2 |

공통 품질: [NFS001](feature-NFS001.md) · [NFS002](feature-NFS002.md) · [NFS004](feature-NFS004.md) · [NFS008](feature-NFS008.md)
