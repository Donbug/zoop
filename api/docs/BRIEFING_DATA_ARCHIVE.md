# 팀원: 브리핑 수집 원본·가공 결과 내려받기

이 안내는 **데이터 파일과 독립적인 검사·복원 도구**를 위한 것입니다. Git과 **Python 3.10 이상**만 있으면 뉴스·공시 원문, 시장/종목 시세, 사건/기업 연결, 중요도·선정·모델 요청/응답·검증·보류/실패·브리핑/전망/짧은 읽기 결과를 내려받아 사용할 수 있습니다. 앱 서버·화면·DB 설치·API 키·외부 Python 패키지가 필요하지 않습니다.

공유 데이터는 2026-10-23 16:17~16:21 KST에 보존한 시점 묶음입니다. 56그룹·132,244개 원래 경로를 24,121개 객체로 중복 제거했습니다. 다운로드 데이터는 약 **377MiB**, 원래 중복 경로까지 전체 복원하면 약 **10.42GiB**가 필요합니다.

## 1. 내려받고 검사하기

새 폴더에서 다음 명령을 실행합니다. 현재 공유 브랜치는 `feat/143-briefing-data-main`이며 main을 기준으로 만든 데이터 전용 PR입니다.

```sh
git clone --single-branch --branch feat/143-briefing-data-main https://github.com/Donbug/zoop.git zoop-briefing-data
cd zoop-briefing-data
python3 scripts/briefing_data_archive.py verify
python3 scripts/briefing_data_archive.py catalog
```

`status=VERIFIED`이면 압축 묶음·파일 목록·모든 객체의 크기/SHA-256 검사가 통과한 것입니다. `catalog`는 그룹별 파일 수와 복원 용량을 보여 줍니다. Git LFS나 별도 다운로드가 필요하지 않습니다. 기존 작업 폴더는 그대로 두고 새 폴더로 clone하세요. PR이 main에 병합된 뒤에는 main에서도 같은 Python 명령을 사용할 수 있습니다.

## 2. 필요한 원문만 복원해서 읽기

파일 목록만 확인하려면 다음 명령을 사용합니다.

```sh
python3 scripts/briefing_data_archive.py list --group search-week-side
python3 scripts/briefing_data_archive.py list --group private-briefing-quality-121
python3 scripts/briefing_data_archive.py list --prefix workspaces/codex/private-briefing-quality-121/inputs/
```

목록 한 줄은 JSON이며 `path`, `group`, `bytes`, 배포본 `sha256`, 자격 증명 제거 전 기록의 `sourceSha256`, 파일 변경 시각, 제거 횟수와 변환 종류를 포함합니다.

예를 들어 원문 모음 한 파일만 복원합니다.

```sh
python3 scripts/briefing_data_archive.py extract \
  --prefix workspaces/codex/search-week-side/week-20261002-20261008-v1/articles.jsonl \
  --output .local/briefing-data
```

아래 코드는 복원한 JSONL의 처음 세 문서를 읽습니다. JSONL은 한 줄이 한 문서입니다.

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

## 3. 브리핑 가공 결과·시세·DB 자료 읽기

완료된 세 회차의 입력·평가·문안 이력과 시세 보강 기록은 다음 그룹에 있습니다.

```sh
python3 scripts/briefing_data_archive.py extract --group private-briefing-quality-121 --output .local/briefing-data
python3 scripts/briefing_data_archive.py extract --group private-briefing-docs-prices-131 --output .local/briefing-data
```

`inputs/sources.jsonl`은 입력 문서, `calls/`의 request/response/result/validation 파일은 실행 이력, `bundle*.json`은 회차 묶음, `storage*/artifacts/`의 `.bin`은 대부분 UTF-8 JSON/원문입니다. `private-...`는 원래 로컬 폴더 이름이며 여기 포함한 파일은 자격 증명 제거를 거친 공유본입니다. 작업 버전마다 구조가 다르므로 `list`로 실제 경로를 먼저 확인하세요.

DB에서 내보낸 자료 테이블은 다음처럼 복원합니다.

```sh
python3 scripts/briefing_data_archive.py extract --group briefing-data-142 --output .local/briefing-data
```

자료는 `.local/briefing-data/workspaces/codex/briefing-data-142/postgres/`에 있습니다. `index.json`에 33개 DB별 테이블·행 수·스냅샷 정보를 기록했습니다. 테이블별 JSONL 한 줄이 한 행입니다. 기사·버전·근거·artifact 메타데이터·브리핑·회사·문서 분석·그래프·AI 실행 자료 테이블을 허용 목록으로 선정해 반복 읽기/읽기 전용 트랜잭션으로 내보냈습니다. 계정·세션·포트폴리오와 운영 DB 전체 덤프는 포함하지 않습니다.

사건 묶음 SQLite 5개는 읽기 전용 일관 스냅샷의 논리 SQL로 저장했습니다. `issues.sqlite3.sql`처럼 끝나는 파일은 필요할 때 **새 빈 SQLite 파일**로 복원할 수 있습니다.

```python
import sqlite3
from pathlib import Path
sql = Path('복원된/경로/issues.sqlite3.sql').read_text(encoding='utf-8')
with sqlite3.connect('새로운-로컬-issues.sqlite3') as db:
    db.executescript(sql)
```

## 4. 전체 복원·재실행

```sh
python3 scripts/briefing_data_archive.py extract --output .local/briefing-data
```

동일 내용도 원래 경로마다 복원하므로 약 10.42GiB의 여유 공간을 확보하세요. 이미 같은 파일이 있으면 재사용하고, 다른 내용의 기존 파일은 덮어쓰지 않습니다. 복원 위치는 `.gitignore`로 재업로드를 방지합니다.

이 PR의 도구는 자료 검사·목록·복원만 수행합니다. 보존된 수집/모델 스크립트나 앱 서버를 실행하지 않으며 AI·검색·시세 공급자·DB에 접속하지 않습니다. 브리핑 화면 실행기는 별도 기능 PR 범위입니다.

## 범위와 기록의 의미

- [데이터 개요](../../data/briefing-archive-2026-10-23/README.md) · [수량·용량·기준 시각](../../data/briefing-archive-2026-10-23/manifest.json) · [인증정보 검사 요약](../../data/briefing-archive-2026-10-23/security-audit.json).
- `files.jsonl.gz`는 원래 경로·배포/수집 해시 목록입니다. 도구가 gzip 압축을 자동으로 읽습니다. `redactions.jsonl`은 제거 내역, `excluded.jsonl`은 제외 파일/폴더와 사유를 담습니다.
- 키·비밀번호·쿠키·Bearer/JWT·CSRF·개인키를 제거했습니다. 인증/개인 자료·전체 DB·서버/빌드/의존성 파일은 제외했습니다.
- 자격 증명을 제거한 파일은 `sourceSha256`과 배포 `sha256`이 다릅니다. 역사적 payload/manifest 안의 해시는 당시 기록이며 배포 무결성에는 최상위 목록의 해시를 사용합니다.
- `.json` 확장자여도 실제 ZIP raw 응답인 과거 파일이 있고, UTF-8이 아닌 HTML도 포함됩니다. 파일의 실제 형식을 확인하세요. ZIP 내부도 검사했으며 변경할 자격 증명이 없으면 원 바이트를 보존했습니다.
- 실패·보류·미완성 응답과 수정본도 보존했습니다. PASS는 해당 실행의 판정이며 운영 승인·당시 본문 동일성·실제 예측 성과를 보증하지 않습니다. 137 그룹은 이 묶음의 캡처 기간 중간 결과이며 이후의 새 결과가 자동으로 추가되지는 않습니다.
