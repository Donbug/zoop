# Issue #129 · 관리자 회원 활동 조회·차단 관리 인계

## 범위와 추적

- WBS: `6.10.3`
- 기능: `FS069-01`, `FS069-02`
- 목표 API: `listMembers`, `getMemberActivity`, `blockMember`, `unblockMember`
- 화면 추적: `A-ADM-05`
- 화면 구현은 포함하지 않는다. API는 정상·빈 결과·부분 미제공·권한 오류·충돌·재전송을 구분한다.

## 조회 계약

- 회원 ID는 가입 시 발급한 난수 기반 `members.id`를 가명 ID로 사용한다. `analytics_key`, 비밀번호, 세션 토큰은 반환하지 않는다.
- 이메일 검색은 가명 ID 또는 정규화된 전체 이메일의 정확 일치이고, 응답은 로컬 부분의 첫 글자만 남겨 마스킹한다. 검색어 원문은 로그와 cursor에 넣지 않는다.
- 활동 기간은 `[member.createdAt, metadata.asOf)`이다. `sessions`는 이 기간에 생성된 `kind=member` 세션 수이며 만료·회수된 세션도 포함한다.
- 현재 API migration에 실제 원천이 있는 회원·세션·관심종목·가상계좌 연결·감사 이력만 조회한다. `graphSelections`, `aiQuestions`, `briefingViews`, `holdingCount`, `feedbackUp`, `feedbackDown`은 `null`이고 `metadata.failures`에 `SOURCE_UNAVAILABLE`을 남긴다. 정상적인 0건을 미제공으로 바꾸지 않는다.
- 목록 cursor는 `(created_at DESC, id DESC)` 키셋, 필터 digest, limit, `asOf`를 포함한다. 새 회원은 첫 페이지의 `asOf` 이후 페이지에 끼어들지 않는다. 상태가 페이지 사이에 바뀌면 각 페이지 읽기 시점의 상태를 반영하는 weak consistency다.
- 상세·목록 조회는 회원 상태, revision, 세션, 감사 이력을 변경하지 않으며 대화·AI 결과·브리핑 원문을 읽지 않는다.

## 차단·해제 계약

- `members.status_revision`은 1부터 시작하고 실제 상태 변경 때만 증가한다. 요청의 `expectedRevision`이 현재 값과 다르면 `409 REVISION_CONFLICT`다.
- 최신 revision에서 이미 목표 상태이면 `changed=false`이고 revision·세션·감사 변경은 없다. 오래된 요청을 no-op 성공으로 처리하지 않는다.
- 차단은 활성 `kind=member` 세션을 같은 트랜잭션에서 회수한다. guest와 oauth pending은 대상이 아니다. 현재 저장소에 진행 중 회원 작업 원천이 없으므로 작업 취소를 가장하지 않는다.
- 해제는 새 로그인을 허용하지만 과거에 회수한 세션은 복구하지 않는다.
- `idempotency_records`의 범위는 `(admin, adminId, POST, path, Idempotency-Key)`다. 같은 key와 같은 canonical 요청은 최초 응답을 재현하고, 본문이 다르면 `409 IDEMPOTENCY_CONFLICT`다. 현재 관리자 회원 작업 레코드는 자동 만료하지 않는다.
- 상태 변경·세션 회수·성공 감사·완료 응답 저장은 하나의 DB 트랜잭션으로 commit 또는 rollback된다. 감사 detail에는 변경 전후 상태와 revision만 기록하고 회원 이메일·세션 정보는 넣지 않는다.

## 보안 경계

- 기존 `admin:all` 권한과 `zoop_admin_session`을 사용한다.
- GET은 관리자 인증, POST는 관리자 인증과 허용 Origin 및 세션 결합 `X-CSRF-Token`을 요구한다.
- 합성 fixture만 테스트에 사용하며 실제 개인정보나 비밀값을 저장하지 않는다.

## 검증

- 단위 테스트: `./api/gradlew -p api test --tests 'com.zoop.admin.members.*' --tests 'com.zoop.admin.members.service.*'`
- PostgreSQL 통합 테스트: `DB_URL=... DB_USERNAME=... DB_PASSWORD=... ./api/gradlew -p api authIntegrationTest --tests 'com.zoop.admin.members.AdminMemberPostgresTest'`
- 계약·생성물: `make contracts-check`, `make public-check`
- 전체 API: `make api-test`, `make api-build`

PostgreSQL 통합 테스트는 목록·상세의 마스킹/partial 응답, 무인증 401, 차단, 세션 회수, 같은 key 재전송, key 충돌, revision 충돌, 해제, 회수 세션 비복구와 감사 건수를 실제 migration 위에서 확인한다.

## 롤백

애플리케이션과 OpenAPI 변경은 같은 변경을 revert한다. 이미 적용된 migration에서 `status_revision`이나 `idempotency_records`를 즉시 삭제하면 운영 상태와 재전송 증거가 손실될 수 있으므로 자동 down migration은 제공하지 않는다. 제거가 필요하면 멱등성 보존 기간과 회원 상태 revision 소비자를 확인한 후 별도 승인 migration으로 처리한다.
