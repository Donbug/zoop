# 브리핑 누적 원본·가공 결과 — 2026-10-23

[팀원용 내려받기·검사·복원·자료 읽기 안내](../../api/docs/BRIEFING_DATA_ARCHIVE.md)

- 원래 경로 **132,244개**, 중복 제거 객체 **24,121개**.
- 원래 경로까지 전체 복원할 때 약 **10.42 GiB**, 중복 제거 원본 약 **1.31 GiB**.
- Git의 압축 객체 23묶음 + 파일 목록 약 **377.1 MiB**. Git LFS·별도 다운로드 없음.
- 포함: 검색/뉴스·공시·ZIP/HTML 원문, 시세/시장 원응답, 사건/회사 연결, 평가·선정·검증·보류/실패, 모델 요청/응답, 브리핑·시장/기업 전망·짧은 읽기, 33개 개발 DB의 허용된 자료 테이블 113,652행.
- 자격 증명 제거가 필요한 경로 1,937개. 원본과 바이트가 그대로인 경로 130,307개. SQLite는 읽기 전용 논리 SQL로 변환.
- 시작 2026-10-23T07:17:55.039813+00:00 / 종료 2026-10-23T07:21:40.524591+00:00. 파일별 modifiedAt 제공. 진행 중인 137 그룹은 이 수집 기간의 중간 결과이며 최종 발행본으로 보지 않습니다.

```sh
python3 scripts/briefing_data_archive.py verify
python3 scripts/briefing_data_archive.py catalog
python3 scripts/briefing_data_archive.py extract --group search-week-side --output .local/briefing-data
```

`manifest.json`은 각 묶음/목록의 크기와 해시, `files.jsonl.gz`는 원본 경로·배포/수집 해시, `redactions.jsonl`은 제거 내역, `excluded.jsonl`은 자료가 아닌 제외 파일/폴더와 사유입니다. 입력의 권리/당시 본문/판정 한계는 원 기록대로 보존했습니다. 계정·세션·키·비밀번호·개인 신청서·전체 DB/빌드/프로세스 파일은 포함하지 않습니다.

독립 재검사: 24,121개 객체와 ZIP 내부1,000개 검사, 알려진 실제 인증정보/키 서명 잔존0, 추가 제거 변경0. 키 제거 양성·기사 URL/모델명 보존 반례 PASS. [검사 요약](security-audit.json).
