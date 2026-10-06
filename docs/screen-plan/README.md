# 줍 화면계획서 v2.1

편집본은 `zoop-screen-plan-v2.1.pptx`, 배포본은 `zoop-screen-plan-v2.1.pdf`예요. v2.0 배포 파일은 제거하며 이전 버전은 깃 이력에서 확인해요. 실제 프로토타입을 조작한 화면이며 모의 계좌와 실제 기사 저장본을 사용해요. AI 답변은 생성형 모델 호출이 없는 규칙 기반 예시예요. 긍부정·회차 판단은 **디자인시스템 예시**만 캡처하며 데모 데이터에는 판정값이 없어요.

## 다시 만들기

저장소 루트에서 다음 명령을 실행해요. Python 패키지는 `uv run --with`의 일회성 환경에만 설치돼요. 기존 웹 의존성(`prototype/web/node_modules`), LibreOffice, Playwright 1.61.0과 맞는 캐시 Chromium 1228(149.0.7827.55)이 필요해요.

```sh
uv run --with playwright==1.61.0 python docs/screen-plan/capture.py --manage-servers --with-admin-containers
uv run --with python-pptx --with pymupdf --with pillow python docs/screen-plan/build_deck.py --pdf
uv run --with pyyaml python docs/system/import_sources.py --spec-dir docs/evidence/raw/functional-spec_2026-10-06 --wbs-dir docs/evidence/raw/wbs_2026-10-03 --requirements-dir docs/evidence/raw/requirements-sheet_2026-10-06
uv run --with pyyaml --with openpyxl python docs/system/build.py
uv run --with pyyaml --with openpyxl python docs/system/build.py --check
uv run --with openapi-spec-validator python -m openapi_spec_validator docs/api/openapi.yaml
open docs/screen-plan/zoop-screen-plan-v2.1.pdf
```

캡처는 공유 `prototype/bff/var`를 읽어 `/tmp/zoop-state-plan`에 복사하고 `rebuild_demo_briefings.py --source /tmp/zoop-state-plan --target /tmp/zoop-state-plan-market --from 2026-09-16`으로 격리된 시연 회차를 만들어요. BFF 8824, Vite 5194, 브라우저 호스트 `plan.localhost`만 사용해요. 공유 8787/5173은 사용하지 않아요. 두 포트는 비어 있어야 해요. 성공·실패와 관계없이 이 명령이 띄운 서버 프로세스 그룹을 종료해요. 관리자용 `zoop-poc-postgres-1`·`zoop-poc-neo4j-1`·`zoop-poc-neo4j-real2`는 중지 상태였던 것만 시작하고 끝나면 그 컨테이너만 정상 중지해요. 컨테이너·볼륨은 삭제하지 않으며 공유 데모 상태와 프로토타입 소스는 수정하지 않아요.

관심 종목 두 화면만 갱신할 때는 첫 명령 대신 `uv run --with playwright==1.61.0 python docs/screen-plan/capture.py --manage-servers --slides D-WAT-01 D-WAT-01b`를 실행해요. 다른 캡처는 유지하고 두 항목만 기존 manifest에 반영해요. 배포 전에는 전체 캡처를 실행해요.

브리핑은 생성 경로로 다시 발행한 시연 회차이며 실제 스케줄러의 과거 실행 기록이 아니에요. 지표는 회차 기준 시각 이전의 공개 자료예요. 외부 출처 응답에 따라 값·지연·미제공·실패 상태가 달라질 수 있어요. 명령은 화면·동작을 재현하며 파일 바이트를 고정하지 않아요.

## v2.1 변경

- 독립 종목 메뉴 `D-STK-01`·`M-STK-01`: 목록·검색·상세 이동·관심 토글. 비회원의 시장 전체 열람도 확인해요. 지도 내부 목록 전환은 제거했어요.
- 기업 패널 `D-GRP-03`: 시세·작은 1개월 추이·접힌 주요 지표·모의 보유·사건·관련 기업·뉴스의 현재 화면을 사용해요.
- 기업 상세 `D-COM-03`~`06`: 좌측 기업 전환, 기업 중심 관계 그래프, 시간 버킷 선택 연동, 거래 바 선택에 따른 `asOf` 변경. 기간은 1일/1주/1개월/1년이며 출처 미지원 기간은 비활성 상태를 그대로 기록해요.
- 모바일 기업 전환 `M-COM-02`: 같은 상세 화면에서 전환 시트를 열어요. 하단 탭은 지도·종목·브리핑·AI·내 종목의 5개예요.
- 긍부정 `D-SEN-01`·`02`: 디자인시스템의 `SentimentLabel`·회차 판단 예시. 실제 데모 판정이나 주가 전망으로 설명하지 않아요. 판정 없는 영역은 숨기며 등락색·확률을 재사용하지 않아요.
- `HISTORY-21`·`APP-DOCS` 추가, `M-RULE-01`·`MAP-*`·`APP-ID` 갱신. 요구 번호는 10-06 정의서의 기능 의미 대응으로 갱신했어요.

## 캡처·검토 파일

- `capture.py`: 실제 로그인·초기 설정·튜토리얼·지도·종목·기업·AI·관리자·브리핑·모바일 조작.
- `captures/<ID>.png`·`.json`: 원본과 좌표, 번호 조작의 URL·화면 글자. 데스크톱 1440×900, 모바일 390×844의 `-before`·`-after` 쌍이에요.
- `captures/manifest.json`: 실제 캡처 내용. 덱은 `build_deck.py`의 `SCREEN_ORDER`로 화면 흐름에 맞춰 정렬해요.
- `captures/screen-details.json`: 화면별 3~6개 조작·구현 상태·코드 근거. 상태 칸은 이번에 캡처한 상태와 구현 상태를 구분해요.
- `captures/interaction-history.json`: **이번 실행**의 실제 클릭 이력. 다른 화면 이동을 참조한 번호도 이 이력에서 확인되어야 통과해요.
- `captures/auth-proof.json`: 비회원 개인화·내 종목·AI 제한 및 공통 브리핑 열람·관리자 로그인 이동 결과.
- `captures/annotation-geometry.json`: 대상 상자와 번호 원의 최종 위치. 번호 원은 대상 밖에 배치해요.
- `captures/slide-index.json`: 모든 슬라이드의 쪽·ID·제목·라우트. 통합 문서 생성기의 화면 ID 출처예요.
- `captures/rendered/page-*.png`·`contact-*.png`: PDF 전 페이지 렌더와 6쪽 연락판.
- `captures/rendered/font-audit.json`: 페이지별 글꼴·포함 여부.
- `captures/verification.json`: 최신 실행의 수치와 렌더 검토·정리 결과.

`captures/rendered/`는 빌드 생성물이며 `.gitignore` 대상이에요. PPTX에는 기존 SUIT Regular/Bold TTF를 EOT 컨테이너로 포함하고 OFL 1.1을 `ppt/fonts/LICENSE.txt`에 보존해요. [SUIT](https://sun.fo/suit/) · [EOT 구조](https://www.w3.org/submissions/EOT/Overview.html) · [LibreOffice embedded font import](https://github.com/LibreOffice/core/blob/master/oox/source/ppt/EmbeddedFontListContext.cxx).

## 문서 체계·근거 버전

- 기능 명세: `docs/evidence/raw/functional-spec_2026-10-06/`.
- 요구사항: `docs/evidence/raw/requirements-sheet_2026-10-06/1-요구사항-정의서.csv`. 번호 대응은 `docs/evidence/doc-delta-2026-10-06.md` §2.2.
- WBS: `docs/evidence/raw/wbs_2026-10-03/`(10-06 재수집본과 내용 동일).
- 디자인: `docs/design/design-direction.md` §4.8·§5.3·§5.4·§5.7·§5.10, `docs/design/sentiment.md`.
- 목표 API: `docs/api/out/zoop-api-spec.md`(정본은 `docs/api/openapi.yaml`). 예시 화면 연결은 실제 API 실행·모델 판정을 증명하지 않아요.
- 통합 목록: `docs/system/out/index.md`. 화면↔기능↔API↔WBS↔구현 판정은 `docs/system/out/zoop-trace.xlsx`에서 확인해요.
- 팀 v1.7: `docs/evidence/screen-plan-v1.7-review.md` 머리 Main 정정 우선. 관리자 ID는 최종 42쪽의 5개 묶음을 유지해요.

## 검증 범위와 한계

관리자 캡처는 현재 상태와 메뉴 이동을 확인해요. 유료 작업·검수 허용·차단·정정·중단은 실행하지 않아요. AI 조회 오류는 질문 작업을 재실행하지 않고 대화 조회 응답만 503으로 차단해 재현해요. 실제 서비스 장애로 설명하지 않아요. 근거 접근 매트릭스는 문서·소스 규칙이며 모든 404/403/외부 원문 실패를 이번 캡처에서 재현한 것은 아니에요. 외부 원문 링크의 새 창 이동은 실행 관측 결과를 그대로 적어요.

가격·시장 지표는 외부 출처의 현재 응답이므로 과거 캡처와 값이 다를 수 있어요. 데모에는 실제 모델 판정값·시장 요약·재무 추이 생산자가 없으며 빈 영역에 값을 만들지 않아요. 명세의 긍부정 라벨·가능성 표현 병존은 팀 확인 대상이며 이 문서가 승인이나 투자 판단을 대신하지 않아요.

## 최종 확인 결과

- 전체 캡처는 **54묶음**, PPTX·PDF는 각각 **77쪽**이에요. 총 **186개 번호**, 화면당 **3~6개 조작**을 기록했고 다른 화면 이동 참조 **9개**도 이번 실행의 클릭 이력에서 확인했어요.
- 데스크톱·모바일 기업 전환은 실제로 삼성전자에서 NVIDIA로 이동하며 `period=1m`·`asOf=2026-09-30…`·`tab=events`를 유지했어요. 시간 버킷 선택은 `open`·`bucket`·`issue` 주소를 기록했고 차트 거래 바 선택은 `asOf=2026-09-14T00:00:00.000Z`로 바뀌었어요.
- 최종 PDF **77쪽 전체**를 렌더링하여 연락판 13장으로 검토했어요. 차트 번호와 관리자 사용량은 개별 페이지도 확인했어요. 덱 설명 글자 잘림·겹침·번호 위치 오류는 **0건**이에요. 차트의 기간 번호가 고정 헤더 뒤에 가리던 캡처 위치를 바로잡았고 모든 DOM 번호 대상의 가림 검사도 통과했어요.
- PDF 텍스트의 페이지 밖 돌출·줄 겹침 후보는 각각 **0건**, 글꼴은 모두 포함돼 있어요. `§`·`–`의 대체 글꼴 추출 상자 교차는 실제 줄 겹침과 구분해 기록했어요.
- 통합 문서 재생성은 **화면 77개·목표 API 84개**, OpenAPI 검증은 `OK`예요. `build.py --check`의 **hard error는 0건**이며 원문 충돌/미결정 경고 115건과 목표↔BFF 차이 168건은 그대로 남겼어요. 이 명령은 warning/difference만 있어도 exit 1을 반환하므로 exit 0과 hard error 0을 혼동하지 않아요.
- 마지막 실행 종료 후 8824·5194의 수신 프로세스가 없고 관리자 컨테이너 3개가 모두 `exited`임을 확인했어요. 수치·범위는 `captures/verification.json`에 기록했어요.

## 발견한 프로토타입 문제

프로토타입 소스는 수정하지 않았어요. 이번에는 목록 전환 없이 **삼성전자 지도 노드를 직접 선택해도**, 확대된 지도에 사건 라벨이 겹쳤어요. AI 질문 창을 열 때 배경 지도에도 겹침이 유지돼요. 근거는 `captures/D-GRP-03.png`·`D-AI-01.png`(PDF 31·49쪽)예요. 원본을 이미지 편집으로 보정하지 않았고 덱 조판의 글자 겹침과 별도 문제로 남겼어요.
