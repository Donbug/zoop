# M-AI-01 · 하단 AI 탭

[전체 목록](index.md) · [검사 결과](warnings.md)

- 라우트: `/?mode=all`
- 화면계획서 캡처 쪽수: **56**
- 원본: [docs/screen-plan/captures/slide-index.json:56 (slide-page)](../../../docs/screen-plan/captures/slide-index.json)

| 기능 | 목표 API | 경로 | 우선순위 |
| --- | --- | --- | --- |
| [FS050](feature-FS050.md) · [FS060](feature-FS060.md) | [createConversation](../../api/out/zoop-api-spec.md#createconversation) | PUT /api/v1/chat/sessions/{id} | P1 |
| [FS050](feature-FS050.md) · [FS051](feature-FS051.md) · [FS060](feature-FS060.md) | [getConversation](../../api/out/zoop-api-spec.md#getconversation) | GET /api/v1/chat/sessions/{id} | P1 |
| [FS051](feature-FS051.md) · [FS060](feature-FS060.md) | [getCurrentConversation](../../api/out/zoop-api-spec.md#getcurrentconversation) | GET /api/v1/chat/sessions/current | P1 |
| [FS025](feature-FS025.md) · [FS045](feature-FS045.md) · [FS046](feature-FS046.md) · [FS047](feature-FS047.md) · [FS048](feature-FS048.md) · [FS049](feature-FS049.md) · [FS050](feature-FS050.md) · [FS051](feature-FS051.md) · [FS060](feature-FS060.md) · [FS064](feature-FS064.md) | [submitQuestion](../../api/out/zoop-api-spec.md#submitquestion) | POST /api/v1/chat/sessions/{id}/jobs | P1 |
| [FS048](feature-FS048.md) · [FS049](feature-FS049.md) · [FS051](feature-FS051.md) | [getQuestionJob](../../api/out/zoop-api-spec.md#getquestionjob) | GET /api/v1/chat/jobs/{job_id} | P1 |
| [FS051](feature-FS051.md) | [retryQuestionJob](../../api/out/zoop-api-spec.md#retryquestionjob) | POST /api/v1/chat/jobs/{job_id}/retry | P1 |
| [FS051](feature-FS051.md) | [cancelQuestionJob](../../api/out/zoop-api-spec.md#cancelquestionjob) | POST /api/v1/chat/jobs/{job_id}/cancel | P1 |

공통 품질: [NFS001](feature-NFS001.md) · [NFS002](feature-NFS002.md) · [NFS004](feature-NFS004.md) · [NFS008](feature-NFS008.md) · [NFS003](feature-NFS003.md) · [NFS009](feature-NFS009.md) · [NFS005](feature-NFS005.md) · [NFS006](feature-NFS006.md)
