# 브리핑 migration 적용 순서 복구

마지막 ECS 배포 커밋 `a4308293`의 최신 migration은 `20261030120000`이다. 그 뒤 추가된 아래 파일 중 `20261029160000`, `20261030110000`은 이 watermark보다 작아, 기본 Flyway 검증에서 미적용 migration 오류를 일으킨다. 빈 DB를 만드는 시험만으로는 이 업그레이드 오류를 발견하지 못한다.

## 파일 번호 변경

아래 SQL 본문은 바꾸지 않고 파일 이름만 변경한다. 이미 배포된 `a4308293`의 migration 39개는 이름·내용을 유지한다. #467의 `20261101120000`과도 충돌하지 않는다.

| 기존 버전 | 새 버전 | 작업 |
| --- | --- | --- |
| 20261030110000 | 20261102130000 | 개인화 후보 풀 생성 (#449) |
| 20261029160000 | 20261102130100 | 브리핑 회원 평가 생성 (#459) |
| 20261030160000 | 20261102130200 | 관리자 브리핑 재처리 생성 (#459) |
| 20261030161000 | 20261102130300 | AI 결과 평가 연결 (#459) |
| 20261030162000 | 20261102130400 | 과거 사용량 기록 보존 제약 변경 (#459) |

마지막 파일은 새 테이블 생성만이 아니라 기존 `briefing_attempts`, `ai_executions`의 CHECK·NULL 조건을 바꾼다. 기존 행과 미확인 토큰·비용의 NULL을 유지한다. 전역 `out-of-order` 설정이나 `repair`, history 삭제로 검증을 우회하지 않는다.

## 배포 전 실제 DB 확인

배포 기록은 실제 DB 적용 이력의 대체 증거가 아니다. 이 변경은 **기존 번호 5개가 대상 DB에 적용되지 않았다는 확인이 선행 조건**이다. 인프라 담당자가 대상 DB에서 아래 읽기 전용 SQL을 실행한다. 애플리케이션 기본 schema가 public이 아니면 해당 schema의 `flyway_schema_history`를 지정한다.

```sql
SELECT installed_rank, version, description, script, checksum, installed_on, success
FROM flyway_schema_history
ORDER BY installed_rank DESC
LIMIT 30;

SELECT installed_rank, version, script, checksum, installed_on, success
FROM flyway_schema_history
WHERE version IN ('20261029160000', '20261030110000',
                  '20261030160000', '20261030161000', '20261030162000')
ORDER BY installed_rank;
```

- 기존 번호가 한 건이라도 있으면 자동 배포를 중단한다. 이미 적용된 DB에 변경된 파일 이름을 그대로 쓰면 missing migration 또는 중복 테이블 오류가 생긴다. 해당 DB의 실제 이력을 확인한 별도 이행 계획이 필요하다. history를 임의 삭제하거나 `repair`하지 않는다.
- 기존 번호가 전부 없고 최신 성공 버전이 새 번호보다 작으면, 백업·일반 배포 절차를 거쳐 새 migration을 순서대로 적용한다. 예측한 `20261030120000`과 다르면 전체 이력을 다시 대조한다.
- 파일 이름 변경 전에 이전 브랜치로 만들어 둔 로컬 DB에도 동일한 제한이 있다. 기존 DB를 덮어쓰지 말고 새 격리 개발 DB를 사용한다.
- 적용 뒤 새 번호 5개의 성공 이력·API health·기존 브리핑/설정/평가 조회를 확인한다. 이미지 빌드·stage-image 성공만으로 ECS 기동 성공이라고 판단하지 않는다.

## 회귀 검증

`BriefingDeployedMigrationPostgresTest`는 기존 CI의 `briefingIntegrationTest`에 포함된다. 테스트 전용 DB의 UUID schema만 사용하고, 실 DB·앱 public schema와 기존 생성 결과에는 쓰지 않는다.

1. 배포 커밋에서 고정한 SHA-256 manifest로 watermark 이하 migration 39개의 이름·내용 불변을 검사한다.
2. `20261030120000`까지만 적용하고 합성 회원 설정·발행본·변경 이력·완료 시도·미확인 사용량을 저장한다.
3. 기존 파일 배치가 `outOfOrder(false)`에서 미적용 migration 두 개를 검출하며 실패하는 것을 재현한다.
4. 새 파일 배치로 정상 업그레이드·validate·재실행 0건을 확인한다. 기존 필드/발행 원문·설정·NULL 사용량을 대조하고 발행본/완료 시도의 불변 제약을 확인한다.
5. 새 평가를 저장한 뒤 재기동에 해당하는 migration 재실행으로 평가가 유지되는지 확인한다.

```sh
DB_URL=jdbc:postgresql://127.0.0.1:5432/zoop_test \
DB_USERNAME=company_test DB_PASSWORD=... \
./api/gradlew -p api briefingIntegrationTest \
  --tests com.zoop.briefing.integration.BriefingDeployedMigrationPostgresTest
```

유료 AI 호출·새 뉴스 수집·운영 배포는 수행하지 않는다. 개인화 정시 실행 #461도 이 복구가 정리될 때까지 병합하지 않으며, 그 PR의 미배포 migration 번호 역시 병합 전 최신 main보다 뒤로 조정해야 한다.
