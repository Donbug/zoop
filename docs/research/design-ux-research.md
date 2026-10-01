# 줍(Zoop) 디자인·UX 리서치 v0.1

| 항목 | 내용 |
|:--|:--|
| 작성일 | 2026-09-29 |
| 범위 | 국내외 핀테크·증권 앱 UX, 브리핑형 콘텐츠, 지식 그래프 시각화, 금융 규제·신뢰 UX, 한국 시장 시각 언어, 접근성, 디자인시스템 구축 방식 |
| 목적 | 프론트엔드 프로토타입 착수 전 **권고(컴포넌트·토큰·패턴 수준)** 확정 근거 확보 |
| 연결 요구사항 | `docs/evidence/raw/requirements_v0.2.md` FR-14~FR-42, FR-43~FR-50, NFR-01/08/09/12/13 |
| 표기 | 사실(출처 확인) / `[추론]`(원문에 없는 해석) / `[미확인]`(근거 확보 실패) |

## 0. 방법과 한계

- **수집 방법**: 웹 검색으로 후보를 찾고, 1차 출처(제품 공식 문서, 법령·감독당국 보도자료, 프로젝트 공식 블로그·고객사례)를 직접 열람해 인용했다. 언론 보도는 1차 자료가 없을 때 보조 근거로만 사용했고 그 사실을 각 항목에 명시했다.
- **한계 1**: 금융위원회 「금융분야 인공지능 가이드라인」 **첨부 PDF 본문은 확보 실패**. `fsc.go.kr` 첨부 파일이 `application/octet-stream` 바이너리로만 반환되어, **보도자료 요약표(7대 원칙)까지만 근거로 사용**했다.
- **한계 2**: 국내 증권사 앱의 화면 세부(간격·컴포넌트 명세)는 **실기기 조작 관찰이 아니라 공식 보도자료·기술블로그 기반**이다. 화면 구조 수준의 사실만 인용하고, 세부 UI는 `[추론]`으로 표시했다.
- **한계 3**: 가격·플랜(Figma 등)과 라이브러리 버전은 조회 시점(2026-09-29) 기준이며 변동될 수 있다.

---

## 1. 국내 핀테크·증권 앱 UX와 디자인시스템

### 1.1 토스 (TDS·UX 라이팅)

- **TDS(Toss Design System)** 는 "토스 커뮤니티 전반에서 쓰는 디자인 시스템"이며, 앱인토스 개발자센터는 핵심 컴포넌트 11종(Badge, Border, BottomCTA, Button, Asset, ListRow, ListHeader, Navigation, Paragraph, Tab, Top)을 공개한다([TDS — 앱인토스 개발자센터](https://developers-apps-in-toss.toss.im/design/components)). 같은 문서는 "커스텀 UI를 직접 만들 때보다 3~5배 빠르게 개발할 수 있다"는 효과를 제시한다. **단, 사용 권한은 "앱인토스 서비스를 제공하기 위한 제한적 권한"이며 지식재산권은 토스에 있다** — 즉 줍은 TDS를 그대로 가져다 쓸 수 없다.
- TDS 색상은 값이 아니라 **이름 기반 토큰**으로 노출된다: `@toss/tds-colors` 패키지의 `colors.blue500` 식([TDS Mobile — Colors](https://tossmini-docs.toss.im/tds-mobile/foundation/colors/)). 이름 규칙은 `{색상}{단계}`로, 다크모드·리브랜딩 시 값만 교체하는 구조다.
- **UX 라이팅 규칙**이 명문화되어 있다: ① 모든 문구 해요체 ② 능동형 ③ 긍정형(없어요 → 있어요) ④ 과도한 경어 제거 ⑤ `{명사}+{명사}` 회피(한자어 풀어쓰기), 그리고 **다이얼로그 왼쪽 버튼은 [닫기]로 통일**(‘취소’는 작업 취소로 오해) ([앱인토스 UI/UX 가이드](https://developers-apps-in-toss.toss.im/design/consumer-ux-guide.md)).
- 같은 문서에 **다크패턴 방지 정책 5종**이 "출시 불가" 사례로 열거된다: 진입 즉시 전면 바텀시트, 뒤로 가기 차단 바텀시트, 탈출 선택지 없음, 예상 밖 전면 광고, CTA만으로 다음 행동 예측 불가.
- 토스 UX Writer 인터뷰에서 밝힌 **North Star는 "Zero Jargon"**(금융 전문용어 전면 교체)이며, 실무적으로는 ① Writing Principle 같은 **가이드라인**과 ② 그것을 TDS 컴포넌트 안에 심는 **시스템화**를 분리한다. 인터뷰는 "도구 안에서 더 좋은 문구를 고를 수 있게" 만드는 것이 목적이라고 설명한다([토스피드 — UX Writing](https://toss.im/tossfeed/article/uxwriter-interview)). 같은 글은 인터콤 리서치를 인용해 상위 앱 UI에서 **텍스트 비중이 30~40%**(페이팔 47%)라고 적는다.
- 토스증권은 커뮤니티 디자인 조직에서 유일하게 **UX R&D팀**을 둔다고 소개한다("어려운 투자를 쉽게 풀어…") ([토스 커리어 — 토스증권 UX R&D팀](https://toss.im/career/article/secu_ux_rnd)).

### 1.2 뱅크샐러드 (BPL)

- 뱅크샐러드는 Design System을 넘어 **Product Language(BPL)** 를 표방한다. 핵심 규칙은 **Container / Element / Child** 3분류로, Child는 "해당 부모 Container 내에서만 swap 가능"하도록 제약해 디자이너 의도 밖 조합을 막는다([Banksalad Product Language는 어떻게 디자인되었나요?](https://blog.banksalad.com/tech/banksalad-product-language-design/)).
- 컴포넌트 네이밍은 `고유번호_Category/(Type)/Name` 규칙이고, **개발 가이드(맞춤법)** 와 **사용자 가이드(문법)** 를 분리 운영한다. 또한 **비(非)디자이너를 위한 BPL Template**(drag&drop으로 화면 조립) 을 별도로 만들었다는 점이 이 팀에 특히 중요하다.
- 성과 지표가 구체적이다: 컴포넌트 642개(+47%), 신규 제작 136개/월 → 13개/월, **기존 컴포넌트 재사용률 43% → 85%**, 설문 기준 **1인당 월 38.5시간 절감**(같은 글).

### 1.3 카카오페이 / 카카오페이증권

- 카카오페이는 홈 화면을 **사용 습관 기반 자동 배치**로 개편했다: 송금은 상단, 결제는 하단, 바로가기 메뉴는 "평소 자주 사용하고 필요한 기능 중심"으로 추천한다([카카오페이 블로그 — 맞춤형 홈 화면](https://story.kakaopay.com/121-kakaopay-home-2/)).
- 카카오페이증권은 **보유 자산 중심**으로 증권홈을 개편하고(주식·연금·펀드·미니금고 잔고 한눈에), 하단 메뉴명을 '주식'에서 '증권'으로 바꿨으며, 미국주식 10호가·호가터치 주문을 추가했다([ZDNet Korea — 카카오페이증권 증권홈 개편](https://zdnet.co.kr/view?no=20241226212205)). 종목 화면 하단에 **정보·차트·호가·보유·주문 탭**을 두는 구조도 보도되었다([비즈니스포스트](https://www.businesspost.co.kr/BP?command=article_view&num=318612)).
- 보도 수준이지만 중요한 신호: 카카오페이증권 MTS가 토스증권과 홈·발견·자산 화면 및 하단 메뉴까지 유사하다는 지적이 있었다([이데일리 — MTS 유사성 논란](https://www.edaily.co.kr/News/Read?mediaCodeNo=257&newsId=02069686645511568)). `[추론]` 이는 국내 MTS가 이미 **수렴된 표준 패턴**(하단 탭 + 종목 상세 세그먼트 탭 + 보유 중심 홈)을 공유한다는 뜻이며, 줍이 새 정보구조를 발명할 필요는 낮다는 근거가 된다.

### 1.4 네이버페이 증권

- 마이데이터 연계가 개인화의 축이다. 계좌를 연결하면 **보유 종목 페이지 상단에 '보유' 표시**, 토론방 게시물에 **'주주' 표시**(주주 게시물만 모아보기), 종목 페이지 하단에 **'내 주식'(수익률·평균 매수가격, 계좌별 현황)** 이 노출된다. 국내 27개 증권사 계좌 연결이 가능하다([네이버 주식회사 보도자료, 2023-09-21](https://www.navercorp.com/media/pressReleasesDetail?seq=31285)).
- `[추론]` 줍의 "보유/관심 종목 맥락"은 네이버페이 증권의 **동일 종목 화면에 개인 맥락을 얹는 방식**(배지 + 하단 내 정보 블록)이 참고 모델이며, 별도 "내 자산" 화면 분리보다 정보 탐색 효율이 높다.

### 1.5 키움 영웅문S#

- 2026-09-08 일반모드 홈을 전면 개편해 **주식·커뮤니티·상품·혜택 4개 메뉴**로 정리했고, '지금 이 순간'(조회수·매수·등락률)과 **장 초반·마감 AI 시황**을 제공한다. 자주 쓰는 메뉴를 홈에 직접 배치·순서 변경하는 **'서비스 바로가기'** 기능도 있다. 커뮤니티 메뉴에는 **증권사 리포트를 AI로 요약한 '키움증권알리미'** 가 실시간 노출된다([머니투데이, 2026-09-08](https://www.mt.co.kr/stock/2026/09/08/2026090809473448605)).
- 초보 대응으로 **간편모드**를 별도 앱 설치 없이 앱 내에서 전환하도록 제공한다. 연합뉴스는 "딱딱하고 진지한 금융 앱의 분위기 대신 젊고 개성 넘치는 이미지와 애니메이션"으로 심리적 부담을 낮추는 것을 목표로 밝혔다고 전한다([연합뉴스, 2025-10-01](https://www.yna.co.kr/view/AKR20251001142600008)).

### ▶ 줍에 적용할 권고

| 항목 | 권고 |
|:--|:--|
| 토큰 | 색은 값이 아니라 **역할 이름**으로 정의: `--color-text-primary`, `--color-up`, `--color-down`, `--color-surface-raised`, `--color-border-subtle`. 단계형 팔레트는 `--blue-500` 식으로 별도 보관(토스 `colors.blue500` 패턴 차용) |
| 컴포넌트 | `ListRow`(기업 행: 종목명·현재가·등락률·보유배지), `Asset`(기업 로고/티커 배지), `BottomCTA`(설정 완료), `SegmentedTabs`(종목 상세 정보/차트/이슈) — TDS 공개 목록 중 줍에 필요한 것만 자체 구현 |
| 정보구조 | 온보딩은 **3스텝 이내**: ① 시작 모드(보유/관심) ② 종목 선택(1~3개, FR-11) ③ 완료. "건너뛰기"를 모든 스텝에 상시 노출(FR-14의 "튜토리얼 강제 금지"와 동일 원칙) |
| 용어 풀이 | `TermGlossary` 툴팁 컴포넌트 + **첫 등장 시 1줄 인라인 설명**(예: "공시 — 회사가 의무적으로 공개하는 주요 정보"). Zero Jargon 원칙을 채택하되, 대체어가 없는 법정 용어는 괄호 병기 |
| 라이팅 | 토스 규칙 4개를 그대로 팀 규칙으로 채택: 해요체 / 능동형 / 긍정형 / `{명사}+{명사}` 회피. 다이얼로그 왼쪽 버튼은 **'닫기'** 로 통일(FR-13 취소 규칙과 정합) |
| 다크패턴 | 앱인토스 5개 금지 사례를 **디자인 리뷰 체크리스트**로 복사. 특히 "진입 즉시 바텀시트"는 알림 동의·튜토리얼·면책 고지 모두에 적용 금지 |
| 개인 맥락 | 네이버페이 증권 방식 채택: 기업 패널 상단에 `보유` 배지, 하단에 "내 보유 기여도"(FR-20) 블록. 별도 자산 화면은 만들지 않음 |
| 홈 | 4블록 이내 + 사용자 커스터마이즈(영웅문S# '서비스 바로가기') — 프로토타입에서는 **순서 변경만** 허용하고 신규 블록 추가는 비활성 |

---

## 2. 해외 레퍼런스: 투자 앱·AI 뉴스 요약·출처 표시

### 2.1 Robinhood

- 접근성 설정이 제품 기능으로 들어가 있다: 테마(light/dark/**market hours**/system), **Accessible colors 토글(적록 색각이상 대응)**, 그리고 **Appearance preview**(선택한 테마가 그래프·텍스트·이미지에 어떻게 적용되는지 미리보기). 반면 "앱이 기기 텍스트 크기 설정을 아직 따르지 않는다"고 명시해 한계도 공개한다([Robinhood — Accessibility options](https://robinhood.com/us/en/support/articles/accessibility-options/)).
- 콘텐츠 규격을 디자인시스템에 통합한 사례가 있다. 디자인시스템 **Bento**에 Content Standards를 심으면서 ① 컴포넌트 플레이스홀더 텍스트를 가이드 문구로 교체 ② 컴포넌트별 best practices/mechanics/길이/Do & Don't 추가 ③ **에러 메시지·CTA 콘텐츠 패턴**을 별도 정의했고, 연간 설문에서 **제품 디자이너 88%가 유용하다고 응답**했다([Robinhood Newsroom — Integrated Content Standards](https://robinhood.com/us/en/newsroom/the-power-of-integrated-content-standards/)).

### 2.2 AI 요약의 표준 형태와 실패 사례

- **Bloomberg**: 2025-01-15 Terminal 뉴스에 **3개 불릿 AI 요약** 도입([Bloomberg Press](https://www.bloomberg.com/company/press/bloomberg-launches-gen-ai-summarization-for-news-content)). 그러나 같은 해 NYT 보도에 따르면 **AI 요약에 대해 수십 건의 정정**이 발생했다([NYT, 2025-03-29](https://www.nytimes.com/2025/03/29/business/media/bloomberg-ai-summaries.html)).
- **Yahoo News "Key Takeaways"**: 사용자가 **"Generate Key Takeaways"를 눌러야 생성되는 opt-in** 방식이며, "기사 본문 텍스트만 사용해 인터넷 전체 정보를 끌어오지 않는다"고 설명한다. 담당자는 이를 **"replacement가 아닌 convenience feature"** 로 규정하고 사람 검수를 병행한다([Nieman Lab, 2025-06-05](https://www.niemanlab.org/2025/06/lets-get-to-the-point-three-newsrooms-on-generating-ai-summaries-for-news/)).
- **WSJ "Key Points"**: 3개 불릿 요약에 **"What's this?" 버튼**을 붙여 "AI 도구가 이 요약을 만들었고 편집자가 확인했다"고 고지한다. 담당자는 "**human-in-the-loop이 결정적**"이며 "오류율은 낮지만 0은 아니다"라고 밝힌다(같은 Nieman Lab 기사).
- **Bloomberg "Takeaways"**: 매우 짧은 기사에는 요약을 붙이지 않고, 속보·장문 기사에 선택적으로 적용한다(같은 기사).

### 2.3 출처·편향 표시 (Ground News)

- Ground News의 **Blindspot** 은 "정치적 색채가 있고 한쪽 스펙트럼 매체가 불균형적으로 다룬 뉴스"로 정의된다. 같은 주제 기사를 **그룹화한 뒤 매체 성향별로 정렬**하고, 불균형 보도는 별도 피드로 분류한다([About The Blindspot](https://ground.news/blindspot/about)).
- 매체 성향 등급은 제3자 평가를 사용하고 방법론을 공개한다([Ground News — Our Approach to Media Bias](https://ground.news/media-bias), [Rating system](https://ground.news/rating-system)). FAQ에서 "sensational/low factuality 기사가 왜 노출되냐"는 질문에 대해 **"온라인 에코챔버에 무엇이 도는지 투명하게 보여주는 것이 목적"** 이라고 답한다(About The Blindspot).
- **Perplexity Finance**: 인라인 출처 칩(도메인 +N), 사이드바 소스 목록, 선택 구간 "Check sources" 등 인용 UX를 갖췄다는 **2차 분석**이 있다([AI UX Playground — Perplexity Citations](https://www.aiuxplayground.com/teardowns/perplexity/citations/)). `[미확인]` Perplexity 공식 문서는 403으로 열람 실패.
- **Public.com**은 개별 종목 대신 **Themes**(산업·트렌드·사회적 원인 단위 묶음)로 탐색 진입점을 제공한다([Public.com — Themes](https://public.com/themes)).

### ▶ 줍에 적용할 권고

| 항목 | 권고 |
|:--|:--|
| AI 요약 카드 | 필수 4요소를 **한 카드 안에 고정 배치**: ① `AiBadge`("AI 요약") ② 근거 문서 수(`근거 3건`) ③ 생성 시각(기준: 수집 마감 시각) ④ `검증 상태` 배지(FR-43) |
| 요약 노출 방식 | Yahoo 방식 차용: 브리핑·기업 요약은 **기본 접힘 → "AI 요약 보기" 탭으로 펼침**. 펼친 상태에서 원문 링크·근거 리스트를 같은 카드 하단에 노출 |
| 고지 컴포넌트 | WSJ의 "What's this?"를 `AiDisclosureSheet`로 구현: 사용 모델(범위), 사용한 문서 범위, 사람 검수 여부, 알려진 한계, "요약은 원문을 대체하지 않습니다" 문장 |
| 출처 표시 | Ground News식 "출처 구성"을 국내 맥락으로 번안: 좌/우 대신 **매체 유형(통신사/경제지/방송/공시)** 분포 + **보도 시각 순 정렬**. FR-31(동일 사건 출처 묶음)과 결합 |
| 왜곡 방지 | 근거가 1건뿐인 사건은 `단일 출처` 배지 + "추가 확인 필요" 문구. 근거 0건이면 요약 자체를 생성하지 않음(FR-48 "근거 부족 시 판단 보류") |
| 테마 그룹핑 | Public.com Themes → 줍의 **이슈 클러스터 노드**(예: "AI 반도체", "전기차 보조금")로 구현하고, 노드 선택 시 소속 기업 리스트를 표시 |

---

## 3. 브리핑형 콘텐츠 UX (출퇴근 5분 소비)

### 3.1 스캔 가능한 구조

- Axios의 **Smart Brevity** 는 "The big picture / Why it matters / Go deeper" 같은 **고정 라벨 블록**으로 요약·맥락·심화를 분리하는 형식이며, 같은 체크리스트를 무료 PDF로 공개한다([Axios HQ — Smart Brevity Checklist](https://www.axioshq.com/hubfs/Solutions-and-Support-Resources/Smart%20Brevity%20Checklist.pdf), [Smart Brevity 101](https://www.axioshq.com/hubfs/smart-brevity-101.pdf)).
- Morning Brew류 뉴스레터의 디자인 관례는 "모든 섹션이 박스 안에 들어가고, 각 박스에 대문자 섹션 헤더"를 두는 방식으로 소개된다([Newsletter Operator — How to design a newsletter readers love](https://www.newsletteroperator.com/p/newsletter-design)). 이 매체의 소개 페이지들은 **읽는 시간(5 MIN READ)** 을 명시한다([Hark — Morning Brew Review](https://hark.news/newsletters/morning-brew-review)). `[미확인]` 위 두 곳은 2차 매체 리뷰다.

### 3.2 오디오 브리핑

- **Business Insider Audio Briefing**: AI 생성 음성으로 톱스토리를 요약하며 홈페이지의 **"Your Briefing" 아이콘**, 앱의 **"Listen to the morning headlines"** 로 진입한다. 실시간 갱신되며 홈과 앱 양쪽에서 접근 가능하다([Business Insider Help Center — Audio Briefings](https://businessinsider.zendesk.com/hc/en-us/articles/37472852715789-Audio-Briefings)).
- Google News가 Android에 'Listen' 탭 기반 오디오 브리핑을 도입했다는 보도가 있다([Business Standard, 2025-12](https://www.business-standard.com/technology/tech-news/google-rolls-out-news-audio-briefing-with-listen-tab-on-android-report-latest-new-summary-125121800582_1.html)). 보도 기반 정보로만 채택.

### 3.3 소요 시간 계산의 근거

- Brysbaert(2019)는 190개 연구·17,887명을 메타분석해 **영어 비문학 평균 묵독 속도 238 wpm**을 제시한다([Journal of Memory and Language 초록/ScienceDirect](https://www.sciencedirect.com/science/article/abs/pii/S0749596X19300786), [후속 인용 검증](https://www.tandfonline.com/doi/full/10.1080/10888438.2025.2612649)). `[추론]` 한국어는 음절 단위라 wpm을 그대로 쓸 수 없지만, **"본문 글자수 ÷ 500자/분" 같은 한국어 기준을 자체 캘리브레이션**하고 UI에는 계산식이 아니라 반올림된 "약 N분"만 노출하는 방식이 합리적이다.

### ▶ 줍에 적용할 권고

| 항목 | 권고 |
|:--|:--|
| `BriefingCard` 구조 | ① 헤더: `아침 브리핑`/`저녁 브리핑` + `기준 07:30 KST` + `약 3분` ② 본문: 3~5개 `BriefingIssueCard` ③ 푸터: `출처 12건 · 다시 보기` |
| `BriefingIssueCard` | 한 줄 요약(40자 이내) + 관련 종목 칩(최대 3) + 영향 방향 배지 + `근거 N건`. 길이 초과 시 접기 |
| 소요 시간 | 라벨은 `약 N분`, 60초 미만은 `30초 이내`. 계산 규칙은 토큰이 아니라 유틸 함수(`estimateReadingMinutes`)로 두고 본문·요약 각각 계산해 합산 |
| 읽음 상태 | 3상태: `미읽음`(점 표시) / `읽음`(제목 굵기 normal + 회색 처리) / `부분 읽음`. 로그인 시 서버 동기화(FR-12 설정 복원과 동일 저장 경로), 비회원은 `localStorage` |
| 진입 동선 | 홈 상단에 **브리핑 카드 1개**(아침/저녁 자동 선택, 시간대 기준 07:30 이전·이후 분기) → 상세에서 FR-40 후속 탐색 |
| 세그먼트 | FR-39의 관계도/요약 전환은 **상단 `SegmentedTabs` 2탭**(`관계도` / `요약`)으로 구현, 전환해도 선택 이슈 ID 유지 |
| 오디오 | **MVP 제외 권고**. AI TTS는 검수·고지·비용 부담이 크고, 대신 스크린리더 낭독이 자연스럽도록 DOM 순서를 요약→근거 순으로 고정 |
| 검증 배지 | FR-41 결과를 `일치`/`불일치`/`보류` 3종 배지로 표시하고, 각 배지 옆에 **판정 사유 툴팁**(평가 기간·근거 문서 ID) 부착 |

---

## 4. 지식 그래프·네트워크 시각화 UX

### 4.1 상용 그래프 도구가 실제로 채택한 패턴 (1차 문서)

**Neo4j Bloom**([Scene interactions](https://neo4j.com/docs/bloom-user-guide/current/bloom-visual-tour/bloom-scene-interactions/)) — 줍의 그래프 UX에 가장 직접적으로 이식 가능한 목록:

| 기능 | 문서상 동작 | 줍 대응 |
|:--|:--|:--|
| 빈 상태 | "Show a graph snippet" 또는 "Search the graph" 2옵션 | 그래프 모드 첫 진입 = 중심 종목/시장 스니펫 자동 표시 |
| 확장 | 우클릭 `Expand nodes`(즉시 이웃), 노드 수는 Settings의 **Node query limit**으로 제한. `Advanced expansion`은 관계 유형·방향·대상 노드 유형·반환 개수까지 지정 | "관계 1단계 펼치기" 버튼 + 반환 개수 상한(기본 10) |
| 정리 | `Select related nodes`, `Dismiss single nodes`(고립 노드 제거), `Reveal relationships`(숨은 간선 표시), `Group nodes/relationships`(묶어서 1개 노드로) | "관련 없는 노드 숨기기", "숨은 관계 보기", "동일 산업 묶기" |
| 경로 | `Shortest Path`(최대 20 hops, 첫 경로만 표시) | 기업 A→B 경로 찾기 |
| 레이아웃 | force 1(GPU, 조밀) / force 2(비GPU, 넓게) / hierarchical / coordinate / circular | 기본 force, "계층 보기" 토글 = 공급망 방향 이해용 |
| 탐색 보조 | 미니맵(전체 씬 + 현재 뷰포트, 드래그 팬), **Presentation mode**(검색·레전드 숨김), 줌 % 클릭 시 100% 리셋 | 미니맵 + 전체 보기(FR-19) |
| 필터 | 필터 적용 시 대상이 아닌 요소는 **회색 처리되고 상호작용 불가**, `Dismiss Filtered elements`로 완전 제거 가능. 시간 속성 필터는 타임존 정규화 옵션 제공 | FR-18의 D-06(숨김/흐림) 결정과 동일 축 |

**Kumu**([Focus 가이드](https://github.com/kumu/docs/blob/main/guides/focus.md)) — "포커스 + 차수(depth)" 패턴의 원형:

- 요소를 **클릭-홀드하거나 선택 후 포커스 아이콘**으로 나머지를 임시 숨김. `+`/`-` 로 차수를 확장·축소하고, 숫자 키로 차수를 직접 지정, `esc` 로 전체 복귀.
- `@settings { focus: #jack out 2 }` 처럼 **초기 포커스를 코드로 선언**할 수 있고, `focus-direction: in | out | all` 로 방향을 제한한다.
- **prompted mode**에서는 전체 지도 대신 검색 프롬프트를 먼저 보여주고, 입력한 요소 + 지정 차수(`out n`)만 그린다. 즉 **"전체 그래프를 먼저 그리지 않는" 기본값**을 선택할 수 있다.

**Obsidian**은 전역 `Graph view`와 `Local graph`를 **별도 뷰로 분리** 제공한다([Graph view](https://help.obsidian.md/plugins/graph), [local-graph](https://help.obsidian.md/plugins/local-graph)). `[추론]` 전역 그래프는 "지형 파악용", 로컬 그래프는 "탐색용"으로 역할을 나눈 것이며, 이는 줍의 "시장 전체 그래프(부분 그래프)"와 "자산 기반 그래프"를 **동일 컴포넌트의 두 모드**로 만드는 근거가 된다.

**Graphistry**는 GPU 기반으로 대규모 그래프를 브라우저에서 탐색하는 것을 제품 차별점으로 내세운다(50만+ 엣지/5만+ 노드 규모를 제품 페이지에서 주장) ([Graphistry GPU](https://www.graphistry.com/gpu), [Data Science 페이지](https://www.graphistry.com/data-science)). 수치는 2020년 시점 제품 주장이다.

**금융·공급망 도메인 사례**: BASF는 Neo4j 기반 WeDecide로 **15억 노드** 규모의 가치사슬을 모델링해 "주 단위 분석을 초 단위로" 단축했고, 2022년 유럽 가스 위기 당시 **가스 의존 제품·가치사슬 식별**에 사용했다([Neo4j 고객사례 — BASF](https://neo4j.com/customer-stories/basf/)). 반도체·소재 기업이 그래프를 쓰는 이유는 "노드가 아니라 연결에서 실패"하기 때문이라는 논변도 있다([Neo4j Blog — Supply chains don't fail at the node](https://neo4j.com/blog/graph-database/supply-chains-dont-fail-at-the-node-they-fail-at-the-connection)).

### 4.2 노드 과밀 대응 연구

- **에고 네트워크(ego network)** 표현 비교 연구는 "부분 그래프를 보여주는 방식" 자체를 비교 대상으로 삼는다([Me! Me! Me! A study and comparison of ego network representations, 2024](https://www.sciencedirect.com/science/article/pii/S0097849324002589)).
- 모바일 제약: Microsoft Research의 **Orchard** 는 모바일 폰에서 다변량 이종 네트워크를 탐색하는 기법을 제안한다([Microsoft Research — Orchard](https://www.microsoft.com/en-us/research/video/orchard-exploring-multivariate-heterogeneous-networks-on-mobile-phones-2)). **Chunky Chains**(2026)는 소형 화면용 그래프 드로잉 알고리즘을 다룬다([arXiv:2607.06029](https://arxiv.org/abs/2607.06029)). 모바일에서 간선의 시각 변수(색·굵기·패턴 등)를 비교한 실험도 있다([Büschel et al., MobileVis 2018 PDF](https://mt.inf.tu-dresden.de/cnt/uploads/mobilevis2018_bueschel.pdf)).
- `[추론]` 위 문헌들이 공통으로 시사하는 바: **작은 화면에서는 노드 수를 늘리는 것보다 "무엇을 보여주지 않을지"를 결정하는 규칙(차수·필터·그룹핑)이 성능보다 중요**하다.

### 4.3 그래프 접근성 (비시각 대안)

- 화면낭독 사용자 대상 **데이터 소니피케이션**은 "언제 쓰고 언제 쓰지 말아야 하는지"까지 연구되어 있다([Web4All 2025 — Data Sonification for Screen-Reader Users](https://dl.acm.org/doi/10.1145/3744257.3744263), [CHI 2023 — Accessible Data Representation with Natural Sound](https://dl.acm.org/doi/10.1145/3544548.3581087)).
- **Chart Reader**(CHI 2023)는 BLV(blind/low-vision) 스크린리더 사용자 10명과의 공동설계로 접근 가능한 시각화 경험을 만든 사례다([PDF](https://homes.cs.washington.edu/~jessejm/data/ThompsonMartinezCHI2023.pdf)).
- Zong 등(2022)은 스크린리더를 위한 **구조적 탐색 경험**(차트 요소를 계층적으로 탐색)을 제안한다([Computer Graphics Forum](https://onlinelibrary.wiley.com/doi/abs/10.1111/cgf.14519)). 모바일 터치 기반 접근성은 ChartA11y가 다룬다([arXiv:2410.20545](https://arxiv.org/html/2410.20545v1)).

### 4.4 웹 라이브러리 비교

| 라이브러리 | 라이선스 | 렌더링 | 성능 근거 | 레이아웃 | React 연동 | 비고 |
|:--|:--|:--|:--|:--|:--|:--|
| **Cytoscape.js** | MIT ([repo](https://github.com/cytoscape/cytoscape.js)) | Canvas(기본), 실험적 WebGL 디버그 페이지 존재 | 공식 성능 테스트 페이지가 200 → 20,000 노드 네트워크를 제공([js-perf](https://cytoscape.org/js-perf/)) | preset/null/random/grid/circle/concentric/breadthfirst/dagre/klay/cose/cose-bilkent/cola/euler/spread/springy/arbor | 코어는 프레임워크 비종속, 래퍼 서드파티 | 논문 기반(Oxford Bioinformatics), 그래프 알고리즘 내장, 확장 70+ |
| **Sigma.js + graphology** | MIT ([repo](https://github.com/jacomyal/sigma.js)) | WebGL | "수천 노드·엣지" 목표로 자기 규정, v4 alpha 진행 중 | graphology 레이아웃 생태계에 위임 | `sigma` + `graphology` 조합, 공식 React 데모 앱 제공 | 대규모 렌더링에 강점, 레이아웃은 별도 패키지 조합 필요 |
| **react-force-graph** | MIT ([repo](https://github.com/vasturiano/react-force-graph)) | Canvas(2D) / WebGL(3D) | 예제에 large-graph 제공 | `d3-force-3d` | **React 네이티브**(2D/3D/VR/AR 동일 API) | `click-to-focus`, `expandable-nodes` 등 줍이 필요한 예제가 이미 존재 |
| **vis-network** | Apache-2.0 또는 MIT 듀얼 ([repo](https://github.com/visjs/vis-network)) | Canvas | "현대 브라우저에서 수천 노드·엣지까지 부드럽게, 그 이상은 **클러스터링** 지원" | 자체 물리 레이아웃(계층형 포함) | 래퍼 필요 | 가장 빠른 도입, 대신 커스터마이즈·성능 상한 |
| **AntV G6** | MIT ([repo](https://github.com/antvis/G6)) | Canvas / SVG / WebGL (G 기반) | 10+ 레이아웃 중 일부 GPU·Rust 병렬 | 다수 | **React 노드 지원**, `Graphin` React 래퍼 | light/dark 테마 + 20여 팔레트 내장, 디자인 자유도 높음 |

`[추론]` 정리: **노드 30~50개 + 사용자 확장형 탐색**이 목표인 줍에서는 WebGL의 압도적 성능보다 **레이아웃 품질·상태 관리·대안 뷰 연동 용이성**이 결정 변수다. 10만 노드급은 이 서비스 범위가 아니다.

### ▶ 줍에 적용할 권고

**1) 노드 예산(budget)을 먼저 정한다**

- 기본 뷰: **중심 노드 1 + 1차 이웃 ≤ 12 + 이슈 노드 ≤ 6 = 20개 이내**. FR-16의 "시장 전체 = 핵심 이슈·대표 기업 부분 그래프"를 그대로 상한으로 사용.
- 확장 1회당 추가 노드 ≤ 8개, 전체 누적 상한 60개. 상한 도달 시 "노드가 많아요. 일부를 묶어서 볼까요?" 제안 → 그룹핑 유도.

**2) 과밀 대응 5패턴을 컴포넌트로 고정**

| 패턴 | 구현 | 참조 |
|:--|:--|:--|
| 포커스 + 컨텍스트 | 노드 선택 시 나머지 opacity 0.25, 선택 노드·직접 이웃만 원색 | Bloom Select related / Kumu focus |
| 에고 네트워크 | "이 기업 기준으로만 보기" → 선택 노드 기준 N홉만 남김 | Kumu `out n`, ego network 연구 |
| 그룹/병합 | 동일 산업·동일 이슈 사건 묶어 1노드로, 클릭 시 해제 | Bloom `Group nodes` |
| 시맨틱 줌 | 줌 < 0.6: 라벨 숨김(모양·색만), 0.6~1.2: 종목명, > 1.2: 종목명 + 등락률 | Bloom(줌에 따른 텍스트 크기 동적) |
| 간선 정리 | 관계 유형 토글(경쟁/공급/고객/협력/지분), 이슈-기업 간선은 선택 이슈 1개만 표시 | FR-22, FR-34 |

**3) 대안 뷰를 "기본 제공"으로**

- 그래프 캔버스 우상단에 **`목록으로 보기` 토글**. `RelationList`는 인접 리스트(선택 기업 → 관계 유형·방향·근거·검증 상태)를 DOM 리스트로 렌더. FR-39(관계도/요약 전환)와 동일 상태를 공유.
- 이슈는 `EventTimeline`(시간축)이 1차 뷰, 그래프는 2차 뷰로 뒤집는 것을 권고. `[추론]` 초보 사용자에게 그래프는 "탐색 도구"보다 "결과 요약"에 가깝다.

**4) 모바일 조작**

- 탭: 노드 선택 / 드래그: 팬 / 핀치: 줌. **확대·축소 버튼을 항상 병행 노출**(WCAG 2.5.7 Dragging Movements 대응, FR-19).
- 노드 탭 → 하단 시트(BottomSheet)로 `NodeInspector`(기업/이슈/관계 3종) 표시, 시트는 3단 스냅(peek 20% / half 50% / full 90%).
- 노드 지름 최소 **44×44 CSS px**(WCAG 2.5.8의 24px 최소보다 상향), 간선은 최소 1px + 선택 시 2px.

**5) 접근성**

- 캔버스에 `role="img"` + `aria-label`(예: "삼성전자 중심 관계 12개, 이슈 3개"), 바로 옆에 **`관계 목록` 링크**(스크린리더 경로).
- `NodeList`는 실제 `<ul>` + 로빙 tabindex로 키보드 탐색(↑↓ 이동, Enter 선택, Esc 해제=FR-14의 초점 복귀 원칙).
- 노드 클릭 → 패널 이동 시 **초점을 패널 첫 헤딩으로 이동**하고, 닫으면 원래 노드로 복귀(NFR-12).

**6) 라이브러리 추천**

| | 1안 (권고) | 대안 |
|:--|:--|:--|
| 선택 | **Cytoscape.js** | **Sigma.js + graphology** (성능 우선) 또는 **react-force-graph** (속도 우선) |
| 근거 | MIT, 공식 성능 테스트로 2만 노드까지 검증된 문서, 레이아웃 16종 내장(dagre/klay/cose 계열 포함), 그래프 알고리즘 내장(최단경로 등), 논문 인용 가능 | WebGL로 대규모 렌더링 우위(자기 규정 "thousands of nodes"), React 예제 코드 존재 |
| 트레이드오프 | Canvas 기반이라 노드 1만+ 에서는 WebGL 대비 열세, React 연동은 직접 래핑 필요 | WebGL 셰이더 학습 곡선, 레이아웃·알고리즘을 graphology 생태계에서 조립해야 함 → 노드 20~60개 규모에서는 이점이 거의 없음 |
| 비권고 | G6: 기능·테마 풍부하나 문서/예제 편차와 학습 비용. vis-network: 도입은 빠르지만 커스터마이즈·성능 상한이 낮음 | — |

---

## 5. 금융 서비스 규제·신뢰 UX

### 5.1 AI 생성 콘텐츠 표시 의무 (법률)

- **인공지능 발전과 신뢰 기반 조성 등에 관한 기본법(인공지능기본법)** 제31조([국가법령정보센터 조문](https://www.law.go.kr/LSW/lsLinkCommonInfo.do?chrClsCd=010202&lsJoLnkSeq=1031810727)):
  - ① 고영향·생성형 AI 기반 제품·서비스를 제공하려는 경우 **해당 AI에 기반해 운용된다는 사실을 사전 고지**
  - ② 생성형 AI 결과물이면 **생성형 AI에 의해 생성되었다는 사실을 표시**
  - ③ 실제와 구분하기 어려운 가상 음향·이미지·영상을 제공하면 **명확하게 인식할 수 있는 방식으로 고지 또는 표시**
- 시행 시점: [시행 2026. 7. 21.] [법률 제21311호, 2026. 1. 20., 일부개정](https://www.law.go.kr/LSW/lsLinkCommonInfo.do?chrClsCd=010202&lsJoLnkSeq=1031810727). 후속 제도(생성형 AI 표시 의무·고영향 AI 관리기준·AI 제품·서비스 확인제도)가 정비되었다는 보도도 있다([연합뉴스, 2026-07](https://www.yna.co.kr/view/AKR20260717029400017)).

### 5.2 금융분야 인공지능 가이드라인 (금융위원회)

- 금융위원회는 2026-06-18 「금융권 인공지능 전환(AX) 현장 간담회」에서 개정안을 발표하고 **7대 원칙**을 제시했다: ① 거버넌스 ② 합법성 ③ **보조수단성**(현 단계 AI는 업무의 보조수단, 최종 의사결정·책임은 임직원) ④ 신뢰성 ⑤ 금융안정성 ⑥ **신의성실**(금융소비자 이익 최우선) ⑦ 보안성. **시행 2026-06-22 예정**이며, 업종·업무와 무관하게 AI를 활용하는 모든 금융회사의 **자율규제**이고, **핀테크 기업 등 비금융회사도 AI 활용 결과가 금융거래 제공에 영향을 줄 수 있으면 적용 대상**이다. 고영향 AI 등은 인공지능기본법상 별도 법적 의무가 발생한다([금융위원회 보도자료, 2026-06-18](https://www.fsc.go.kr/no010101/87142)).
- `[미확인]` **개정판 7대 원칙 목록에는 '설명가능성'이 독립 항목으로 없다.** 표시·고지는 인공지능기본법 제31조가, 설명 책임은 ③보조수단성·④신뢰성 원칙이 담당하는 구조로 보이나, 상세 본문 확인 실패로 단정하지 않는다(부록 한계 참조). 참고로 이 개정은 2021년판 가이드라인을 대체하는 개정이며, 실무 해설은 [법률신문](https://www.lawtimes.co.kr/news/articleView.html?idxno=223136)과 [김·장 법률사무소 뉴스레터](https://www.shinkim.com/kor/media/newsletter/3142)에서 다룬다.

### 5.3 투자권유 오인·허위과장 광고 규제

- 금융투자회사는 투자광고 시 **금융소비자보호법(손실보전·이익보장 오인 표현 금지)** 과 **표시·광고의 공정화에 관한 법률(허위·과장 광고 금지)** 을 준수해야 하며, 협회가 투자광고를 심사한다. 단, **"한국금융투자협회 심사필 번호는 … 내용이 진실 또는 정확하다는 것을 인정하거나 보증하는 것이 아니다"** ([금융투자협회 — 불법광고 신고](https://www.kofia.or.kr/wpge/m_169/sub04070103.do)).
- 금감원은 2026-04-23 **'금투사 광고제도 개선 T/F'** 첫 회의를 열고 실제 위반 유형을 공개했다: 의무 표시사항(수수료 부과기준, 광고 주체, 투자 위험) 누락 / **미실현 수익률 표시**("커버드콜 ETF 연 15% 프리미엄 수익 목표") / 이익보장·손실보전 표현("따박따박 월세 같은") / **최상급 표현에 출처·비교범위 미표시**("글로벌 1위") / 월배당 ETF의 원금 감소 가능성 미기재([동아일보/뉴스1, 2026-04-23](https://www.donga.com/news/Economy/article/all/20260423/133796852/1); [파이낸셜뉴스, 2026-09-01](https://www.fnnews.com/news/202609011400105857) — 심사절차 강화 방향).
- 실제 제재 사례: 토스증권은 "엔비디아가 5% 오르면 옵션 가격은 214% 오른다" 같은 문구로 고위험 파생상품을 홍보해 논란이 되었고, 앞서 **미수거래를 '외상구매'로 표현해 금감원 시정명령**을 받았다(금융당국은 해당 표현이 **투자 위험을 과소평가하게 만들 수 있다**고 지적) ([조선비즈, 2025-11-06](https://biz.chosun.com/stock/stock_general/2025/11/06/H7NWI57LVNCPPGUZ4EEKO43D5M/)).

### 5.4 긍/부정 감성 표기의 오해 위험 (연구 근거)

- 금융 뉴스 감성 측정은 **부정어(negation) 범위** 처리가 핵심 난제이며, 이를 개선하면 감성-수익률 상관이 최대 10.63% 향상된다는 연구가 있다([Decision Support Systems — Negation scope detection in sentiment analysis](https://www.sciencedirect.com/science/article/abs/pii/S0167923616300823)).
- 금융 뉴스 감성은 **측정 방법(사전 기반 vs 신경망 vs 트랜스포머)에 따라 결과가 달라진다**는 비교 연구가 있다([arXiv — On Quantifying Sentiments of Financial News](https://arxiv.org/pdf/2312.14978), [Comparative Evaluation of Embedding Representations](https://arxiv.org/html/2512.13749v2)).
- 연준 연구는 뉴스 자체와 감성 지표를 분리해 예측력을 검증한다([FEDS 2016-048 — News versus Sentiment](https://www.federalreserve.gov/econresdata/feds/2016/files/2016048pap.pdf)). `[추론]` 즉 "긍정/부정"은 **관측된 사실이 아니라 모델의 산출값**이므로, UI에서 사실과 같은 위계로 표시하면 오해를 만든다. 이는 요구사항 NFR-08("사실과 영향 가설·불확실성을 구분. 주가 상승 확률로 표현하지 않음")과 정확히 같은 결론이다.

### ▶ 줍에 적용할 권고

| 항목 | 권고 |
|:--|:--|
| `AiBadge` | 모든 AI 생성 텍스트(브리핑 요약, 기업 요약, 이슈 요약, 챗 답변) 좌상단에 고정. 문구는 `AI 요약` + 아이콘. 색만으로 구분 금지(테두리 + 텍스트) |
| `AiDisclosureSheet` | "이 요약은 어떻게 만들어졌나요?" → ① 사용 모델·버전 ② 입력 범위(문서 N건, 수집 마감 시각) ③ 사람 검수 여부 ④ 알려진 한계 ⑤ "요약은 원문을 대체하지 않습니다". 인공지능기본법 제31조 ①② 대응 |
| 감성 표기 | 라벨을 `긍정/부정`이 아니라 **`호재 가능성` / `악재 가능성` / `혼합` / `판단 보류`** 로 변경(FR-23의 4분류와 이미 일치). 각 라벨 옆에 **근거 인용 구간 링크 필수**(FR-44) |
| 근거 없는 주장 금지 | 요약 문장 중 근거 ID가 매핑되지 않은 문장은 렌더하지 않거나 `근거 없음` 표시. "확률/목표가/예상 수익률" 표현은 전 화면 금지(NFR-08, 금감원 지적 유형) |
| 투자권유 오인 방지 | ① 요약·브리핑 카드 하단에 1줄 고지: `이 정보는 참고용이며 투자 권유가 아닙니다` ② 앱 전체 푸터 고정 고지는 **하지 않음**(스크롤 무관 노출은 오히려 무시됨) ③ "매수/매도"·"지금이 기회"·"바겐세일" 등 권유성 카피 금지 목록을 디자인 리뷰 체크리스트에 등록 |
| 최상급·수치 표현 | "1위", "최고" 사용 금지(불가피하면 출처·비교범위·기준일 병기). 시세·등락률은 **기준 시각 + 지연 여부** 상시 표기(NFR-09) |
| 책임 구조(보조수단성) | AI 답변 UI에 "최종 판단은 사용자" 문구를 두고, 앱이 추천·주문을 유도하는 CTA(매수 버튼 등)를 **AI 답변 영역에 두지 않는다** |

---

## 6. 한국 시장 관례와 시각 언어

### 6.1 상승 빨강 / 하락 파랑

- 한국거래소 공식 표기 관례가 **상승=빨강, 하락=파랑**이라는 보도가 있다. 미국과 반대인 이유로는 다우존스 초기 시세 전달 장치(포커 칩 색)와 동아시아의 색 상징 차이가 제시된다([조선일보 위클리비즈, 2020-12-21](https://www.chosun.com/economy/weeklybiz/2020/12/21/PJ2TWSLMUJCAJPL5IF364HU3VM/), [매일경제 — 주가상승 왜 빨간색으로 표시하나](https://www.mk.co.kr/news/society/4987122)).
- 사용자 요구는 일방적이지 않다. "상승색을 초록으로 설정할 수 있는 앱이 있나"라는 커뮤니티 질문에는 "KB증권·토스증권·카카오페이증권에는 설정이 없다"는 사용자 답변이 달린다([클리앙, 2023-02](https://www.clien.net/service/board/cm_stock/17899990)). 커뮤니티 자료이므로 **약한 근거**로만 사용한다.
- 대비되는 사례: **Robinhood는 `Accessible colors` 토글로 적록 색각이상 사용자의 색을 개선**하고, 테마 미리보기를 제공한다([Accessibility options](https://robinhood.com/us/en/support/articles/accessibility-options/)).
- 한국형 지침은 색 의존 자체를 금지한다: **KWCAG 2.2 5.4.1(색에 무관한 콘텐츠 인식)** 은 "차트나 그래프를 고대비 모드로 표시하면 모든 색이 단색으로 표시되어 사용자가 색을 구분하지 못하는 경우가 발생한다"며 **색은 시각적 강조를 위해서만 사용**하고 **무늬·부호 등 추가 단서를 병행**하도록 요구한다([한국형 웹 콘텐츠 접근성 지침(KWCAG) 2.2](https://a11ykr.github.io/kwcag22/)).

### 6.2 숫자·통화·등락률 포맷

- 로케일별 숫자·통화·단위 포맷은 플랫폼 표준 API가 담당한다: `Intl.NumberFormat`은 `style: "currency"`, `currency`, `maximumSignificantDigits`, `style: "unit"`을 지원하고 **`formatToParts()`로 부호·숫자·통화 기호를 분리**해 반환한다([MDN — Intl.NumberFormat](https://developer.mozilla.org/en-US/docs/Web/JavaScript/Reference/Global_Objects/Intl/NumberFormat)). `[추론]` 부호 부분만 색을 입히려면 `formatToParts()` 분리가 사실상 필수다(문자열 조작으로 색을 넣으면 로케일·자릿수에서 깨진다).

### 6.3 한글 타이포 (Pretendard)

- Pretendard는 **SIL Open Font License 1.1** 로 배포되며, 예약 폰트명은 `Pretendard`, 파생 폰트는 다른 라이선스로 재배포할 수 없고, **폰트 자체를 단독 판매하는 것만 금지**된다. 저작권 고지는 소프트웨어와 함께 번들·임베드·재배포 시 포함해야 한다([orioncactus/pretendard LICENSE](https://github.com/orioncactus/pretendard/blob/main/LICENSE)).
- OFL 1.1 공식 페이지도 "책·포스터·로고·웹 등에서 사용 가능"하며 조건(예약명 미사용, 단독 판매 금지) 준수를 요구한다([SIL Open Font License](https://scripts.sil.org/OFL), [SPDX OFL-1.1](https://spdx.org/licenses/OFL-1.1.html)). `[추론]` 웹폰트로 self-host·서브셋하는 것은 허용 범위이며, **"Pretendard" 이름을 유지**하면 예약명 조건에도 문제가 없다.

### 6.4 다크모드

- 토스 서비스는 페이지 메타데이터에 `toss:color-scheme: light dark`와 `toss:support-font-scale: on`을 선언해 **시스템 색상 스킴과 폰트 스케일을 따르는 구조**를 갖는다(관찰 출처: [토스 커리어 — 토스증권 UX R&D팀](https://toss.im/career/article/secu_ux_rnd) meta 태그, [토스피드 UX Writing](https://toss.im/tossfeed/article/uxwriter-interview) meta 태그).
- shadcn/ui는 다크모드를 **클래스 기반(`.dark`) + 프레임워크별 가이드**(Next.js/Vite/Astro/Remix/TanStack Start)로 문서화하며, 토큰을 CSS 변수로 두고 스킴에 따라 값만 교체하는 형태를 권장한다([shadcn/ui — Dark Mode](https://ui.shadcn.com/docs/dark-mode)).
- Material 계열은 **색상 역할(role) 기반 접근**을 사용한다: "Color roles are like the 'numbers' in a paint-by-number canvas. They're the connective tissue between elements of the UI and what color goes where" ([Material 3 — Color roles](https://m3.material.io/styles/color/roles)). Apple HIG는 다크모드를 "저조도 환경에 맞춘 시스템 전역 설정"으로 규정한다([Apple HIG — Dark Mode](https://developer.apple.com/design/human-interface-guidelines/dark-mode)). `[미확인]` 두 페이지는 본문 스크립트 렌더링으로 전체 텍스트 추출에 실패해, 위 문장(메타 설명·인용구) 범위에서만 근거로 사용했다.

### ▶ 줍에 적용할 권고

| 항목 | 권고 |
|:--|:--|
| 등락 색 토큰 | `--color-up` / `--color-down` 으로 **이름을 먼저 고정**하고 값은 팔레트 스터디에서 확정. 계층: `--color-up` → `--color-up-weak`(배경), `--color-up-text`(다크 대비 재계산) |
| 색 외 신호(필수) | 모든 등락 표시 = **부호 + 등락률 텍스트 + 방향 아이콘(▲▼) + 색** 4중. 단독 색 사용 금지. 요구사항 NFR-12("색 이외 방향 텍스트 제공")가 이미 같은 규칙 |
| 색각이상 모드 | 설정에 `차트 색상: 한국식(빨강/파랑)` / `색각 안전(파랑/주황)` 2종 제공. 기본값은 한국식(시장 관례 존중), 전환 시 차트·배지·등락률 전 영역 동시 적용. `[추론]` Robinhood의 Accessible colors 대응을 국내 관례로 번안한 형태 |
| 숫자 포맷 유틸 | `formatPrice(value, {currency:'KRW'})`, `formatRate(0.0231)` → `+2.31%`(부호 항상, 소수 2자리), `formatCompactKRW(1_200_000_000_000)` → `1.2조 원`. 내부는 전부 `Intl.NumberFormat('ko-KR', …)` + `formatToParts()` 사용 |
| 숫자 타이포 | 숫자 영역에 `font-variant-numeric: tabular-nums` 강제(값 갱신 시 폭 흔들림 방지). 가격 16~20px Bold, 등락률 13~14px Medium |
| 폰트 | Pretendard self-host(woff2, 서브셋) + `font-display: swap`, `unicode-range` 분할. OFL 고지 파일을 저장소에 포함 |
| 다크모드 | ① 시스템 설정 기본, 수동 전환 제공 ② 색은 `--color-surface-base/-raised/-overlay` 3계층 + `--color-border-subtle/-strong` ③ 다크에서 상승/하락 색은 **명도 상향 재계산**(같은 hex 재사용 금지) ④ 차트 그리드·간선 색도 별도 토큰 |
| 고지 | 시세 영역에 `기준 15:30 KST · 15분 지연` 형태로 **항상** 표기(FR-26, NFR-09). 휴장·결측은 값 대신 `–`와 사유 툴팁 |

---

## 7. 접근성 (WCAG 2.2 / KWCAG 2.2)

### 7.1 WCAG 2.2에서 새로 추가된 항목

WCAG 2.2는 2023-10-05 W3C Recommendation이며, 2.1 대비 **9개 성공 기준이 추가**되고 **4.1.1 Parsing은 폐지·삭제**되었다([What's New in WCAG 2.2 — W3C WAI](https://www.w3.org/WAI/standards-guidelines/wcag/new-in-22/), [WCAG 2.2 REC](https://www.w3.org/TR/WCAG22/)). 줍에 직접 영향이 있는 항목:

| SC | 수준 | 요구 | 줍에서 위험한 지점 |
|:--|:--|:--|:--|
| 2.4.11 Focus Not Obscured (Minimum) | AA | 키보드 포커스 요소가 **저작 콘텐츠에 의해 완전히 가려지면 안 됨** | 그래프 캔버스 위 고정 툴바, 하단 시트, sticky 브리핑 바 |
| 2.5.7 Dragging Movements | AA | 드래그 동작은 **단일 포인터(드래그 없는) 대안** 필수 | 그래프 팬/줌, 타임라인 스크럽, 노드 이동 |
| 2.5.8 Target Size (Minimum) | AA | 포인터 타깃 **최소 24×24 CSS px**(또는 24px 원이 겹치지 않는 간격) | 그래프 노드, 칩, 아이콘 버튼 |
| 3.2.6 Consistent Help | A | 도움말 수단이 여러 페이지에 있으면 **상대적 순서가 동일** | AI 챗 진입 버튼, 툴팁 도움말 위치 |
| 3.3.7 Redundant Entry | A | 같은 프로세스에서 이전 입력을 **재입력 요구 금지**(자동 채움 또는 선택 제공) | 온보딩 3스텝, 종목 재선택, 검색 재입력 |
| 3.3.8 Accessible Authentication (Minimum) | AA | 인지 기능 테스트(암기·퍼즐) 요구 금지, **붙여넣기·비밀번호 관리자 허용** | 로그인(OAuth), 이메일 인증 코드 |

### 7.2 KWCAG 2.2 (국내 표준)

- KWCAG 2.2는 **4개 원칙 / 14개 지침 / 33개 검사항목** 구조이며(KS X OT000, 2022-12-28 개정), WCAG 2.1을 기초로 국내 상황에 맞게 작성되었다([KWCAG 2.2 전문](https://a11ykr.github.io/kwcag22/), [KWCAG 2.2 / 2.1 검사항목 대조표](https://webwatch.or.kr/include/fileDown.asp?2.2_%EA%B2%80%EC%82%AC%ED%95%AD%EB%AA%A9_%EB%8C%80%EC%A1%B0%ED%91%9C.pdf&filename=kwcag2.1)).
- 줍에 직접 관련된 검사항목:
  - **5.1.1 적절한 대체 텍스트**: "데이터 차트와 같이 내용이 복잡한 콘텐츠는 사용자가 의미를 충분히 파악할 수 있도록 대체 텍스트를 제공"
  - **5.4.3 명도 대비**: 텍스트와 배경 **4.5:1 이상**(18pt 이상 또는 14pt 굵은 폰트는 3:1)
  - **5.3.3 명확한 지시사항**: "동그란 버튼", "오른쪽 버튼" 같은 **색·크기·모양·위치 의존 지시 금지**
  - **5.4.1 색에 무관한 콘텐츠 인식**, **5.4.2 자동 재생 금지**(3초 초과 소리에는 제어 수단)
  - (전문 근거: [KWCAG 2.2](https://a11ykr.github.io/kwcag22/))

### 7.3 차트·그래프의 대체 텍스트

- W3C WAI는 복잡한 이미지에 대해 **짧은 대체 텍스트(alt) + 긴 설명(long description)** 을 요구하고, 긴 설명에는 "스케일, 값, 관계, 추세"를 포함하라고 명시한다. 연결 방식은 ① 인접 링크 + `figure/figcaption`+`role="group"` ② `alt`에 위치 안내 ③ `figure` 안에 설명 포함. `aria-describedby`는 **구조 정보(헤딩·표)를 전달하지 못하므로 텍스트 전용 설명에만** 사용해야 한다([W3C WAI — Complex Images](https://www.w3.org/WAI/tutorials/images/complex/)).

### ▶ 줍에 적용할 권고

**릴리스 전 통과해야 할 필수 체크 10개**

| # | 체크 | 측정 방법 |
|:--|:--|:--|
| 1 | 본문 텍스트 대비 ≥ 4.5:1, 큰 텍스트 ≥ 3:1 (라이트·다크 각각) | 토큰 값 사전 계산 + axe 검사 |
| 2 | 포커스 표시가 시각적으로 명확(대비 3:1 이상)하고 **어떤 요소에도 가려지지 않음** (2.4.11) | 키보드 Tab 전체 순회 + 하단 시트 열린 상태 재확인 |
| 3 | 모든 인터랙티브 타깃 ≥ 24×24px, 그래프 노드는 ≥ 44px | DOM 검사 + 그래프 노드 렌더 크기 상수 |
| 4 | 그래프 팬/줌이 **버튼으로도** 가능 (2.5.7) | 버튼만 사용해 특정 노드 도달 시나리오 |
| 5 | 차트·그래프에 `role="img"` + `aria-label`(요약 1문장) **그리고** `데이터 표로 보기` 토글 | 스크린리더 낭독 확인 |
| 6 | 정보 전달에 색 단독 사용 금지: 등락은 ▲▼+부호, 이슈 유형은 아이콘+라벨 | 흑백 스크린샷 검사 |
| 7 | 자동 재생 없음(오디오·영상 도입 시 3초 내 정지 또는 제어 제공) | 코드 검사 |
| 8 | 도움말(AI 챗·튜토리얼 재열기) 위치가 전 화면 동일 (3.2.6) | 화면 5종 비교 |
| 9 | 온보딩·설정에서 이전 입력 자동 채움, 종목 목록 재선택 제공 (3.3.7) | 스텝 뒤로 가기 시나리오 |
| 10 | 로그인·인증에서 붙여넣기 허용, 암기·퍼즐 요구 없음 (3.3.8) | 붙여넣기 실제 테스트 |

**컴포넌트 명세에 함께 넣을 것**

- `GraphCanvas`: `aria-label`은 "노드 수·관계 수·선택 상태"를 포함한 1문장(예: `삼성전자 중심, 기업 12개·이슈 3개, 선택된 관계 없음`). 갱신은 `aria-live="polite"`로 1회만(잦은 갱신 금지).
- `PriceChart`: 시각 차트 + **`표로 보기` 토글**(`<table>`: 일자/시가/종가/등락률). 기본값은 차트, 토글 상태는 사용자 설정으로 저장.
- `RelationList`: 그래프의 **1급 대체 경로**. 그래프 미지원 환경에서도 FR-17/FR-22 완결 가능해야 한다.
- `BottomSheet`: 열릴 때 `role="dialog"` + `aria-modal`, 초점 트랩, Esc 닫기, 닫은 뒤 **트리거 버튼으로 초점 복귀**(NFR-12).
- 애니메이션: `prefers-reduced-motion: reduce`에서 그래프 레이아웃 애니메이션·노드 이동을 즉시 완료로 전환.

---

## 8. 디자인시스템 구축 방식 비교

### 8.1 디자인 토큰 표준 (W3C DTCG)

- Design Tokens Community Group이 **2025-10-28 첫 stable 스펙(2025.10)** 을 발표했다. 주요 내용: **테마·멀티브랜드 지원**(라이트/다크/접근성 변형을 파일 중복 없이), **Display P3·Oklch 등 CSS Color Module 4 색공간 지원**, **상속·별칭·컴포넌트 수준 참조**, **한 파일에서 iOS/Android/web/Flutter 코드 생성**([W3C DTCG — 첫 stable 버전 발표](https://www.w3.org/community/design-tokens/2025/10/28/design-tokens-specification-reaches-first-stable-version/), [스펙 문서](https://www.designtokens.org/tr/2025.10/)).
- 레퍼런스 구현으로 Style Dictionary, Tokens Studio, Terrazzo가 언급되고, Figma·Sketch·Framer·Penpot 등이 지원/구현 중이다(같은 보도자료).

### 8.2 코드 스택

- **Tailwind CSS v4.0**: 설정을 JavaScript에서 **CSS-first(@theme)** 로 전환하고 성능을 재설계한 메이저 버전([Tailwind CSS v4.0 릴리스 노트](https://tailwindcss.com/blog/tailwindcss-v4)).
- **shadcn/ui**: 스스로를 "컴포넌트 라이브러리가 아니라 **컴포넌트 라이브러리를 만드는 방법**"으로 규정한다. 핵심은 ① Open Code(컴포넌트 소스를 프로젝트에 복사해 직접 수정) ② Composition(공통 컴포저블 인터페이스) ③ Distribution(스키마 + CLI) ④ Beautiful Defaults ⑤ AI-Ready. 상단 레이어는 headless 의존성 업데이트로 수정을 받고, 디자인시스템에 가까운 레이어는 열려 있다([shadcn/ui — Introduction](https://ui.shadcn.com/docs)).
- **Radix Primitives**: "접근성, 커스터마이즈, 개발자 경험"에 집중한 low-level 라이브러리. **WAI-ARIA 디자인 패턴 준수, aria/role 속성·포커스 관리·키보드 내비게이션을 내부 처리**, 스타일 없음, `asChild`로 렌더 엘리먼트 제어, 트리 셰이킹([Radix UI — Introduction](https://www.radix-ui.com/primitives/docs/overview/introduction)).
- **Storybook**: 컴포넌트를 앱 컨텍스트 없이 격리 렌더링하고, **stories를 개발·테스트·문서에 재사용**(interaction/accessibility/visual 테스트 내장), CSF 개방 표준([Storybook — Why Storybook](https://storybook.js.org/docs/get-started/why-storybook)).
- **비용**: Figma는 **Starter 무료**(초안·UI kit, AI 크레딧 500/월), 유료 플랜은 좌석 단위(Professional 이상)이며 Dev seat/Collab seat 구분과 AI 크레딧 체계가 있다. 유료 플랜에서는 **파일 보기·댓글은 추가 좌석 없이 허용**된다([Figma Pricing](https://www.figma.com/pricing/)). `[추론]` 5~6인 비전공자 팀은 **Full seat을 디자이너 1~2명만** 보유하고 나머지는 무료 뷰어로 운영하는 것이 비용 최소 경로다.

### 8.3 "비전공자 팀이 쓸 수 있는가" 관점 비교

| 방식 | 강점 | 약점 | 비전공자 접근성 |
|:--|:--|:--|:--|
| **Figma 중심 + 문서 페이지** | 시각적, 학습 곡선 낮음, 리뷰 쉬움 | 코드와 드리프트, 상태(로딩/에러) 표현 약함 | **상** |
| **Tailwind v4 + shadcn/ui (+Radix)** | 코드가 곧 시스템, 상태 변형 풍부, AI 도구가 잘 읽음 | 클래스 나열이 낯설 수 있음 | **중** |
| **Storybook 전면 도입** | 상태·접근성 테스트까지 한 곳 | 설정·유지 비용, 비전공자엔 과함 | **중하** |
| **DTCG tokens.json + Style Dictionary** | 표준·도구 독립, Figma↔코드 단일 소스 | 초기 설정 작업 필요 | **중**(설정은 개발자 1인) |
| **뱅크샐러드 BPL식 Container/Element/Child + 비전공자 템플릿** | "무엇을 조합할 수 있는지"를 도구가 강제 | Figma 플러그인·규칙 유지 비용, 재사용률 85%까지 9개월 소요 | **상** |

### ▶ 줍에 적용할 권고

**권고 스택 (1안)**

```
tokens.json (DTCG 포맷, 사람이 읽는 단일 소스)
   ├─ 빌드 스크립트(Style Dictionary 등) → src/styles/tokens.css (CSS 변수)
   ├─ Tailwind v4 @theme 에 매핑(--color-*, --radius-*, --font-*, --spacing-*)
   ├─ shadcn/ui 컴포넌트(코드 복사) + Radix 프리미티브(오버레이·탭·툴팁)
   └─ Storybook: 컴포넌트 6종만 스토리 + Docs 탭을 "디자인 카탈로그"로 사용
```

- 이유: ① 토큰이 표준 포맷이라 Figma·문서·코드가 같은 이름을 쓴다(DTCG) ② shadcn/ui는 라이브러리 버전업에 휘둘리지 않고 **소스를 직접 고칠 수 있어** 비전공자 팀의 "일단 고쳐서 맞추기" 워크플로와 궁합이 맞는다 ③ Radix가 포커스·키보드·ARIA를 대신 처리하므로 접근성 항목 4·8·10을 자동 확보할 여지가 크다 ④ Storybook은 **핵심 컴포넌트 6~8종만** 스토리로 운영하면 유지비가 낮고, Docs 탭이 그대로 팀 문서가 된다.

**대안과 트레이드오프**

| 대안 | 트레이드오프 |
|:--|:--|
| **A. Figma 중심 + 경량 문서 페이지(스토리북 생략)** | 도입 1주차 속도가 가장 빠르고 비전공자 진입이 쉽다. 대신 **코드-디자인 드리프트**가 누적되고(뱅크샐러드가 겪은 "제각각 컴포넌트" 문제 재현 위험), 로딩/에러/빈 상태 같은 **상태 변형**은 관리되지 않는다. 프로토타입 기간이 4주 이하라면 유효한 선택 |
| **B. Next.js 등 풀 프레임워크 + Storybook 전면** | 테스트·문서화는 최강이지만, 이번 단계 목표(디자인시스템 + PoC 백엔드 연동 프로토타입)에 비해 설정 비용이 과함. 서버 렌더링·라우팅 요구가 확정된 뒤로 이연 권고 |

**비전공자 팀을 위한 최소 장치 3개**

1. **컴포넌트 카탈로그 1페이지**: `/design` 라우트(또는 Storybook Docs)에 컴포넌트 이름·언제 쓰는지·쓰면 안 되는 경우·코드 스니펫 3줄. — Robinhood가 Content Standards를 Bento 안에 심은 방식과 동일한 발상(에디터가 문서를 따로 찾지 않게 함).
2. **금지 패턴 목록**: 다크패턴 5종 + 투자권유 오인 카피 금지어 + 색 단독 사용 금지. 파일 하나(`docs/design-checklist.md`)로 관리.
3. **토큰 추가 규칙**: "새 색·간격이 필요하면 먼저 기존 토큰으로 대체 가능한지 확인, 불가하면 `tokens.json`에 추가하고 PR에 이유 1줄". 규칙이 없으면 6주 뒤 토큰이 3배가 된다(뱅크샐러드 사례: 컴포넌트 642개).

---

## 9. 결론

### 9.1 줍의 디자인 원칙 7개

1. **근거 없는 문장은 표시하지 않는다.** 모든 요약·평가·관계 문장은 근거 문서 ID로 추적 가능해야 한다(FR-43, FR-44). 근거가 없으면 "판단 보류"가 정상 상태다. — 근거: WSJ는 "human-in-the-loop이 결정적"이라 명시하고([Nieman Lab](https://www.niemanlab.org/2025/06/lets-get-to-the-point-three-newsrooms-on-generating-ai-summaries-for-news/)), Bloomberg는 요약 정정 사례가 보도됐다([NYT](https://www.nytimes.com/2025/03/29/business/media/bloomberg-ai-summaries.html)).
2. **그래프는 목적지가 아니라 경로다.** 그래프 화면에는 항상 `목록으로 보기`가 있고, 초보 사용자의 1차 뷰는 리스트·타임라인이다(FR-39의 관계도/요약 전환과 동일 사상). — 근거: Kumu는 전체 지도 대신 검색 프롬프트로 시작하는 prompted mode를 제공하고([Focus 가이드](https://github.com/kumu/docs/blob/main/guides/focus.md)), Bloom은 필터 결과를 회색 처리·제거하는 두 단계 동작을 제공한다([Scene interactions](https://neo4j.com/docs/bloom-user-guide/current/bloom-visual-tour/bloom-scene-interactions/)).
3. **색 하나에 의미를 싣지 않는다.** 등락·긍부정·검증 상태는 항상 색 + 부호/아이콘 + 텍스트 3중 표기(NFR-12, KWCAG 5.4.1). — 근거: [KWCAG 2.2](https://a11ykr.github.io/kwcag22/) 5.4.1, [Robinhood Accessible colors](https://robinhood.com/us/en/support/articles/accessibility-options/).
4. **AI는 라벨링된 도구다.** AI 생성 텍스트에는 배지·근거 수·생성 시각·검수 상태가 붙고, "이 요약은 어떻게 만들어졌나요?"에 항상 답할 수 있다. — 근거: [인공지능기본법 제31조](https://www.law.go.kr/LSW/lsLinkCommonInfo.do?chrClsCd=010202&lsJoLnkSeq=1031810727) ①②, [금융위 금융분야 AI 가이드라인 7대 원칙](https://www.fsc.go.kr/no010101/87142).
5. **한 카드 = 한 질문.** 브리핑 카드 하나에 이슈 하나, 이슈 카드 하나에 판단 하나. 카드당 문장 3줄·칩 3개를 넘기지 않는다. — 근거: [Axios Smart Brevity 101](https://www.axioshq.com/hubfs/smart-brevity-101.pdf)(고정 라벨 블록 구조).
6. **초보가 기본값, 전문가는 옵션.** 기본 화면은 노드 20개·요약 우선·한국식 색상. 정밀 필터·전체 그래프·수치 표는 "더 보기" 뒤에 둔다. — 근거: 키움 영웅문S#의 간편모드/일반모드 분리([연합뉴스](https://www.yna.co.kr/view/AKR20251001142600008), [머니투데이](https://www.mt.co.kr/stock/2026/09/08/2026090809473448605)).
7. **투자 권유처럼 보이는 UI를 만들지 않는다.** 수익 단정·미실현 수익률·최상급 표현·매수 유도 CTA를 요약 영역에 두지 않는다. — 근거: 금감원이 지적한 광고 위반 유형([동아일보/뉴스1](https://www.donga.com/news/Economy/article/all/20260423/133796852/1)), 금소법상 손실보전·이익보장 오인 표현 금지([금융투자협회](https://www.kofia.or.kr/wpge/m_169/sub04070103.do)), 토스증권 시정명령 사례([조선비즈](https://biz.chosun.com/stock/stock_general/2025/11/06/H7NWI57LVNCPPGUZ4EEKO43D5M/)).

### 9.2 추천 스택

| 구분 | 1안 (권고) | 대안 | 트레이드오프 |
|:--|:--|:--|:--|
| 빌드 | Vite + React + TypeScript | Next.js | 라우팅·SSR 요구 확정 전까지 Vite가 가볍다 |
| 스타일 | Tailwind v4 (`@theme` CSS-first) ([릴리스 노트](https://tailwindcss.com/blog/tailwindcss-v4)) | CSS Modules + 수동 토큰 | Tailwind는 토큰↔유틸리티 연결이 강점, 학습 곡선 존재 |
| 토큰 | `tokens.json`(DTCG 2025.10 포맷) → CSS 변수 ([스펙](https://www.designtokens.org/tr/2025.10/)) | Tailwind 설정에 직접 값 기입 | DTCG 채택 시 Figma·문서·코드 이름 일치, 초기 설정 1일 소요 |
| 컴포넌트 | shadcn/ui(코드 복사) + [Radix 프리미티브](https://www.radix-ui.com/primitives/docs/overview/introduction) ([shadcn/ui](https://ui.shadcn.com/docs)) | MUI/Chakra 등 배포형 라이브러리 | 배포형은 오버라이드 지옥, shadcn은 소유권·수정 자유 |
| 그래프 | Cytoscape.js ([repo](https://github.com/cytoscape/cytoscape.js), [perf](https://cytoscape.org/js-perf/)) | Sigma.js+graphology / react-force-graph | §4.4 표 참조. 노드 20~60 규모에서는 Cytoscape.js의 레이아웃·알고리즘·문서 이점이 크다 |
| 문서 | [Storybook](https://storybook.js.org/docs/get-started/why-storybook)(핵심 6~8종) 또는 `/design` 라우트 | Figma만 | Figma만 쓰면 상태·드리프트 관리가 약하다 |
| 폰트 | Pretendard (OFL 1.1, self-host woff2) ([LICENSE](https://github.com/orioncactus/pretendard/blob/main/LICENSE)) | 시스템 폰트 스택 | 시스템 폰트는 다크/숫자 정렬 품질 편차 |

### 9.3 우선 만들 컴포넌트 (P0 → P2)

**P0 — 프로토타입 첫 화면에 반드시 필요**

| 컴포넌트 | 핵심 요구 |
|:--|:--|
| `AppShell` + `BottomNav` | 4탭 이하(홈/그래프/브리핑/내 정보), 현재 위치 표시 |
| `PriceChangeBadge` | 부호 + 등락률 + ▲▼ + 색 4중, `formatToParts` 기반 ([MDN](https://developer.mozilla.org/en-US/docs/Web/JavaScript/Reference/Global_Objects/Intl/NumberFormat)) |
| `TickerRow` / `ListRow` | 종목명 + 현재가 + 등락률 + `보유` 배지, 탭 영역 44px ([KWCAG 2.2](https://a11ykr.github.io/kwcag22/) 5.4.3) |
| `AiBadge` / `AiDisclosureSheet` | AI 생성 라벨 + 고지 시트(모델·근거 범위·검수) ([인공지능기본법 제31조](https://www.law.go.kr/LSW/lsLinkCommonInfo.do?chrClsCd=010202&lsJoLnkSeq=1031810727)) |
| `EvidenceList` / `EvidenceRow` | 문서명·출처·공개일·인용 구간·검증 상태(FR-43), 실패 시 사유 |
| `IssueCard` | 한 줄 요약 + 관련 기업 칩 ≤3 + 방향 배지(`호재 가능성`/`악재 가능성`/`혼합`/`보류`) + 근거 N건 |
| `BriefingCard` | 아침/저녁 라벨 + 기준 시각(KST) + `약 N분` + 이슈 3~5개 + 읽음 상태 ([Smart Brevity](https://www.axioshq.com/hubfs/smart-brevity-101.pdf)) |
| `EmptyState` / `ErrorState` / `LoadingSkeleton` | 3상태 분리 + 재시도 + 이전 화면 복귀(NFR-01) |
| `GraphCanvas` | 노드 예산 20, 포커스+컨텍스트, 확대/축소 버튼, `role="img"` ([WCAG 2.2](https://www.w3.org/TR/WCAG22/) 2.5.7) |
| `NodeInspectorSheet` | 기업/이슈/관계 3종 하단 시트, Esc 닫기 + 초점 복귀 ([WCAG 2.2](https://www.w3.org/TR/WCAG22/) 2.4.11) |
| `RelationList` | 그래프 대체 경로(관계 유형·방향·근거·검증 상태) ([WAI Complex Images](https://www.w3.org/WAI/tutorials/images/complex/)) |
| `DisclaimerNote` | "참고용이며 투자 권유가 아닙니다" 1줄, 요약 카드 하단 ([금융투자협회](https://www.kofia.or.kr/wpge/m_169/sub04070103.do)) |

**P1 — 탐색 완결성**

`TermGlossary`(용어 툴팁) · `EventTimeline` · `SegmentedTabs` · `FilterChips`(관계 유형·기간) · `VerificationBadge`(일치/불일치/보류) · `SearchInput` + `ResultList`(빈 결과 문구 포함) · `ChatMessage` + `CitationChip`(FR-48, 인용 ID 링크) · `PriceChart` + `표로 보기` 토글 · `ModeSwitcher`(시장 전체/자산 기반/관심 종목)

**P2 — 심화**

`OnboardingSteps`(3스텝 + 진행 표시) · `NodeGroupControl`(묶기/해제) · `PathHighlight`(사건→기업 경로 강조, FR-34) · `BriefingComparison`(이전 브리핑 검증, FR-41) · `ColorModeToggle`(한국식/색각 안전) · `SourceDistributionBar`(매체 유형·시각순)

### 9.4 다음 결정이 필요한 항목 (미정)

| 항목 | 선택지 | 결정에 필요한 정보 |
|:--|:--|:--|
| 그래프 필터 방식 (FR-18 / D-06) | 흐림(dim) vs 숨김(hide) | 노드 예산 20 기준 사용성 테스트. Bloom 문서는 "회색 처리 + 상호작용 차단"이 기본, 제거는 별도 동작 |
| 상승/하락 색 기본값 | 한국식(빨강/파랑) vs 색각 안전 기본 | 팀 내 색각이상 사용자 유무 + 사용성 테스트 |
| 그래프 라이브러리 최종 | Cytoscape.js vs Sigma.js | 노드 60개 + 애니메이션 + 한국어 라벨 렌더 품질 실측(PoC 필요) |
| 노드 상한 | 20 / 30 / 60 | PoC 백엔드가 실제 반환 가능한 부분 그래프 크기 확인 필요 |

---

## 부록 A. 출처 목록 (섹션별 인용 URL)

**1. 국내 핀테크·증권**
- https://developers-apps-in-toss.toss.im/design/components
- https://developers-apps-in-toss.toss.im/design/consumer-ux-guide.md
- https://tossmini-docs.toss.im/tds-mobile/foundation/colors/
- https://toss.im/tossfeed/article/uxwriter-interview
- https://toss.im/career/article/secu_ux_rnd
- https://blog.banksalad.com/tech/banksalad-product-language-design/
- https://story.kakaopay.com/121-kakaopay-home-2/
- https://zdnet.co.kr/view?no=20241226212205
- https://www.businesspost.co.kr/BP?command=article_view&num=318612
- https://www.edaily.co.kr/News/Read?mediaCodeNo=257&newsId=02069686645511568
- https://www.navercorp.com/media/pressReleasesDetail?seq=31285
- https://www.mt.co.kr/stock/2026/09/08/2026090809473448605
- https://www.yna.co.kr/view/AKR20251001142600008

**2. 해외 레퍼런스**
- https://robinhood.com/us/en/support/articles/accessibility-options/
- https://robinhood.com/us/en/newsroom/the-power-of-integrated-content-standards/
- https://www.bloomberg.com/company/press/bloomberg-launches-gen-ai-summarization-for-news-content
- https://www.nytimes.com/2025/03/29/business/media/bloomberg-ai-summaries.html
- https://www.niemanlab.org/2025/06/lets-get-to-the-point-three-newsrooms-on-generating-ai-summaries-for-news/
- https://ground.news/blindspot/about
- https://ground.news/media-bias
- https://ground.news/rating-system
- https://www.aiuxplayground.com/teardowns/perplexity/citations/
- https://public.com/themes

**3. 브리핑형 콘텐츠**
- https://www.axioshq.com/hubfs/Solutions-and-Support-Resources/Smart%20Brevity%20Checklist.pdf
- https://www.axioshq.com/hubfs/smart-brevity-101.pdf
- https://www.newsletteroperator.com/p/newsletter-design
- https://hark.news/newsletters/morning-brew-review
- https://businessinsider.zendesk.com/hc/en-us/articles/37472852715789-Audio-Briefings
- https://www.business-standard.com/technology/tech-news/google-rolls-out-news-audio-briefing-with-listen-tab-on-android-report-latest-new-summary-125121800582_1.html
- https://www.sciencedirect.com/science/article/abs/pii/S0749596X19300786
- https://www.tandfonline.com/doi/full/10.1080/10888438.2025.2612649

**4. 지식 그래프·네트워크 시각화**
- https://neo4j.com/docs/bloom-user-guide/current/bloom-visual-tour/bloom-scene-interactions/
- https://github.com/kumu/docs/blob/main/guides/focus.md
- https://help.obsidian.md/plugins/graph
- https://help.obsidian.md/plugins/local-graph
- https://www.graphistry.com/gpu
- https://www.graphistry.com/data-science
- https://neo4j.com/customer-stories/basf/
- https://neo4j.com/blog/graph-database/supply-chains-dont-fail-at-the-node-they-fail-at-the-connection
- https://www.sciencedirect.com/science/article/pii/S0097849324002589
- https://www.microsoft.com/en-us/research/video/orchard-exploring-multivariate-heterogeneous-networks-on-mobile-phones-2
- https://arxiv.org/abs/2607.06029
- https://mt.inf.tu-dresden.de/cnt/uploads/mobilevis2018_bueschel.pdf
- https://dl.acm.org/doi/10.1145/3744257.3744263
- https://dl.acm.org/doi/10.1145/3544548.3581087
- https://homes.cs.washington.edu/~jessejm/data/ThompsonMartinezCHI2023.pdf
- https://onlinelibrary.wiley.com/doi/abs/10.1111/cgf.14519
- https://arxiv.org/html/2410.20545v1
- https://github.com/cytoscape/cytoscape.js · https://cytoscape.org/js-perf/
- https://github.com/jacomyal/sigma.js · https://www.sigmajs.org/
- https://github.com/vasturiano/react-force-graph
- https://github.com/visjs/vis-network
- https://github.com/antvis/G6

**5. 규제·신뢰 UX**
- https://www.law.go.kr/LSW/lsLinkCommonInfo.do?chrClsCd=010202&lsJoLnkSeq=1031810727
- https://www.fsc.go.kr/no010101/87142
- https://www.lawtimes.co.kr/news/articleView.html?idxno=223136
- https://www.shinkim.com/kor/media/newsletter/3142
- https://www.kofia.or.kr/wpge/m_169/sub04070103.do
- https://www.donga.com/news/Economy/article/all/20260423/133796852/1
- https://www.fnnews.com/news/202609011400105857
- https://biz.chosun.com/stock/stock_general/2025/11/06/H7NWI57LVNCPPGUZ4EEKO43D5M/
- https://www.sciencedirect.com/science/article/abs/pii/S0167923616300823
- https://arxiv.org/pdf/2312.14978
- https://www.federalreserve.gov/econresdata/feds/2016/files/2016048pap.pdf
- https://www.yna.co.kr/view/AKR20260717029400017

**6. 시장 관례·시각 언어**
- https://www.chosun.com/economy/weeklybiz/2020/12/21/PJ2TWSLMUJCAJPL5IF364HU3VM/
- https://www.mk.co.kr/news/society/4987122
- https://www.clien.net/service/board/cm_stock/17899990
- https://a11ykr.github.io/kwcag22/
- https://developer.mozilla.org/en-US/docs/Web/JavaScript/Reference/Global_Objects/Intl/NumberFormat
- https://github.com/orioncactus/pretendard/blob/main/LICENSE
- https://scripts.sil.org/OFL · https://spdx.org/licenses/OFL-1.1.html
- https://ui.shadcn.com/docs/dark-mode
- https://m3.material.io/styles/color/roles
- https://developer.apple.com/design/human-interface-guidelines/dark-mode

**7. 접근성**
- https://www.w3.org/TR/WCAG22/
- https://www.w3.org/WAI/standards-guidelines/wcag/new-in-22/
- https://a11ykr.github.io/kwcag22/
- https://webwatch.or.kr/include/fileDown.asp?2.2_%EA%B2%80%EC%82%AC%ED%95%AD%EB%AA%A9_%EB%8C%80%EC%A1%B0%ED%91%9C.pdf&filename=kwcag2.1
- https://www.w3.org/WAI/tutorials/images/complex/

**8. 디자인시스템 구축**
- https://www.w3.org/community/design-tokens/2025/10/28/design-tokens-specification-reaches-first-stable-version/
- https://www.designtokens.org/tr/2025.10/
- https://tailwindcss.com/blog/tailwindcss-v4
- https://ui.shadcn.com/docs
- https://www.radix-ui.com/primitives/docs/overview/introduction
- https://storybook.js.org/docs/get-started/why-storybook
- https://www.figma.com/pricing/
