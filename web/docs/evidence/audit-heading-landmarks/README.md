# 작업 2: 제목 계층·본문 랜드마크 검증 (F3·F4)

기준 main: `bcbaa392` (#419 병합), 2026-10-29. D-AUT-02와 D-COM-01의 의미 구조만 보정합니다.

- F3: 약관에만 `MarkdownContent headingOffset={1}`을 적용합니다. h1→h2, h2→h3이며 h6에서 제한합니다. 기본 offset은 0이라 기존 사용 방식은 유지합니다. 원문·문구·클래스·API 값은 변경하지 않습니다.
- F4: 기업 상세의 안쪽 main을 동일 클래스의 div로 변경합니다. AppLayout의 `main#service-main`, 기존 section·h1·포커스 대상은 유지합니다.
- RouteError 확인: 404는 App.tsx의 최상위 `*` 경로에 있고 오류 대체 화면도 레이아웃을 대체합니다. AppLayout main 안에 중첩되지 않으므로 수정하지 않았습니다.

## 화면 비교

Chrome 1440×1000, 라이트·다크. 브라우저에서 실제 클릭으로 약관 두 개를 펼쳤습니다. HTTP 응답만 고정된 합성 fixture를 사용했고 제품 DOM·CSS는 조작하지 않았습니다. 약관과 기업 이름·출처에는 합성임을 표시했습니다. 실제 회원·계좌·인증 값·운영 데이터는 없습니다.

| 화면              | 수정 전                             | 수정 후                            | 의미 구조           |
| ----------------- | ----------------------------------- | ---------------------------------- | ------------------- |
| 약관 펼침, 라이트 | [전](before-signup-light-1440.png)  | [후](after-signup-light-1440.png)  | h1 3→1, main 1 유지 |
| 약관 펼침, 다크   | [전](before-signup-dark-1440.png)   | [후](after-signup-dark-1440.png)   | h1 3→1, main 1 유지 |
| 기업 상세, 라이트 | [전](before-company-light-1440.png) | [후](after-company-light-1440.png) | main 2→1, h1 1 유지 |
| 기업 상세, 다크   | [전](before-company-dark-1440.png)  | [후](after-company-dark-1440.png)  | main 2→1, h1 1 유지 |

네 쌍 모두 수정 전후 PNG SHA-256이 같으며, 제목의 글자 크기·굵기·좌표·크기도 같습니다. 대비·레이아웃 변경은 없습니다. `comparison.json`과 전후 `*-measurements.json`에서 확인할 수 있습니다. 캡처에 필요한 모든 API 요청에 합성 응답이 대응했고 미대응 요청은 없습니다.

## 회귀 확인

- 수정 전 신규 검사 5건 실패·기본 Markdown 검사 1건 통과를 확인했습니다.
- 수정 후 관련 5파일 82테스트가 통과했습니다. 약관 펼침, 기본 Markdown 제목 계층·스타일 유지, 임베디드 제목의 h6 제한을 확인합니다.
- 기업 상세 사건·문서·기업 정보 탭마다 main 1개와 SkipLink의 `service-main` 포커스 이동·주소 hash 미변경을 확인합니다.
- 최종 타입·린트·포맷·빌드·전체 Vitest 실행 결과는 PR Evidence에 기록합니다.

원본 근거는 `taste-audit-report-2026-10-29.md`의 F3·F4, `manual/manual-checks.json`, D-AUT-02/D-COM-01 와이어프레임입니다. 임베디드 약관은 페이지의 하위 콘텐츠이며, main 랜드마크는 앱 셸이 소유합니다.
