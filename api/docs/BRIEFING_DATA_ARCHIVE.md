# 팀원: 브리핑 수집 원본·가공 결과 내려받기

이 안내는 **데이터 파일과 독립적인 검사·복원 도구**를 위한 것입니다. Git과 **Python 3.10 이상**으로 검사·목록 조회가 가능합니다. 파일 복원은 descriptor-relative no-follow 연산과 hard link를 지원하는 **Linux·macOS·WSL의 파일시스템**에서 실행합니다. 네이티브 Windows 등 지원되지 않는 환경에서는 쓰기를 시작하지 않고 실패합니다. 앱 서버·화면·DB 설치·API 키·외부 Python 패키지는 필요하지 않습니다.

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

사건 묶음 SQLite 5개는 읽기 전용 일관 스냅샷의 논리 SQL로 저장했습니다. `.py`·`.sh`·SQL도 보존 자료에 포함됩니다. reader와 아래 재검사기는 이 파일들을 실행하지 않습니다. SQL은 먼저 내용을 확인하고, 별도로 검토한 뒤 기존 DB와 분리한 새 빈 DB에서만 실행 여부를 결정하세요. 체크섬 검사는 SQL 실행 안전성을 판정하지 않습니다.

```python
from pathlib import Path
sql = Path('복원된/경로/issues.sqlite3.sql').read_text(encoding='utf-8')
print(sql[:1000])  # 내용 조회만 수행
```

## 4. 전체 복원·재실행

```sh
python3 scripts/briefing_data_archive.py extract --output .local/briefing-data
```

동일 내용도 원래 경로마다 복원하므로 약 10.42GiB의 여유 공간을 확보하세요. 이미 같은 파일이 있으면 재사용하고, 다른 내용의 기존 파일은 덮어쓰지 않습니다. 복원 위치는 `.gitignore`로 재업로드를 방지합니다.

복원은 실제 디렉터리 handle을 기준으로 수행합니다. 내부 경로의 파일·부모 심볼릭 링크는 거절하고, 같은 폴더의 무작위 0600 임시 파일에 전부 쓴 뒤 `fsync`하고 atomic hard link로 확정합니다. 확정 직전에 다른 파일이 생겨도 덮어쓰지 않으며, 내용이 같을 때만 재사용합니다. 쓰기 중 실패하면 불완전한 최종 파일을 남기지 않아 같은 명령으로 재시도할 수 있습니다. 확정 직후 중단된 경우에도 완성된 파일을 재사용합니다. 기존 파일의 권한도 변경하지 않습니다.

출력 root는 사용자가 지정한 경로를 canonicalize한 위치입니다. 전용 출력 폴더를 선택하고 복원 중 다른 프로그램이 그 폴더를 이동·삭제하지 않도록 하세요. 부모 교체는 handle/identity 검사로 감지하며 새 심볼릭 링크를 따라가지 않습니다. 이것은 같은 사용자 권한으로 디렉터리를 임의 이동하는 프로그램까지 격리하는 sandbox나 전체 archive 트랜잭션·정전 복구 보장은 아닙니다. 강제 종료로 남은 `.zoop-archive-*`는 완료 파일로 사용하지 않으며 다음 복원은 새 임시 이름을 사용합니다.

이 PR의 도구는 자료 검사·목록·복원만 수행합니다. 보존된 수집/모델 스크립트나 앱 서버를 실행하지 않으며 AI·검색·시세 공급자·DB에 접속하지 않습니다. 브리핑 화면 실행기는 별도 기능 PR 범위입니다.

## 범위와 기록의 의미

- [데이터 개요](../../data/briefing-archive-2026-10-23/README.md) · [수량·용량·기준 시각](../../data/briefing-archive-2026-10-23/manifest.json) · [인증정보 검사 요약](../../data/briefing-archive-2026-10-23/security-audit.json).
- `files.jsonl.gz`는 원래 경로·배포/수집 해시 목록입니다. 도구가 gzip 압축을 자동으로 읽습니다. `redactions.jsonl`은 제거 내역, `excluded.jsonl`은 제외 파일/폴더와 사유를 담습니다.
- 키·비밀번호·쿠키·Bearer/JWT·CSRF·개인키를 제거했습니다. 인증/개인 자료·전체 DB·서버/빌드/의존성 파일은 제외했습니다.
- 자격 증명을 제거한 파일은 `sourceSha256`과 배포 `sha256`이 다릅니다. 역사적 payload/manifest 안의 해시는 당시 기록이며 배포 무결성에는 최상위 목록의 해시를 사용합니다.
- `.json` 확장자여도 실제 ZIP raw 응답인 과거 파일이 있고, UTF-8이 아닌 HTML도 포함됩니다. 파일의 실제 형식을 확인하세요. ZIP 내부도 검사했으며 변경할 자격 증명이 없으면 원 바이트를 보존했습니다.
- 실패·보류·미완성 응답과 수정본도 보존했습니다. PASS는 해당 실행의 판정이며 운영 승인·당시 본문 동일성·실제 예측 성과를 보증하지 않습니다. 137 그룹은 이 묶음의 캡처 기간 중간 결과이며 이후의 새 결과가 자동으로 추가되지는 않습니다.

## 재현 가능한 배포본 재검사

```sh
python3 scripts/briefing_data_archive_audit.py \
  --check data/briefing-archive-2026-10-23/audit-recheck-v1.json
python3 -m unittest discover -s scripts/tests -p 'test_briefing_data_archive*.py' -v
```

재검사는 공개된 [규칙·컬럼 허용 목록](../../data/briefing-archive-2026-10-23/audit-policy-v1.json)과 scanner/reader SHA-256, manifest·목록·23개 shard의 정확한 해시를 결과에 결속합니다. archive와 ZIP/gzip 내부를 실제 읽고 키 서명·문자열/컨테이너 자격 증명 필드·PostgreSQL의 최상위 컬럼을 검사합니다. 결과에는 객체 hash·규칙 ID·검토한 메타데이터 경로만 기록하고 검출된 값을 출력하지 않습니다. 리뷰 과정에서 HTML 1개 객체(16개 경로)에 남은 외부 분석 서비스 키 값은 공개 redactor로 추가 마스킹했습니다. 기사 NLP entity의 `token` 12개는 정확한 객체 해시·JSON 경로·인접 필드 타입을 모두 만족할 때만 예외로 집계합니다. 키의 권한이나 프로젝트 키 유출을 추정하지 않으며, 원본 sourceSha256과 캡처 이력은 유지합니다. 테스트에는 키 형태 양성 대조·정상 기사 URL/사용량·중첩 압축·허용하지 않은 DB 컬럼 반례가 있습니다.

`security-audit.json`은 원 캡처 당시의 검사 요약으로 보존합니다. 원 redactor의 규칙과 source digest는 새 policy에 기록했지만, **당시 비공개 known-value 목록을 공개 재현했다고 주장하지 않습니다.** 새 `audit-recheck-v1.json`의 PASS도 명시한 규칙의 통과이며 모든 비밀·개인정보의 부재를 보증하지 않습니다. 최상위 컬럼 허용 목록은 고정 스냅샷의 구조 계약이며 중첩 JSON/원문 전체의 개인정보 승인 목록이 아닙니다. 시스템/예약 도메인의 fixture 관리자 메타데이터가 남을 수 있습니다.

공개 게시에 대한 사용자 승인과 뉴스·공시·공급원의 재배포 권리는 별개입니다. 원 출처/권리 상태를 확인해 사용해야 하며 이 재검사는 재배포권리나 SQL 본문의 안전성을 인증하지 않습니다.
