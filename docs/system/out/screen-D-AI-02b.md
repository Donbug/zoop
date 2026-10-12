# D-AI-02b · AI 대화 조회 오류·다시 확인

[전체 목록](index.md) · [검사 결과](warnings.md)

- 라우트: `/?mode=all&select=node%3AKRX%3A005930`
- 화면계획서 캡처 쪽수: **52**
- 원본: [docs/screen-plan/captures/slide-index.json:52 (slide-page)](../../../docs/screen-plan/captures/slide-index.json)

| 기능 | 목표 API | 경로 | 우선순위 |
| --- | --- | --- | --- |
| [FS050](feature-FS050.md) · [FS051](feature-FS051.md) · [FS060](feature-FS060.md) | [getConversation](../../api/out/zoop-api-spec.md#getconversation) | GET /api/v1/chat/sessions/{id} | P1 |
| [FS051](feature-FS051.md) · [FS060](feature-FS060.md) | [getCurrentConversation](../../api/out/zoop-api-spec.md#getcurrentconversation) | GET /api/v1/chat/sessions/current | P1 |

공통 품질: [NFS001](feature-NFS001.md) · [NFS002](feature-NFS002.md) · [NFS004](feature-NFS004.md) · [NFS008](feature-NFS008.md) · [NFS003](feature-NFS003.md) · [NFS009](feature-NFS009.md) · [NFS005](feature-NFS005.md) · [NFS006](feature-NFS006.md)
