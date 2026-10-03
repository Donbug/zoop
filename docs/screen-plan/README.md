# 줍 화면계획서 v2.0

편집본은 `zoop-screen-plan-v2.0.pptx`, 배포본은 `zoop-screen-plan-v2.0.pdf`예요. 화면은 실제 프로토타입을 눌러 캡처했으며, 모의 계좌와 실제 기사 39건의 저장본을 사용해요. AI는 생성형 모델 호출이 없는 규칙 기반 예시 답변이에요.

## 다시 만들기

저장소 루트에서 아래 3줄을 실행해요. Python 패키지는 `uv run --with`의 일회성 환경에만 설치돼요. 기존 웹 의존성(`prototype/web/node_modules`)과 LibreOffice, Playwright 1.61.0의 revision과 일치하는 캐시 Chromium 1228(149.0.7827.55)이 필요해요.

```sh
uv run --with playwright==1.61.0 python docs/screen-plan/capture.py --manage-servers --with-admin-containers
uv run --with python-pptx --with pymupdf --with pillow python docs/screen-plan/build_deck.py --pdf
open docs/screen-plan/zoop-screen-plan-v2.0.pdf
```

첫 명령은 공유 `prototype/bff/var`를 읽어 `/tmp/zoop-state-plan`에 복사하고, `rebuild_demo_briefings.py --source /tmp/zoop-state-plan --target /tmp/zoop-state-plan-market --from 2026-09-16`으로 새 회차를 만들어요. BFF 8824, Vite 5194, 브라우저 호스트 `plan.localhost`만 사용해요. 두 포트는 비어 있어야 해요. 성공·실패와 관계없이 이 명령이 띄운 서버 프로세스 그룹을 종료해요. 관리자용 `zoop-poc-postgres-1`·`zoop-poc-neo4j-1`·`zoop-poc-neo4j-real2`는 중지 상태였던 것만 시작하고, 끝나면 그 컨테이너만 정상 중지해요. 기존 볼륨·데이터는 삭제하지 않아요. 컨테이너 없이 부분 실패 화면을 확인하려면 `--with-admin-containers`를 빼요. 공유 데모 상태는 변경하지 않아요.

관심 종목 두 화면만 갱신하려면 첫 명령 대신 `uv run --with playwright==1.61.0 python docs/screen-plan/capture.py --manage-servers --slides D-WAT-01 D-WAT-01b`를 실행해요. 다른 캡처는 유지하고 해당 두 항목만 기존 manifest에 반영해요.

브리핑은 생성 경로로 다시 발행한 시연 회차이며, 실제 스케줄러의 과거 실행 기록이 아니에요. 지표는 회차 기준 시각 이전의 공개 자료예요. 외부 출처 응답에 따라 재현 때 값·지연·미제공·실패 상태가 달라질 수 있어요. 같은 화면·동작을 재현하는 명령이지 파일 바이트를 고정하는 명령은 아니에요.

## 캡처·검토 파일

- `capture.py`: 로그인·가입·초기 설정·튜토리얼·지도·기업·AI·관리자·브리핑·모바일을 실제로 조작해요.
- `captures/<ID>.png`와 `.json`: 1440×900 원본, 선택자별 좌표, 클릭 후 URL·화면 글자. 모바일은 390×844의 `-before`·`-after` 두 장이에요.
- `captures/manifest.json`: 캡처 순서와 내용. 덱은 `build_deck.py`의 `SCREEN_ORDER`로 화면 흐름에 맞춰 재정렬해요.
- `captures/auth-proof.json`: 비회원 개인화·내 종목·AI 제한, 공통 브리핑 열람, 관리자 로그인 이동의 실제 결과.
- `captures/screen-details.json`: 화면별 주요 조작·구현 상태·기존 상태 캡처·코드 근거.
- `captures/interaction-history.json`: 실제로 수행한 조작 이력. 이미 확인한 이동을 참조하는 번호도 이 이력과 맞아야 통과해요.
- `captures/annotation-geometry.json`: 2px 대상 상자와 32px 번호 원의 최종 위치. 번호는 상자 밖에 두고 겹치면 자동으로 비켜요.
- `build_deck.py`: 캡처 좌표로 번호 원을 올리고, 16:9 PPTX와 LibreOffice PDF를 만들어요.
- `captures/slide-index.json`: 모든 슬라이드의 쪽·ID·제목·라우트.
- `captures/rendered/page-*.png`: PDF 모든 페이지를 렌더링한 이미지.
- `captures/rendered/contact-*.png`: 6쪽씩 모은 전체 배치 검토 이미지.
- `captures/rendered/font-audit.json`: PDF 페이지별 글꼴 이름·포함 여부.
`captures/rendered/`는 빌드할 때 다시 만드는 생성물이며 `.gitignore` 대상이에요.

SUIT 시스템 설치가 없어도 읽히도록 프로젝트에 이미 있는 SUIT Regular/Bold TTF를 EOT 컨테이너로 PPTX에 포함해요. 원본 폰트 바이트는 바꾸지 않아요. 글꼴 저작권·OFL 1.1은 PPTX 내부 `ppt/fonts/LICENSE.txt`에 보존해요. 참고: [SUIT](https://sun.fo/suit/), [EOT 구조](https://www.w3.org/submissions/EOT/Overview.html), [LibreOffice embedded font import](https://github.com/LibreOffice/core/blob/master/oox/source/ppt/EmbeddedFontListContext.cxx).

## 근거 버전

- 기능명세 v1.2: `docs/evidence/raw/functional-spec_2026-10-01/` + 10-03 채택 항목 `docs/evidence/spec-v1.2-gap.md` §0.3.
- 요구사항 번호: `docs/evidence/raw/requirements-sheet_2026-10-01/1-요구사항-정의서.csv`의 ID 열. 번호가 비어 있는 사이드바·관심 수정 행은 임의 번호를 만들지 않아요.
- Notion: `docs/evidence/raw/notion_2026-10-03/`, 요약 `docs/evidence/notion-delta-2026-10-03.md`.
- 명세 충돌: `docs/evidence/spec-wbs-delta-2026-10-03.md`.
- 팀 v1.7: `docs/evidence/screen-plan-v1.7-review.md` 머리의 Main 정정 우선. 관리자 ID는 v1.7 42쪽의 최종 5개 묶음이에요.
- 디자인: `docs/design/tokens.json` v3.0.0, `docs/design/design-direction.md` §5·§6.3. 역사적 §9의 07:30/18:30·비회원 AI 문구는 현재 규칙으로 채택하지 않았어요.

## 검증 범위와 한계

번호 설명은 JSON의 `clickEvidence`와 대조할 수 있어요. 주요 조작은 화면당 3~6개이며, 다른 화면에서 이미 확인한 이동은 실제 클릭 이력과 해당 화면 ID를 함께 참조해요. AI 조회 오류는 질문 작업을 재실행하지 않고 대화 조회 응답만 503으로 차단해 재현했어요. 실서비스 장애라고 표현하지 않았어요. 상태 칸은 구현 범위를 적고, 기존 `docs/design/v5|v6|v7/` 캡처 또는 코드 파일을 근거로 표시해요.

관리자 캡처는 현재 상태와 메뉴 이동을 확인했어요. 유료 작업·검수 허용·차단·정정·중단 변경은 실행하지 않았어요. 관리자 권한 등급·대화록 별도 열람 권한·목적·실패 차단, 허용 후 재검증은 팀 결정이 필요해요. 근거 접근 상태 매트릭스는 문서·소스 규칙이며 모든 404/403/외부 원문 실패를 이번 캡처에서 재현한 것은 아니에요.
외부 원문 링크는 실제로 눌렀지만 이 브라우저 실행에서는 새 창 이동을 관측하지 못했어요. 링크 주소와 관측 결과를 기록했으며, 새 창 열림을 확인한 것으로 쓰지 않았어요. 앱이 외부 원문 사이트의 접근 성공·실패를 검사하는 것은 아니에요.

## 확인 결과

- PPTX·PDF 각 **65쪽**이며, 명세의 최소 화면 ID를 모두 포함했어요. 세부 상태를 나눈 추가 화면도 들어 있어요.
- 화면 **45묶음**, 화면당 주요 조작 **3~6개**, 총 **159개 번호**를 기록했어요. 그중 **14개는 이번 실행에서 확인한 이동을 다른 화면 ID로 참조**해요. 데스크톱 1440×900, 모바일 390×844를 사용했어요.
- 위 캡처→빌드 명령을 다시 실행해 같은 65쪽 덱을 재생성했어요. 이후 지도는 노드를 직접 눌러 캡처했으며, 마지막 실행도 45묶음 저장과 정상 종료를 마쳤어요.
- PDF 65쪽을 모두 PNG로 렌더링해 페이지별로 검토했어요. 마지막 연락판 11장과 수정한 지도·AI·라우트 표의 개별 이미지도 다시 확인했어요. 덱 설명 글자의 잘림·겹침, 빈 슬라이드, 번호 원 위치 오류는 없어요. 웹 화면의 자연스러운 스크롤 경계·말줄임은 원래 캡처 그대로예요.
- 실제 PPTX의 대상 외곽 상자·번호 원 159개를 좌표 JSON 및 `annotation-geometry.json`과 대조했어요. 번호 원은 대상 상자와 겹치지 않고, 충돌하면 자동으로 비켜요. 최소 ID 포함 여부·화면 흐름 순서·16:9 비율·글자 페이지 밖 돌출 0건을 확인했어요. 모든 PDF 글꼴이 포함되어 있고 SUIT Regular/Bold를 확인했어요. `§`·`–`의 인라인 대체 글꼴 추출 상자 교차는 실제 줄 겹침과 구분해 기록했어요.
- `captures/verification.json`에 수치·확인 범위를 보존했어요. 끝난 뒤 8824·5194에 수신 중인 프로세스가 없고, 위 컨테이너 3개가 모두 `exited`인 것을 확인했어요.

## 발견한 프로토타입 문제

프로토타입 코드는 수정하지 않았어요.

- 목록에서 기업을 고른 뒤 그래프로 바꾸면, 선택 기업 주변 사건 라벨이 겹쳤어요. 그 상태에서 AI 창을 열었을 때도 뒤쪽의 흐리게 표시한 지도에 라벨 겹침이 남았어요. 관측 당시 원본은 `captures/observations/company-list-switch-label-overlap.png`·`ai-background-label-overlap.png`에 보존했어요. 본문 캡처는 목록 전환 대신 지도 노드를 직접 누르는 정상 탐색 경로로 만들며, 원본 화면을 이미지 편집으로 보정하지 않아요.
