# 팀원: 누적 브리핑 원본·가공 결과 내려받기

브리핑 개발 과정에서 로컬에 보존한 뉴스/공시 원문, 검색 결과, 회사 연결/사건 묶음, 중요도/선정, 모델 요청·응답, 검증·보류·실패 기록, 시장/종목 시세, 생성 문안/전망/짧은 요약, 브리핑 전용 DB의 자료 테이블을 공유합니다. 동일 내용은 한 번 압축 저장하고, `files.jsonl.gz`에 각 원래 경로와 SHA-256을 연결했습니다.

**Python 3.10 이상과 Git만 있으면 자료를 검사하고 읽을 수 있습니다.** 키·로그인·DB 설치·외부 Python 패키지가 필요하지 않습니다. 아래 명령은 AI·검색·시세 공급자를 호출하지 않습니다.

## 1. 받기와 무결성 검사

```sh
git clone --single-branch --branch feat/142-briefing-data-archive https://github.com/Donbug/zoop.git zoop-briefing-data
cd zoop-briefing-data
python3 scripts/briefing_data_archive.py verify
python3 scripts/briefing_data_archive.py catalog
```

`status=VERIFIED`이면 파일 목록·모든 압축 묶음·각 원본 객체의 크기와 SHA-256이 일치합니다. Git LFS나 별도 비공개 다운로드는 필요하지 않습니다. 이미 다른 브랜치에서 작업 중이면 새 폴더로 clone하세요.

## 2. 필요한 원본부터 읽기

파일명/메타데이터만 열람합니다.

```sh
python3 scripts/briefing_data_archive.py list --group search-week-side
python3 scripts/briefing_data_archive.py list --group private-briefing-quality-121
python3 scripts/briefing_data_archive.py list --group private-briefing-quality-137
```

모든 목록 행은 JSON이며 `path`, `group`, `bytes`, 배포본 `sha256`, 로컬 원본 `sourceSha256`, 변경 시각과 자격 증명 제거 횟수를 포함합니다. `conversion`이 있으면 SQLite 논리 덤프나 미완성 JSON 같은 변환/상태를 확인하세요.

원문 모음 한 파일만 복원하는 예입니다.

```sh
python3 scripts/briefing_data_archive.py extract \
  --prefix workspaces/codex/search-week-side/week-20261002-20261008-v1/articles.jsonl \
  --output .local/briefing-data
```

복원한 JSONL은 한 줄이 한 문서입니다. 표준 Python으로 바로 읽습니다.

```sh
python3 - <<'PY'
import json
from pathlib import Path
path = Path('.local/briefing-data/workspaces/codex/search-week-side/week-20261002-20261008-v1/articles.jsonl')
with path.open(encoding='utf-8') as source:
    for index, line in enumerate(source):
        article = json.loads(line)
        print(article.get('title'), article.get('url'))
        print((article.get('body') or '')[:300])
        if index == 2:
            break
PY
```

완료된 3회차 생성 입력·평가/문안/보류 이력을 보고 싶으면 다음 그룹을 복원하세요.

```sh
python3 scripts/briefing_data_archive.py extract --group private-briefing-quality-121 --output .local/briefing-data
python3 scripts/briefing_data_archive.py extract --group private-briefing-docs-prices-131 --output .local/briefing-data
```

`private-...`는 로컬에서 사용했던 역사적 폴더 이름입니다. 이 묶음에 포함한 내용은 자격 증명 제거를 거친 공유본입니다. `inputs/sources.jsonl`은 입력 문서, `calls/`의 request/response/result/validation 파일은 실행 이력, `bundle*.json`은 회차 묶음, `storage*/artifacts/`의 `.bin`은 대부분 UTF-8 JSON/원문입니다. 파일명과 실제 JSON 구조는 작업 버전에 따라 다릅니다. 원본을 최신 형식으로 소급 변경하지 않았습니다.

## 3. 전체 복원과 DB 자료

```sh
# 전체 복원: 중복 경로까지 되살리므로 manifest.logicalBytes만큼 여유 공간이 필요합니다.
python3 scripts/briefing_data_archive.py extract --output .local/briefing-data

# DB에만 남은 자료를 JSONL로 읽기
python3 scripts/briefing_data_archive.py extract --group briefing-data-142 --output .local/briefing-data
```

DB 결과는 `.local/briefing-data/workspaces/codex/briefing-data-142/postgres/` 안에 있습니다. `index.json`에 DB별 테이블·행 수와 스냅샷 격리 수준을 기록했습니다. DB마다 반복 읽기/읽기 전용 트랜잭션으로 기사·버전·근거·artifact 메타데이터·브리핑·회사·문서 분석·그래프·AI 실행 테이블만 추출했습니다. 테이블별 JSONL 한 줄이 한 행이며, 기존 개발 DB를 통째로 복원하거나 운영 DB에 덮어쓰는 파일이 아닙니다.

사건 묶음 SQLite는 실행 중 파일을 직접 복사하지 않고 읽기 전용 연결에서 일관 스냅샷을 얻어 `issues.sqlite3.sql` 같은 SQL 텍스트로 보존했습니다. 필요하면 **새 빈 SQLite 파일**에 아래처럼 복원합니다.

```python
import sqlite3
from pathlib import Path
sql = Path('복원된/경로/issues.sqlite3.sql').read_text(encoding='utf-8')
with sqlite3.connect('새로운-로컬-issues.sqlite3') as db:
    db.executescript(sql)
```

자료 파일 복원은 기존 파일을 다른 내용으로 덮어쓰지 않습니다. 이미 같은 해시의 파일이면 재사용하고, 다르면 중단합니다. 수집·모델 재실행 스크립트가 함께 보존되어 있어도 이 도구는 실행하지 않습니다.

## 4. 실제 API와 React 화면으로 보기

현재 브랜치에는 기존 3회차의 팀원용 조회 데이터도 포함되어 있습니다. [BRIEFING_TEAM_DEMO.md](BRIEFING_TEAM_DEMO.md)의 JDK/Docker/Node 준비와 아래 명령을 사용하면 별도 DB → Spring API → React로 저장된 결과를 봅니다.

```sh
python3 scripts/briefing_team_demo.py --check
# 의존성·JAR 준비 후
python3 scripts/briefing_team_demo.py
```

이 화면 실행은 **기존 완료 3회차**를 재생합니다. 누적 archive의 모든 실험·보류·실패 버전을 한 번에 발행하거나 진행 중 137 결과를 최종본으로 표시하지 않습니다. 다른 회차/버전을 개발 재생할 때는 해당 bundle/source/clocks/manifest를 함께 선택하고 [연속 회차 실행](BRIEFING_ROUND_SERIES.md)을 따르세요. 역사적 파일의 내부 경로는 당시 기록이며 자기 환경에 맞게 경로 인자를 지정해야 합니다.

## 범위와 기록의 의미

- 범위·수량·용량·기준 시각: [manifest.json](../../data/briefing-archive-2026-10-23/manifest.json).
- 전체 경로/원본·배포 해시: `files.jsonl.gz`(gzip 압축 JSONL, 도구가 자동으로 읽음). 제거/변환된 파일: `redactions.jsonl`. 제외 항목과 사유: `excluded.jsonl`.
- 키·비밀번호·쿠키·Bearer/JWT·CSRF·개인키는 제거했습니다. 계정/세션/포트폴리오·인증 진단·개인 신청서·DB 전체 덤프·서버/빌드/의존성 파일은 자료 범위에서 제외했습니다.
- 자격 증명을 제거한 객체는 `sourceSha256`과 배포 `sha256`이 다릅니다. 당시 payload/manifest 안의 해시는 원 이력으로 보존했으므로 배포 무결성에는 최상위 목록의 해시를 사용하세요.
- 실패·보류·불완전 응답과 당시 수정본도 남겼습니다. PASS 표시는 해당 실행의 판정이며 전체 품질/운영 승인이나 주가 예측 성과 인증이 아닙니다. 과거 발행 시각 기준의 재생과 실제 당일 수집 사실을 구분하세요.
- 137 그룹은 수집 중간 시점의 결과입니다. `manifest.sourceStatus`와 각 파일 변경 시각을 확인하고 최종 발행본과 구분해서 사용하세요. 이번 묶음은 지속 동기화 작업이 아니며 이후 새로 저장된 결과는 포함하지 않습니다.

일부 raw 응답은 ZIP이거나 EUC-KR 등 UTF-8 이외 인코딩의 HTML입니다. 확장자보다 파일의 실제 형식을 확인하세요. ZIP 내부도 검사했으며 자격 증명 변경이 없으면 압축 원본 바이트를 보존했습니다. 기존 SHA 이름의 `.json` 파일 중에도 ZIP raw 응답이 있을 수 있습니다.
