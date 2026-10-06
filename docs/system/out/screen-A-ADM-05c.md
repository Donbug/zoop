# A-ADM-05c · 관리자 로그인

[전체 목록](index.md) · [검사 결과](warnings.md)

- 라우트: `/admin/login`
- 화면계획서 캡처 쪽수: **61**
- 원본: [docs/screen-plan/captures/slide-index.json:61 (slide-page)](../../../docs/screen-plan/captures/slide-index.json)

| 기능 | 목표 API | 경로 | 우선순위 |
| --- | --- | --- | --- |
| [FS073](feature-FS073.md) | [getAdminSession](../../api/out/zoop-api-spec.md#getadminsession) | GET /api/v1/admin/auth/session | P1 |
| [FS073](feature-FS073.md) | [logInAdmin](../../api/out/zoop-api-spec.md#loginadmin) | POST /api/v1/admin/auth/login | P1 |
| [FS073](feature-FS073.md) | [logOutAdmin](../../api/out/zoop-api-spec.md#logoutadmin) | POST /api/v1/admin/auth/logout | P1 |

공통 품질: [NFS001](feature-NFS001.md) · [NFS002](feature-NFS002.md) · [NFS004](feature-NFS004.md) · [NFS008](feature-NFS008.md) · [NFS003](feature-NFS003.md) · [NFS009](feature-NFS009.md)
