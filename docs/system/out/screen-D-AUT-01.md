# D-AUT-01 · 시작·이메일 로그인

[전체 목록](index.md) · [검사 결과](warnings.md)

- 라우트: `/login`
- 화면계획서 캡처 쪽수: **16**
- 원본: [docs/screen-plan/captures/slide-index.json:16 (slide-page)](../../../docs/screen-plan/captures/slide-index.json)

| 기능 | 목표 API | 경로 | 우선순위 |
| --- | --- | --- | --- |
| [FS001](feature-FS001.md) · [FS006](feature-FS006.md) | [getMemberSession](../../api/out/zoop-api-spec.md#getmembersession) | GET /api/v1/auth/session | P1 |
| [FS002](feature-FS002.md) · [FS006](feature-FS006.md) | [logIn](../../api/out/zoop-api-spec.md#login) | POST /api/v1/auth/login | P1 |
| [FS005](feature-FS005.md) | [startGuestSession](../../api/out/zoop-api-spec.md#startguestsession) | POST /api/v1/auth/guest | P1 |
| [FS004](feature-FS004.md) · [FS061](feature-FS061.md) | [listSocialProviders](../../api/out/zoop-api-spec.md#listsocialproviders) | GET /api/v1/auth/social/providers | P1 |
| [FS004](feature-FS004.md) · [FS061](feature-FS061.md) | [authorizeSocialLogin](../../api/out/zoop-api-spec.md#authorizesociallogin) | GET /api/v1/auth/social/{provider}/authorize | P1 |
| [FS004](feature-FS004.md) · [FS061](feature-FS061.md) | [completeSocialLogin](../../api/out/zoop-api-spec.md#completesociallogin) | GET /api/v1/auth/social/{provider}/callback | P1 |

공통 품질: [NFS001](feature-NFS001.md) · [NFS002](feature-NFS002.md) · [NFS004](feature-NFS004.md) · [NFS008](feature-NFS008.md) · [NFS003](feature-NFS003.md) · [NFS009](feature-NFS009.md)
