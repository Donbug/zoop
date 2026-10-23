# 팀원: 키 없이 현재 브리핑 3회차 보기

데이터 공유 브랜치에 포함한 저장 결과를 자신의 PC에서 **실제 Spring API → 별도 PostgreSQL → React 화면**으로 재생합니다. AI·검색·시세 공급자를 호출하지 않으며 OpenAI/DART/토스 키·AWS·Neo4j·private PoC 설치가 필요하지 않습니다. 운영 scheduler 실행과 구분합니다.

## 1. 브랜치와 준비물

저장소 루트에서 시작합니다. 자신의 미커밋 변경이 있으면 보존하고 별도 worktree에서 실행하세요.

```sh
git fetch origin feat/142-briefing-data-archive:refs/remotes/origin/feat/142-briefing-data-archive
git switch --track origin/feat/142-briefing-data-archive
# 이미 브랜치가 있다면 git switch 후 git pull --ff-only
```

필수: **JDK 21 이상, Python 3.10 이상, Docker 실행 환경, Node 22/pnpm**. Python 외부 라이브러리·기존 PostgreSQL 설정은 필요하지 않습니다. JDK 탐지가 안 되면 `JAVA_HOME`을 설정하거나 아래 실행에 `--java /절대경로/bin/java`를 추가합니다.

처음 한 번 준비합니다(이 과정은 빌드 의존성과 PostgreSQL 이미지를 내려받습니다).

```sh
make api-build
pnpm --dir web install --frozen-lockfile
docker pull postgres:16.13-alpine
```

Windows 팀원은 **WSL2의 Linux 파일시스템 안에 clone하고 JDK·Python·Node를 설치한 뒤**, Docker Desktop의 해당 WSL 배포판 연동을 켜서 위 명령을 실행합니다. 현재 artifact 저장소가 POSIX 소유권·0600/0700 권한을 검사하므로 Windows 네이티브 파일시스템 실행은 지원하지 않습니다. 실행기는 설치·이미지 pull·빌드를 몰래 수행하지 않습니다.

## 2. 데이터 확인 후 실행

```sh
# 파일·해시·조회 권한 결속 검사만: DB/네트워크/AI 호출 없음
python3 scripts/briefing_team_demo.py --check

# 별도 Docker DB + API 8080 + 프론트 5173
python3 scripts/briefing_team_demo.py
```

`status=READY`, `newAiCalls=0`, `newPriceCalls=0`이 출력되면 아래 주소를 엽니다.

- [10/22 퇴근](http://127.0.0.1:5173/briefing?date=2026-10-22&edition=evening&reading=compact)
- [10/22 출근](http://127.0.0.1:5173/briefing?date=2026-10-22&edition=morning&reading=compact)
- [10/21 퇴근](http://127.0.0.1:5173/briefing?date=2026-10-21&edition=evening&reading=compact)

**포트가 사용 중이면 기존 서버를 종료하지 말고 다른 포트를 지정합니다.**

```sh
python3 scripts/briefing_team_demo.py --api-port 18080 --web-port 13080
```

이 경우 출력된 `briefingUrl`을 사용합니다. 간단히/전체 보기·기업 전망·회차 시세·시장 요약/지표·핵심 상세의 저장 인용/주변 문맥/원문 링크·회차 이력·재구성 지도까지 확인할 수 있습니다. 지도에 세션 안내가 뜨면 **로그인 없이 둘러보기**로 진입한 뒤 브리핑에서 지도 링크를 다시 누릅니다. 다른 기능의 OAuth·계좌·AI 질의 전체 연동을 준비하는 실행은 아닙니다.

## 3. 종료·검증과 데이터 범위

- 실행 중인 터미널에서 **Ctrl-C**: 이번 실행의 API·프론트·무작위 이름의 임시 컨테이너/DB만 정리합니다. 다음 실행은 같은 보존 결과로 새 DB를 만듭니다. 기존 `api/.env`, DB, 컨테이너를 수정하지 않습니다.
- 무인 확인: `python3 scripts/briefing_team_demo.py --api-only --once`. 실제 API의 3회차·핵심 상세 5개·지도 기준 3개(총 11응답)를 원래 저장 응답 해시와 대조한 뒤 종료합니다. 요청마다 달라지는 `metadata.requestId`만 비교에서 제외하며 문안·시각·시세는 모두 비교합니다. CI의 api 잡도 별도 Docker DB에서 이 경로를 실행합니다.
- 프론트 proxy까지 무인 확인: `python3 scripts/briefing_team_demo.py --once`.
- 강제 종료로 컨테이너가 남았다면 `docker ps -a --filter label=com.zoop.briefing-team-demo=1`로 **본인 실행의 이름을 확인**하고 `docker rm -f -v <해당 이름>`으로 정리합니다.

자료는 [`api/demo/briefing-2026-10-21_22`](../demo/briefing-2026-10-21_22/README.md)에 있습니다. 개인 경로·계정·세션·키·원문 전체·모델 호출 원장·원 시세 응답은 포함하지 않습니다. SHA-256은 데이터 변조·실행 결과 일치를 확인하는 것이며 운영 공개 권리나 실제 예측 성과의 증명은 아닙니다. 상세는 데이터 README를 확인하세요.

기존에 생성된 전체 artifact로 재검증·가격 보완·실패 단계 재개가 필요한 담당자는 [연속 회차 실행](BRIEFING_ROUND_SERIES.md)을 사용합니다. 이번 팀원용 보기에는 원본 archive가 필요하지 않습니다.

## 수집 원본과 전체 가공 이력

화면용 3회차 외의 누적 수집 원본·모델 평가/생성·시장 자료·브리핑 전용 DB 결과는 [누적 데이터 사용 방법](BRIEFING_DATA_ARCHIVE.md)에 있습니다. Git에서 함께 내려받고 Python만으로 무결성 검사·선택/전체 복원·JSONL 읽기가 가능합니다.
