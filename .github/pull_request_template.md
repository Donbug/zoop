## Summary

해결하는 문제와 변경하지 않은 범위를 적으세요. PR 제목은 `feat(web): 기업 문서 조회 구현`처럼 [CONTRIBUTING](../CONTRIBUTING.md)의 Conventional Commits 형식을 사용합니다. 본개발은 루트 `web/`, `api/`, `ai/`, `contracts/`, `infra/`를 사용합니다. `api/` 최소 기반 PR은 업무 API·CI 연결보다 먼저 병합할 수 있으며, 다른 새 앱은 첫 기능과 검사기를 함께 추가합니다. [본개발 시작 안내](../docs/share/production-start-2026-10-12.md)를 참고하세요.

## Traceability

- Issue: `Closes #번호` 또는 이슈가 없는 사유
- FS / NFS / WBS: ID·현재 기능/업무명·BE/FE 역할·최신 고정본 파일/시트/행. 번호가 재사용됐으면 현행/이력 의미를 구분합니다.
- screen IDs / stable operationId:
- Work scope / affected paths: 본개발 / 프로토타입 / 계약 / 문서와 실제 변경 경로
- Affected apps / contracts: 루트 `web/`, `api/`, `ai/`, 향후 생성물 배포용 `contracts/`, `docs/api/openapi.yaml` 정본 및 영향을 받는 consumer/생성물

## Evidence

| Command / input | Observed result | Actual / fixture |
| --- | --- | --- |
| 실행한 명령과 최소 입력 | 실제 관측 결과 또는 미실행 사유 | 실제 출처/합성 구분 |

- [ ] 영향받는 consumer와 테스트를 함께 갱신했습니다.
- [ ] 생성물은 원본에서 재생성했으며 원본 경고를 숨기지 않았습니다.
- [ ] 실패·부분 실패·복구·회귀 조건을 검증했거나 미검증 이유를 명시했습니다.
- [ ] 실제 데이터와 합성 입력, 실제 AI 결과와 예시를 구분했습니다.
- [ ] 새 앱의 manifest·진입점·테스트와 검증 결과를 포함했습니다. `api/` 최소 기반 PR이라면 업무 API·CI 연결이 후속인 이유와 완료 시점을 적고, 다른 새 앱이라면 첫 기능·루트 명령·CI required gate 연결을 확인했습니다.
- [ ] 본개발은 `prototype/` runtime import와 DB 공유 없이 동작하며 계약 정본을 중복 생성하지 않았습니다.

## Rights and privacy

뉴스·문서·이미지·폰트·의존성의 출처와 라이선스/사용 권한을 적으세요. 모델 전송 승인과 실제 호출 여부를 구분하세요.

- [ ] 비밀 키, 실제 `.env`, 인증 헤더, DB, 개인 기록, 사용자 로그를 포함하지 않았습니다.
- [ ] 새로운 유료 호출·외부 데이터 요청·권한 확대가 있다면 별도 승인을 기록했습니다.

## Review and rollback

- 필요한 리뷰 역할 및 실제 지정한 reviewer:
- API/스키마/데이터 변경과 이행 방법:
- 실패 판정 조건과 되돌릴 커밋/데이터 복원 절차:
- 배포 영향: 없음 / 아티팩트 준비만 / 별도 승인된 배포

현재 CI는 프로토타입·문서/계약 검사입니다. 새 본개발 앱의 실제 runner 결과를 별도로 남기세요. 원격 CI 링크, branch protection, credential trust 승인, production 배포를 실행·확인하지 않았다면 완료로 표시하지 마세요.
