# 브리핑 공동 개발분 이관 — 1차

- 이슈: [#190](https://github.com/Donbug/zoop/issues/190), 관련 #99 핵심 이슈 선정(FS030/WBS6.8.3), #100 주요 시장 지표(FS031/WBS6.8.4), #104 입력/이력 보존 기반(FS035/WBS6.8.8), #111 통합 검증(WBS6.8.15).
- 비교 기준: Donbug `main@71ff60214ab417c3e3deb7c41f958f96f4cc46a6`, 공동 개발 통합본 `a8d7ddd63dec65c1d153441ca897cd86837d7f15` (2026-10-16).
- 목표 public operation은 getBriefing/listBriefingRounds이나 이번 1차에는 새 HTTP route·DTO·OpenAPI 변경이 없다. 관련 화면 D-BRF-01/02/04의 구현 완료를 의미하지 않는다.

## 1차에 옮긴 범위

선정기·입력 고정·회차/명시적 거래일·개발용 3지표 snapshot과 해당 시험을 새로운 `com.zoop.briefing` 패키지로 이관한다. 유일한 공통 실행기 수정은 `briefingMarketCapture` 명시 실행 task 추가다. 기존 Gradle dependency·default test/AI 계약·company/auth PostgreSQL task와 CI는 보존한다.

이관한 Java source/test는 위 통합본과 동일하며 실제 뉴스·시장 원문, 로컬 선정 평가표, 키, 환경 파일, DB, 실행 로그, private 보고서 또는 신호판 폴더를 옮기지 않는다. 기존 API와 인증/문서/AI 파일을 이전 사본으로 덮어쓰지 않는다. 사용 방법은 [브리핑 입력](../../api/docs/BRIEFING_INPUT.md)에 있다.

## 직접 확인한 충돌과 후속 범위

| 영역 | 최신 돈버그와의 차이 | 1차 처리 / 후속 조건 |
| --- | --- | --- |
| 공통 코드 | API 비교에서 신규105파일·기존15파일의 차이, 돈버그에만 있는302파일 확인. 새 인증/문서/기업·S2/S3 transport가 존재 | AI 예외/transport·Member·application.yml·공통 예외 처리·기존 문서/설정을 덮어쓰지 않음 |
| Gradle | 돈버그에 security/crypto와 company/auth/S2/S3 계약 task가 추가됨 | 기존 dependency·test 태그·task 유지, 개발 수집 task만 추가 |
| artifacts | 돈버그 V20261014120000이 공통 artifacts를 이미 생성하며 kind CHECK/불변 UPDATE trigger/관련 문서 FK를 소유. 공동개발 V20261015114000은 CREATE TABLE artifacts를 다시 수행 | 중복 생성 migration은 옮기지 않음. 후속 DB PR은 기존 registry를 참조하고 briefing_input FK/검증만 후속 migration으로 추가해야 함 |
| Flyway 순서 | 돈버그 최신 migration은 V20261015120000, 공동개발 회차/attempt migration은 V20261013163000/191000 | 이전 날짜 파일을 그대로 추가하거나 기존 적용 파일을 수정하지 않음. 신규 번호의 후속 migration과 기존 적용 DB 업그레이드 시험 필요 |
| 회차/발행 저장 | 제품 ERD v6 §19는 briefing_publications/items/outlooks를 briefing_rounds로 통합하며 공동개발 snapshot 저장과 방향이 일치함 | 분리 발행 테이블을 되살리지 않음. 후속 DB 이관은 기존 registry/FK 소유자·briefing_changes 정정/감사 경계를 맞춰야 하며 기존 isolation 시험만으로 운영 연결 완료로 판단하지 않음 |
| 현재 원천·권한 | 공동개발 local 원장은 개발용이며 최신 돈버그 articles/article_versions·document analyses·현재권한 owner와 자동으로 연결되지 않음 | 새로운 가짜 owner/허위 PASS 없이 실제 adapter·revision/철회·graph 준비를 연결해야 함 |
| HTTP·인증 | 최신 돈버그는 cookie/CSRF·rate limit·개인 접근 경계를 구현함 | 브리핑 Controller·관리자·평가/개인화 경로는 이번에 옮기지 않음. 공개/회원 계약과 실제 principal을 확인 후 연결 |
| AI 생성·usage | 공동개발 생성/검증/사용량 recording은 개발 재생과 실제 운영 등록을 구분함 | 이번 1차에서 OpenAI/DART/AI pipeline·JDBC 결과 저장을 시작하지 않음. 공통 artifacts/ai_executions 및 내부 HTTP 소유 경계 연결 후 별도 이관 |

## DB 변경과 검증 기준

**이번 PR은 기존 migration·DDL·entity·DB 설정을 변경하지 않는다.** Flyway out-of-order를 켜거나 공통 테이블을 다시 만들지 않는다. 최신 돈버그 기준의 기존 company/auth PostgreSQL 회귀를 검증하고 그 결과를 PR에 기록한다.

후속 DB PR에서는 (1) 기존 main migration 전체 적용→새 migration 업그레이드, (2) artifacts 기존 행/문서 FK·불변성 보존, (3) 발행/정정 이력의 ERD 매핑, (4) 현재권한·그래프·검수와 transaction/잠금 일치, (5) 신선도/실패·재생을 확인해야 한다. 담당 owner의 기존 파일/테이블을 임의 교체하지 않는다.

## 완료·리뷰·롤백

이 PR은 제품 전체 브리핑의 완료가 아닌 검증된 입력 기반 이관이다. 실제 HTTP 조회·발행·AI 생성·운영 scheduler와 남은 기능의 acceptance는 열린 상태로 유지한다. main 병합/배포는 이번 요청 범위가 아니다.

브리핑 담당은 선정·시점·근거·입력 무결성을, 공통 API/DB 담당은 향후 이관의 registry/migration·인증 경계를 검토한다. 새 외부 호출/권한 확대는 이 PR로 만들지 않는다. 롤백은 이 PR 커밋 revert이며 DB가 바뀌지 않아 데이터 복원 migration은 필요하지 않다.
