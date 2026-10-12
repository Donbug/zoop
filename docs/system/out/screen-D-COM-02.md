# D-COM-02 · 사건 타임라인·문서 탭

[전체 목록](index.md) · [검사 결과](warnings.md)

- 라우트: `/companies/KRX%3A005930?asOf=2026-10-07T18%3A59%3A09.207Z&tab=documents`
- 화면계획서 캡처 쪽수: **40**
- 원본: [docs/screen-plan/captures/slide-index.json:40 (slide-page)](../../../docs/screen-plan/captures/slide-index.json)

| 기능 | 목표 API | 경로 | 우선순위 |
| --- | --- | --- | --- |
| [FS021](feature-FS021.md) · [FS043](feature-FS043.md) · [FS056](feature-FS056.md) · [FS063](feature-FS063.md) · [FS064](feature-FS064.md) | [listCompanyDocuments](../../api/out/zoop-api-spec.md#listcompanydocuments) | GET /api/v1/companies/{id}/documents | P1 |
| [FS040](feature-FS040.md) · [FS041](feature-FS041.md) · [FS056](feature-FS056.md) · [FS055](feature-FS055.md) | [listEvents](../../api/out/zoop-api-spec.md#listevents) | GET /api/v1/events | P1 |
| [FS021](feature-FS021.md) · [FS041](feature-FS041.md) · [FS056](feature-FS056.md) | [getEvent](../../api/out/zoop-api-spec.md#getevent) | GET /api/v1/events/{id} | P1 |
| [FS024](feature-FS024.md) · [FS043](feature-FS043.md) · [FS049](feature-FS049.md) · [FS055](feature-FS055.md) | [getEvidence](../../api/out/zoop-api-spec.md#getevidence) | GET /api/v1/evidence/{id} | P1 |
| [FS066-01](feature-FS066-01.md) | [getMyFeedback](../../api/out/zoop-api-spec.md#getmyfeedback) | GET /api/v1/feedback | P2 |
| [FS066-01](feature-FS066-01.md) | [setFeedback](../../api/out/zoop-api-spec.md#setfeedback) | PUT /api/v1/feedback | P2 |
| [FS038](feature-FS038.md) · [FS040](feature-FS040.md) · [FS041](feature-FS041.md) · [FS042](feature-FS042.md) · [FS055](feature-FS055.md) | [getCompanyGraphAsOf](../../api/out/zoop-api-spec.md#getcompanygraphasof) | GET /api/v1/companies/{id}/graph | P1 |

공통 품질: [NFS001](feature-NFS001.md) · [NFS002](feature-NFS002.md) · [NFS004](feature-NFS004.md) · [NFS008](feature-NFS008.md) · [NFS005](feature-NFS005.md) · [NFS006](feature-NFS006.md) · [NFS003](feature-NFS003.md) · [NFS009](feature-NFS009.md)
