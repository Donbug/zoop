# D-AI-01 · AI 질문·대상 연결

[전체 목록](index.md) · [검사 결과](warnings.md)

- 라우트: `/?mode=all&select=node%3AKRX%3A005930`
- 화면계획서 캡처 쪽수: **49**
- 원본: [docs/screen-plan/captures/slide-index.json:49 (slide-page)](../../../docs/screen-plan/captures/slide-index.json)

| 기능 | 목표 API | 경로 | 우선순위 |
| --- | --- | --- | --- |
| [FS024](feature-FS024.md) · [FS043](feature-FS043.md) · [FS050-01](feature-FS050-01.md) · [FS055](feature-FS055.md) | [getEvidence](../../api/out/zoop-api-spec.md#getevidence) | GET /api/v1/evidence/{id} | P1 |
| [FS051](feature-FS051.md) · [FS060](feature-FS060.md) | [createConversation](../../api/out/zoop-api-spec.md#createconversation) | PUT /api/v1/chat/sessions/{id} | P1 |
| [FS052-01](feature-FS052-01.md) · [FS052-02](feature-FS052-02.md) · [FS060](feature-FS060.md) | [getConversation](../../api/out/zoop-api-spec.md#getconversation) | GET /api/v1/chat/sessions/{id} | P1 |
| [FS025](feature-FS025.md) · [FS045](feature-FS045.md) · [FS046](feature-FS046.md) · [FS047](feature-FS047.md) · [FS048](feature-FS048.md) · [FS049](feature-FS049.md) · [FS050-02](feature-FS050-02.md) · [FS052-01](feature-FS052-01.md) · [FS060](feature-FS060.md) · [FS064](feature-FS064.md) | [submitQuestion](../../api/out/zoop-api-spec.md#submitquestion) | POST /api/v1/chat/sessions/{id}/jobs | P1 |
| [FS066-01](feature-FS066-01.md) | [getMyFeedback](../../api/out/zoop-api-spec.md#getmyfeedback) | GET /api/v1/feedback | P2 |
| [FS066-01](feature-FS066-01.md) | [setFeedback](../../api/out/zoop-api-spec.md#setfeedback) | PUT /api/v1/feedback | P2 |

공통 품질: [NFS001](feature-NFS001.md) · [NFS002](feature-NFS002.md) · [NFS004](feature-NFS004.md) · [NFS008](feature-NFS008.md) · [NFS003](feature-NFS003.md) · [NFS009](feature-NFS009.md) · [NFS005](feature-NFS005.md) · [NFS006](feature-NFS006.md)
