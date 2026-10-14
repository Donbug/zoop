# Zoop 공개용 약관

돈벌래 팀이 2026년 10월 13일 17:00 KST에 승인한 정책과 후속 확정 사항을 반영했다. 두 문서의 버전은 `2026-10-13.1`, 시행 시각은 **2026년 10월 13일 17:00 KST**다. 가입 시 두 항목을 필수로 확인·동의받는다.

| 약관 ID | 공개 본문 | DB |
| --- | --- | --- |
| `service` | [서비스 이용약관](approved/terms-of-service-2026-10-13.1.md) | `term_versions(service, 2026-10-13.1)` |
| `privacy` | [개인정보 처리방침](approved/privacy-policy-2026-10-13.1.md) | `term_versions(privacy, 2026-10-13.1)` |

본문은 [`V20261013040000__register_approved_term_versions.sql`](../../api/src/main/resources/db/migration/V20261013040000__register_approved_term_versions.sql)에 동일한 Markdown으로 고정한다. 이 migration이나 승인 문서를 적용 후 수정하지 않는다. 약관을 바꾸면 새 문서 버전과 Flyway migration을 만들고 이전 버전의 효력 종료 시각을 같은 트랜잭션에서 조정한다. 기존 [`drafts/`](drafts/README.md)는 작성·승인 이전 검토 자료로 남긴다.

공개 문서의 약속을 실제 배포가 지켜야 한다. 특히 만 14세 미만 가입 제한, 필수 동의 확인, 탈퇴 시 계정·대화·활동 기록·동의 이력 삭제, OpenAI 전송 항목과 AWS 서울 리전 사용을 배포 전에 확인한다. 본문 버전 등록 자체가 해당 기능의 구현을 뜻하지는 않는다.
