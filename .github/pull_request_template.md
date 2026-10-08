## Summary

해결하는 문제와 변경하지 않은 범위를 적으세요. PR 제목은 `feat(web): 관심 종목 조회`처럼 Conventional Commits 형식을 사용합니다.

## Traceability

- Issue: `Closes #번호` 또는 이슈가 없는 사유
- FS / NFS / WBS: ID와 **현재 업무명**
- screen IDs / operationId:
- Affected apps / contracts: `web`, `api`, `ai`, `docs/api/openapi.yaml` 등

## Evidence

| Command / input | Observed result | Actual / fixture |
| --- | --- | --- |
| 실행한 명령과 최소 입력 | 실제 관측 결과 또는 미실행 사유 | 실제 출처/합성 구분 |

- [ ] 영향받는 consumer와 테스트를 함께 갱신했습니다.
- [ ] 생성물은 원본에서 재생성했으며 원본 경고를 숨기지 않았습니다.
- [ ] 실패·부분 실패·복구·회귀 조건을 검증했거나 미검증 이유를 명시했습니다.
- [ ] 실제 데이터와 합성 입력, 실제 AI 결과와 예시를 구분했습니다.

## Rights and privacy

뉴스·문서·이미지·폰트·의존성의 출처와 라이선스/사용 권한을 적으세요. 모델 전송 승인과 실제 호출 여부를 구분하세요.

- [ ] 비밀 키, 실제 `.env`, 인증 헤더, DB, 개인 기록, 사용자 로그를 포함하지 않았습니다.
- [ ] 새로운 유료 호출·외부 데이터 요청·권한 확대가 있다면 별도 승인을 기록했습니다.

## Review and rollback

- 필요한 리뷰 역할 및 실제 지정한 reviewer:
- API/스키마/데이터 변경과 이행 방법:
- 실패 판정 조건과 되돌릴 커밋/데이터 복원 절차:
- 배포 영향: 없음 / 아티팩트 준비만 / 별도 승인된 배포

원격 CI 링크, branch protection, production 배포를 실행하지 않았다면 완료로 표시하지 마세요.
