# A-ADM-05 · 회원·접근 관리

[전체 목록](index.md) · [검사 결과](warnings.md)

- 라우트: `/admin/members`
- 화면계획서 캡처 쪽수: **68**
- 원본: [docs/screen-plan/captures/slide-index.json:68 (slide-page)](../../../docs/screen-plan/captures/slide-index.json)

| 기능 | 목표 API | 경로 | 우선순위 |
| --- | --- | --- | --- |
| [FS069-01](feature-FS069-01.md) | [listMembers](../../api/out/zoop-api-spec.md#listmembers) | GET /api/v1/admin/members | P2 |
| [FS069-01](feature-FS069-01.md) | [getMemberActivity](../../api/out/zoop-api-spec.md#getmemberactivity) | GET /api/v1/admin/members/{member_id} | P2 |
| [FS069-02](feature-FS069-02.md) | [blockMember](../../api/out/zoop-api-spec.md#blockmember) | POST /api/v1/admin/members/{member_id}/block | P2 |
| [FS069-02](feature-FS069-02.md) | [unblockMember](../../api/out/zoop-api-spec.md#unblockmember) | POST /api/v1/admin/members/{member_id}/unblock | P2 |

공통 품질: [NFS001](feature-NFS001.md) · [NFS002](feature-NFS002.md) · [NFS004](feature-NFS004.md) · [NFS008](feature-NFS008.md) · [NFS003](feature-NFS003.md) · [NFS009](feature-NFS009.md)
