# 줍 화면계획서 v2.1 · 10-08 정합화

편집본은 `zoop-screen-plan-v2.1.pptx`, 배포본은 `zoop-screen-plan-v2.1.pdf`예요. 기존 **77쪽과 화면 ID**를 유지하고 2026-10-08 자료의 결정 상태·FS042 연결·공유 그래프 라벨 가독성을 반영해요. 실제 프로토타입을 조작한 화면이며 모의 계좌와 실제 기사 저장본을 사용해요. AI 답변은 생성형 모델 호출이 없는 규칙 기반 예시예요. 긍정/부정·회차 판단은 **디자인시스템 예시**이며 실제 데모 판정값은 없어요.

## 다시 만들기

저장소 루트에서 다음 명령을 실행해요. 새 패키지나 브라우저를 내려받지 않으며 `uv --offline`과 기존 캐시만 사용해요. 기존 웹 의존성(`prototype/web/node_modules`), LibreOffice, Playwright 1.61.0과 캐시 Chromium 1228(149.0.7827.55)이 필요해요. GraphLabelRepair의 공유 GraphCanvas 수정 완료 후에만 부분 캡처를 실행해요.

```sh
uv run --offline --with playwright==1.61.0 python docs/screen-plan/capture.py --manage-servers --state-source /tmp/zoop-state-plan-market --slides D-GRP-T D-GRP-T2 D-GRP-T3 D-GRP-T4 D-GRP-T5 D-GRP-01 D-GRP-01b D-GRP-02 D-GRP-03 D-GRP-04 D-GRP-05 D-GRP-06 D-GRP-07 D-GRP-07b D-COM-01 D-COM-01b D-COM-02 D-COM-03 D-COM-04 D-COM-05 D-COM-06 D-BRF-04 D-AI-01 D-AI-01b D-AI-02 D-AI-02b M-GRP-01 M-AI-01
uv run --offline --with python-pptx --with pymupdf --with pillow python docs/screen-plan/build_deck.py --pdf
open docs/screen-plan/zoop-screen-plan-v2.1.pdf
```

부분 캡처는 **기존 발행본을 가진 실제 기사 상태** `/tmp/zoop-state-plan-market`을 SQLite backup API로 새 `/tmp/zoop-screen-plan-*`에 복사해요. `--state-source`를 생략하면 공유 `prototype/bff/var`를 읽기 전용으로 복사해요. 원본 회차를 재발행하지 않으며 스케줄러는 명시적으로 `off`예요. 시장 시세 HTTP 조회는 있을 수 있지만 모델 실행·관리자 작업은 없어요. BFF 8824, Vite 5194, 브라우저 호스트 `plan.localhost`만 사용해요. 공유 8787/5173·공유 var는 수정하지 않아요. 소유 서버·브라우저와 격리 사본은 종료 시 정리해요.

`--slides`는 기존 manifest의 일반 화면 ID를 받아요. 지정한 화면의 이미지·metadata만 갱신하고 나머지는 보존해요. 그래프가 실제로 보이는 기업 상세·회차 지도·AI 배경·모바일 **28묶음**을 대상으로 해요. 초기 소비자 목록 31묶음 중 M-COM-01/M-COM-02/M-STK-01은 캡처에 그래프가 보이지 않아 작업 시작 전 이미지·metadata·manifest로 정확히 복원했고 최종 명령에서 제외했어요. 관리자 9개 화면과 컨테이너는 사용하지 않아요. 관심 종목만 갱신할 때는 `--slides D-WAT-01 D-WAT-01b`를 사용해요.

기존 시연 브리핑은 생성 경로로 재발행한 회차이며 실제 스케줄러의 과거 기록은 아니에요. 이번 정합화에서는 기존 발행본을 그대로 복사해요. 시장 HTTP 응답에 따라 시세·지연·실패가 달라질 수 있으므로 명령은 파일 바이트 고정이 아니라 화면과 동작 재현을 보장해요.

최종 `slide-index.json` 변경은 TraceReconcile/Main에게 전달해요. `docs/system/import_sources.py`와 통합 build는 그 담당자만 실행하며, 명세 10-08·WBS 10-08·요구 10-06 경로를 사용해요.

## v2.1 변경

- 독립 종목 메뉴 `D-STK-01`·`M-STK-01`: 목록·검색·상세 이동·관심 토글. 비회원의 시장 전체 열람도 확인해요. 지도 내부 목록 전환은 제거했어요.
- 기업 패널 `D-GRP-03`: 시세·작은 1개월 추이·접힌 주요 지표·모의 보유·사건·관련 기업·뉴스의 현재 화면을 사용해요.
- 기업 상세 `D-COM-03`~`06`: 좌측 기업 전환, 기업 중심 관계 그래프, 시간 버킷 선택 연동, 거래 바 선택에 따른 `asOf` 변경. 기간은 1일/1주/1개월/1년이며 출처 미지원 기간은 비활성 상태를 그대로 기록해요.
- 모바일 기업 전환 `M-COM-02`: 같은 상세 화면에서 전환 시트를 열어요. 하단 탭은 지도·종목·브리핑·AI·내 종목의 5개예요.
- 긍부정 `D-SEN-01`·`02`: 디자인시스템의 `SentimentLabel`·회차 판단 예시. 실제 데모 판정이나 주가 전망으로 설명하지 않아요. 판정 없는 영역은 숨기며 등락색·확률을 재사용하지 않아요.
- `HISTORY-21`·`APP-DOCS` 추가, `M-RULE-01`·`MAP-*`·`APP-ID` 갱신. 요구 번호는 10-06 정의서의 기능 의미 대응으로 갱신했어요.

## 10-08 정합화의 결정 상태

- `FS0??`는 `FS042 시점 기반 관계 그래프 조회`로 정리됐어요. `D-COM-04/05/06`의 현재 동작과 요구 41을 연결하며 **기존 FS042 재무와 의미 충돌**은 남겨요.
- 긍정/부정 명칭은 사용자 결정이며 혼재·판단 보류는 유지해요. API 공통 규칙은 **잠정 채택**이며 팀 최종 승인으로 쓰지 않아요.
- 판정 LLM 모델·추론 수준은 `.env`에서 관리하고 예산은 추후 결정해요. 실제 설정값은 열람하지 않았고 모델 호출은 하지 않아요.
- `FS074~FS081` 8개는 추가 제안·검토 전 / 우선순위 미정이에요. 확정 구현 행이나 신규 완료 기능으로 추가하지 않아요.
- Figma는 [대응 부록](wireframe-correspondence.md)에 raw node·현재 화면 ID·정적 검토·동작 관측·영향을 연결해요. **47 정적 / 2 상태 후보 / 5 독립 미수록**을 유지하며 예시 데이터와 전역 도형을 복사하지 않아요.
- 남은 명세/WBS/퍼센트/시점 동작 충돌은 작업자 가결정 → 시연 → 팀 최종 결정으로 처리해요. 우리 프로토타입/화면계획서가 현재 기준이에요.


## 캡처·검토 파일

- `capture.py`: 실제 로그인·초기 설정·튜토리얼·지도·종목·기업·AI·관리자·브리핑·모바일 조작.
- `captures/<ID>.png`·`.json`: 원본과 좌표, 번호 조작의 URL·화면 글자. 데스크톱 1440×900, 모바일 390×844의 `-before`·`-after` 쌍이에요.
- `captures/manifest.json`: 실제 캡처 내용. 덱은 `build_deck.py`의 `SCREEN_ORDER`로 화면 흐름에 맞춰 정렬해요.
- `captures/screen-details.json`: 화면별 3~6개 조작·구현 상태·코드 근거. 상태 칸은 이번에 캡처한 상태와 구현 상태를 구분해요.
- `captures/interaction-history.json`: 보존된 이전 이력 + **이번 부분 실행**의 실제 클릭 이력. 실행마다 덮어써서 과거 캡처의 관측 근거를 잃지 않아요.
- `captures/auth-proof.json`: 비회원 개인화·내 종목·AI 제한 및 공통 브리핑 열람·관리자 로그인 이동 결과.
- `captures/annotation-geometry.json`: 대상 상자와 번호 원의 최종 위치. 번호 원은 대상 밖에 배치해요.
- `captures/slide-index.json`: 모든 슬라이드의 쪽·ID·제목·라우트. 통합 문서 생성기의 화면 ID 출처예요.
- `captures/rendered/page-*.png`·`contact-*.png`: PDF 전 페이지 렌더와 6쪽 연락판.
- `captures/rendered/font-audit.json`: 페이지별 글꼴·포함 여부.
- `captures/verification.json`: 최신 실행의 수치와 렌더 검토·정리 결과.
- `captures/targeted-capture.json`: 이번 실행의 지정/갱신 ID·스케줄러 off·로컬 API 요청 경로·모델 호출 0·관리자 작업 0.
- `captures/revision-2026-10-08.json`: 이전 파일 sha256·화면 ID·원본 상태의 보존 대조와 FS042/결정 상태.
- `wireframe-correspondence.md`: 10-08 raw Figma node와 현재 화면 ID의 대응 및 상태 한계.

`captures/rendered/`는 빌드 생성물이며 `.gitignore` 대상이에요. PPTX에는 기존 SUIT Regular/Bold TTF를 EOT 컨테이너로 포함하고 OFL 1.1을 `ppt/fonts/LICENSE.txt`에 보존해요. [SUIT](https://sun.fo/suit/) · [EOT 구조](https://www.w3.org/submissions/EOT/Overview.html) · [LibreOffice embedded font import](https://github.com/LibreOffice/core/blob/master/oox/source/ppt/EmbeddedFontListContext.cxx).

## 문서 체계·근거 버전

- 기능 명세: `docs/evidence/raw/functional-spec_2026-10-08/`. FS042 정리와 검토 전 8개 제안 상태를 보존해요.
- 요구사항: `docs/evidence/raw/requirements-sheet_2026-10-06/1-요구사항-정의서.csv`. 10-08 재수집과 내용 동일해요.
- WBS: `docs/evidence/raw/wbs_2026-10-08/`. 본문·요약의 번호·담당·기간 충돌은 [10-08 delta](../evidence/doc-delta-2026-10-08.md)로 연결해요.
- 디자인: `docs/design/design-direction.md` §4.8·§5.3·§5.4·§5.7·§5.10, `docs/design/sentiment.md`.
- 목표 API: `docs/api/out/zoop-api-spec.md`(정본은 `docs/api/openapi.yaml`). 예시 화면 연결은 실제 API 실행·모델 판정을 증명하지 않아요.
- 통합 목록: `docs/system/out/index.md`. 화면↔기능↔API↔WBS↔구현 판정은 `docs/system/out/zoop-trace.xlsx`에서 확인해요.
- 팀 v1.7: `docs/evidence/screen-plan-v1.7-review.md` 머리 Main 정정 우선. 관리자 ID는 최종 42쪽의 5개 묶음을 유지해요.

## 검증 범위와 한계

관리자 캡처는 현재 상태와 메뉴 이동을 확인해요. 유료 작업·검수 허용·차단·정정·중단은 실행하지 않아요. AI 조회 오류는 질문 작업을 재실행하지 않고 대화 조회 응답만 503으로 차단해 재현해요. 실제 서비스 장애로 설명하지 않아요. 근거 접근 매트릭스는 문서·소스 규칙이며 모든 404/403/외부 원문 실패를 이번 캡처에서 재현한 것은 아니에요. 외부 원문 링크의 새 창 이동은 실행 관측 결과를 그대로 적어요.

가격·시장 지표는 외부 출처의 현재 응답이므로 과거 캡처와 값이 다를 수 있어요. 데모에는 실제 모델 판정값·시장 요약·재무 추이 생산자가 없으며 빈 영역에 값을 만들지 않아요. 긍정/부정 명칭은 결정됐지만 퍼센트 의미와 생산 정책은 시연 후 팀 확정 대상이에요. 이 문서가 승인이나 투자 판단을 대신하지 않아요.

## 10-06 기존 확인 결과

- 전체 캡처는 **54묶음**, PPTX·PDF는 각각 **77쪽**이에요. 총 **186개 번호**, 화면당 **3~6개 조작**을 기록했고 다른 화면 이동 참조 **9개**도 이번 실행의 클릭 이력에서 확인했어요.
- 데스크톱·모바일 기업 전환은 실제로 삼성전자에서 NVIDIA로 이동하며 `period=1m`·`asOf=2026-09-30…`·`tab=events`를 유지했어요. 시간 버킷 선택은 `open`·`bucket`·`issue` 주소를 기록했고 차트 거래 바 선택은 `asOf=2026-09-14T00:00:00.000Z`로 바뀌었어요.
- 최종 PDF **77쪽 전체**를 렌더링하여 연락판 13장으로 검토했어요. 차트 번호와 관리자 사용량은 개별 페이지도 확인했어요. 덱 설명 글자 잘림·겹침·번호 위치 오류는 **0건**이에요. 차트의 기간 번호가 고정 헤더 뒤에 가리던 캡처 위치를 바로잡았고 모든 DOM 번호 대상의 가림 검사도 통과했어요.
- PDF 텍스트의 페이지 밖 돌출·줄 겹침 후보는 각각 **0건**, 글꼴은 모두 포함돼 있어요. `§`·`–`의 대체 글꼴 추출 상자 교차는 실제 줄 겹침과 구분해 기록했어요.
- 최신 통합 문서 재생성 기준은 **화면/설명 슬라이드 77개·목표 API 86개**이며 OpenAPI 검증은 `OK`예요. `build.py --check`는 warning/difference만 있어도 exit 1을 반환하므로 exit 0과 hard error 0을 혼동하지 않아요. 경고와 목표↔BFF 차이는 삭제하지 않고 `docs/system/out/`에 생성 시점의 상세 결과를 남깁니다.
- 마지막 실행 종료 후 8824·5194의 수신 프로세스가 없고 관리자 컨테이너 3개가 모두 `exited`임을 확인했어요. 수치·범위는 `captures/verification.json`에 기록했어요.

## 발견한 프로토타입 문제

10-06 캡처에는 삼성전자 지도 노드를 직접 선택해도 확대된 지도에 사건 라벨이 겹쳤어요. AI 질문 창 배경에도 겹침이 유지됐으며 근거는 당시 `D-GRP-03`·`D-AI-01`(PDF 31·49쪽)이에요. 이번 10-08에는 GraphLabelRepair가 앱의 공유 라벨 선별·호버를 수정하고, 이 작업은 실제 UI를 재캡처해요. 이미지 편집으로 겹침을 가리지 않아요. 최종 관측 결과는 `captures/verification.json`에 기록해요.

## 10-08 최종 확인 결과

- GraphLabelRepair의 **캡처 가능 통지 후** 실제 기사 v1 사본에서 실행했어요. 그래프·노드 애니메이션이 끝난 뒤 LOD idle 140ms보다 긴 750ms를 기다렸어요.
- 부분 실행은 31묶음으로 성공했고, 직접 PDF 검토 후 그래프가 보이지 않는 모바일 3묶음을 원본으로 복원했어요. 최종 반영 대상은 **28묶음**, 실제 변경 PNG는 **22개**, bytes가 같은 PNG는 **38개**예요. 미선택/복원 **26묶음의 60개 PNG·JSON**과 원본 상태 DB·그래프 sha256은 모두 유지됐어요.
- 이미지가 실제로 바뀐 ID: `D-GRP-01/01b/T/02/03/05/06/07b`, `D-COM-01/01b/02/03/04/05/06`, `D-BRF-04`, `D-AI-01/01b/02/02b`, `M-GRP-01`, `M-AI-01`이에요. 튜토리얼 T2~T5와 경로 등 동일 bytes가 나온 이미지는 그대로예요.
- PPTX·PDF는 각각 **77쪽**, 기존 **77개 ID와 페이지 순서**가 같고 총 **186개 번호**를 유지해요. PDF에서 화면/설명/명세가 바뀐 쪽과 보존 복원 쪽 등 **37쪽을 직접 열어** 한글·번호 표식·화면 설명·FS042 충돌 고지·잘림을 확인했어요. 덱 텍스트의 페이지 밖 돌출·줄 겹침 후보는 각각 **0건**이고 글꼴은 모두 포함됐어요. 그래프 노드·간선 본체 교차는 별도 문제이며 0건이라고 주장하지 않아요.
- 실제 조작 경로: 삼성전자 노드 → 기업 패널 → 직접 이슈 → 근거; 두 기업 경로/포커스; 기업 상세에서 1·2단계 관계 보기; 버킷 선택의 `open/bucket/issue`; 거래 바 선택의 `asOf=2026-09-14T00:00:00.000Z`; 기업 전환 시 `period=1m/asOf/tab` 유지; 브리핑 퇴근 → `round=brf-2026-09-17-evening` 지도 → 원래 회차 복귀; AI 새 질문/되묻기/복구/조회 503 재현과 다시 확인; 모바일 기업 바텀시트/AI 탭을 눌렀어요. 개별 클릭 결과는 각 JSON에 있어요.
- 성공 실행의 브라우저 **로컬 API 요청은 2,490건**(GET 2,430 · POST 51 · PUT 9)이에요. 취소/503 재현 요청도 요청 수에 포함되며 외부 시장 HTTP 수와는 별개예요. 모델 호출·관리자 변경 작업·컨테이너 시작은 **0건**, 스케줄러는 `off`예요. 첫 실행은 helper의 모바일 before 별칭 누락으로 중단됐고 이를 수정한 뒤 성공했으며, 실패 실행을 무실패로 숨기지 않아요.
- 8824·5194의 LISTEN은 `lsof`에서 관측되지 않았어요(exit 1). 브라우저·소유 서버와 이번 격리 사본은 정리했으며 기존 LibreOffice profile과 읽기 원본은 유지했어요. 앱 build/test/lint·모델 실행·문서 통합 import/build는 이 작업에서 실행하지 않았어요. 최종 slide-index는 TraceReconcile에 전달했고 통합 재생성은 Main이 맡아요.
- 시세·평가액·조회 기준 시각은 캡처 날짜와 기간에 따라 달라요. 10-08 갱신 화면과 10-06 보존 화면의 실제 값을 Figma 수치에 맞춰 통일하지 않았어요. 원본 버전·기간·시각·sha256 및 최초 실패/최종 성공은 `captures/revision-2026-10-08.json`·`targeted-capture.json`·`verification.json`에서 확인해요.

### 최종 번호 설명 정정

Main이 발견한 D-GRP-03 번호 3의 설명을 **‘기업의 다른 이름을 펼쳐요’**로 바로잡았어요. 실제 클릭 기록의 열린 내용은 `Samsung Electronics · Samsung`이며 주요 지표가 아니에요. `screen-details.json`·개별 캡처 JSON·manifest를 함께 정정하고 덱을 다시 생성했어요. 이미지·번호 위치·CSS는 바꾸지 않았고 별도 재캡처나 API 요청도 하지 않았어요.

## 10-10 관심 종목 추천 제거

사용자 피드백(10-10)으로 초기 설정의 추천 종목 목록을 없앴어요. `/api/me/recommendations`는 보존하지만 화면은 요청하지 않아요. `capture.py`는 추천 행 대신 실제 검색(NVIDIA·SK·삼성)을 실행해 결과 행으로 4개를 고르고, 추천 영역이나 추천 요청이 보이면 실패해요. `--slides D-WAT-01 D-WAT-01b`로 두 화면만 다시 캡처했어요. `D-WAT-01`의 명세는 `FS011-01·FS012·FS013`이에요. 이 실행의 로컬 API 요청 26건 중 추천 요청은 0건이며 `targeted-capture.json`은 이 실행 기록으로 바뀌었어요. 10-08 실행 수치는 위 본문과 `verification.json`에 남아 있어요. 덱은 77쪽·186개 번호 그대로 다시 만들었고 21·22쪽(D-WAT-01/01b)에 새 캡처가 들어가요.
