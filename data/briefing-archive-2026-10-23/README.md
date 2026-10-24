# 브리핑 누적 원본·가공 결과 — 2026-10-23

[팀원용 내려받기·검사·복원·자료 읽기 안내](../../api/docs/BRIEFING_DATA_ARCHIVE.md)

- 원래 경로 **132,244개**, 중복 제거 객체 **24,121개**.
- 원래 경로까지 전체 복원할 때 약 **10.42 GiB**, 중복 제거 원본 약 **1.31 GiB**.
- Git의 압축 객체 23묶음 + 파일 목록 약 **377.1 MiB**. Git LFS·별도 다운로드 없음.
- 포함: 검색/뉴스·공시·ZIP/HTML 원문, 시세/시장 원응답, 사건/회사 연결, 평가·선정·검증·보류/실패, 모델 요청/응답, 브리핑·시장/기업 전망·짧은 읽기, 33개 개발 DB의 허용된 자료 테이블 113,652행.
- 자격 증명 제거가 필요한 경로 1,953개. 원본과 바이트가 그대로인 경로 130,291개. SQLite는 읽기 전용 논리 SQL로 변환.
- 시작 2026-10-23T07:17:55.039813+00:00 / 종료 2026-10-23T07:21:40.524591+00:00. 파일별 modifiedAt 제공. 진행 중인 137 그룹은 이 수집 기간의 중간 결과이며 최종 발행본으로 보지 않습니다.

```sh
python3 scripts/briefing_data_archive.py verify
python3 scripts/briefing_data_archive.py catalog
python3 scripts/briefing_data_archive.py extract --group search-week-side --output .local/briefing-data
```

`manifest.json`은 각 묶음/목록의 크기와 해시, `files.jsonl.gz`는 원본 경로·배포/수집 해시, `redactions.jsonl`은 제거 내역, `excluded.jsonl`은 자료가 아닌 제외 파일/폴더와 사유입니다. 입력의 권리/당시 본문/판정 한계는 원 기록대로 보존했습니다. 계정·세션·키·비밀번호·개인 신청서·전체 DB/빌드/프로세스 파일은 포함하지 않습니다.

리뷰 보완에서 캡처 HTML 1개 객체(16개 경로)의 외부 분석 서비스 키 값을 추가 마스킹했습니다. 원 sourceSha256은 유지하며 변경 객체·규칙·redactor 해시는 manifest의 distributionRevision에 기록했습니다. 기사 NLP entity의 token 필드 12개는 정확한 객체 해시·JSON 경로·인접 필드 타입에 한정한 검토 예외이며 결과에 따로 집계합니다.

캡처 당시 검사 요약은 [security-audit.json](security-audit.json)에 보존합니다. 당시 비공개 known-value 목록은 공개 재현 대상이 아닙니다. 공개 scanner·[정확한 규칙/컬럼 범위](audit-policy-v1.json)·[배포본/코드 해시 결속 결과](audit-recheck-v1.json)는 다음 명령으로 별도 재검사할 수 있습니다.

```sh
python3 scripts/briefing_data_archive_audit.py --check data/briefing-archive-2026-10-23/audit-recheck-v1.json
```

PASS는 이 규칙의 통과이며 모든 비밀·개인정보의 부재, SQL 실행 안전성, 원문 재배포권리의 인증은 아닙니다. 보존된 스크립트/SQL도 데이터로 검사하며 실행하지 않습니다. 파일 복원은 Linux·macOS·WSL의 dir_fd/no-follow·hard-link 지원 파일시스템에서 실행합니다.
