# 외부 API 후보와 데이터 이용 권한 — 2026-10-08

## 결론과 조사 범위

**국내 기업 개황·공시 재무는 OpenDART를 우선하고, 미국 공시 재무는 SEC EDGAR를 우선한다.** 해외 기업의 CEO·홈페이지 등 보강은 FMP가 기능상 적합하지만, 다중 사용자 화면 표시에는 별도 계약이 필요하다. 국내·미국 시세와 과거 시점 환율은 이미 어댑터가 있는 Toss를 우선 협의할 만하다. 다만 **키 발급·허용 IP와 제3자 표시/저장/모델 전송 권한은 별개**이므로, 키만 확보해서 바로 사용자 서비스에 적용해서는 안 된다.

**Yahoo는 무키 비공식 임시 공급원(provisional)일 뿐, 배포 가능한 무료 API가 아니다.** 공식 Yahoo Finance 도움말은 재배포를 금지하고, 일반약관은 사전 허락 없는 자동 수집을 금지한다. Naver 증권의 무키 JSON도 공식 Search API와 다른 비공식 인터페이스이며, Search API 가입이 증권 데이터 사용권을 주지는 않는다.

**Naver 개발자센터 Search API는 AI 입력 공급원으로 비추천한다.** 실제 열람한 2026-10-07 개정 약관은 검색 데이터와 가공·파생물의 AI 입력·학습·개선·평가·노출을 명시적으로 금지한다. 뉴스 검색 응답에는 전체 본문도 없다. 신규 이용자는 NAVER API HUB의 별도 절차·약관을 따라야 하며, 이 조사에서 HUB의 본문 저장·LLM 전송 허가는 확인하지 못했다.

Google과 Kakao는 둘 다 서버측 authorization-code/OIDC 방식이 현재 소셜 로그인 교체 지점에 적합하다. 실제 로그인은 각 제공자 앱 등록과 redirect URI 등록이 선행되어야 한다. Kakao의 이메일은 선택 제공이므로, 현재 `SocialIdentity.email: str` 계약을 그대로 적용할 수 있다고 가정하면 안 된다.

- **질문:** 현재 프로토타입에서 정확히 부족한 기업·재무·시세·뉴스 권한·소셜 필드를 어떤 최소 공급원 조합으로 채울 수 있는가?
- **지원할 결정:** Main이 추가 등록 없이 구현할 수 있는 어댑터/읽기 경로와, 등록·계정·계약·권한 확인을 먼저 해야 하는 실제 연결을 구분한다. 이는 최종 구매나 아키텍처 결정이 아니라 초기 근거 비교다.
- **기준:** 현재 BFF 소스와 목표 OpenAPI를 읽었다. 고정 WBS/명세/Figma를 다시 수집하지 않았다. 과거 문서의 ‘검토 전’을 이번 조사에서 기능 제외 근거로 사용하지 않는다.
- **조회일:** 아래 외부 자료는 모두 **2026-10-08**에 열람했다. 문서의 개정일·시행일은 조회일과 별도로 적었다.
- **경계:** 새 조사문서만 작성했다. 코드·원본 WBS/명세·계정·키·외부 설정을 변경하지 않았고, 실제 `.env`나 키 값은 읽지 않았다. 인증이 필요한 데이터 API 요청, 본문 추가 수집, 유료 호출, 등록, 배포, 빌드·테스트·린트·포매터는 수행하지 않았다. 가격은 공개 문서상 조건이며 실제 견적이 아니다.

`unknown`은 허용도 금지도 입증하지 못한 상태다. `조건부 추천`은 해당 조건을 충족한 뒤의 후보라는 뜻이며 지금 호출/재배포를 승인한다는 뜻이 아니다. 공개 접근, robots 허용, API 응답 성공, 운영자 승인, 모델 공급자 설정은 각각 데이터 라이선스를 대신하지 않는다.

## 1. 현재 구현에서 부족한 필드와 교체 지점

| 영역 | 소스에서 확인한 현재 계약 | 정확히 부족하거나 주의할 부분 |
|---|---|---|
| 기업 카탈로그 | `dataset.py:82-97,382-412`의 `CompanyRec`/`parse_companies`: `id`, `name`, `ticker`, `aliases`, `sector`, 이름/브랜드 출처와 로고. `sources.py:91-102,117-130`: JSON 최상위 `companies`를 읽는다. | 정식 법인명과 화면 이름의 구분, 법인 식별자, 거래소 **시장 세그먼트**, 대표, 설립일, 홈페이지, 업종 코드/명칭, 필드별 기준 시각이 없다. 기존 `KRX:005930`은 KOSPI/KOSDAQ 구분이 아니다. 정식명 확인 없이 표시 이름을 정식 법인명으로 승격하면 안 된다. |
| 기업 상세 | `schemas.py:450-463`의 `CompanyDetail`은 카탈로그 필드와 승인 이슈 연결을 제공한다. | 개황 API 응답이 아니다. 기업 등록/프로필 보강은 사건 참여나 공급 관계의 승인 근거가 아니다. |
| 주요 지표 | `quote_naver.py:36-70,157-170`: 시가총액·PER·EPS·PBR·BPS·배당수익률·주당배당금·외국인 소진율을 **출처의 문자열과 기준 기간 그대로** 제공한다. 추정 PER/EPS는 제외한다. | 기간별 매출·영업이익·순이익·자산·부채·자본·현금흐름 생산자가 아니다. `Metrics.items[].value: str`를 재무제표 수치 계약으로 재사용하면 통화·회계기준·누적/당분기 구분이 사라진다. |
| 목표 재무 | `docs/api/openapi.yaml:7541-7577,15605-15665`: `/api/v1/companies/{id}/financials`, `FinancialValue{name,value,unit,period,accountingBasis,source,asOf}`와 `FinancialResponse{available,unavailable,failed}`. | 목표 계약이 있다는 사실과 BFF에 실제 생산자가 있다는 사실은 다르다. 재무 기간은 차트 기간과 별개이며 미제공은 `null`+사유다. |
| Yahoo 시세·차트 | `quote_yahoo.py:1-14,35-36,73-83,143-171,183-230`: KRX `.KS/.KQ`, 미국, TSE `.T`; `1d/1w/1m/1y`를 `5m/1h/1d/1wk`로 요청. 현재가·전일종가·범위·거래량·52주 범위. | 시장가치·발행주식수는 이 차트 응답 어댑터에서 비어 있다. 무키·비공식이며 권리와 안정성을 보장하지 않는다. 약 60일 장중 이력 제한 언급은 **로컬 어댑터 주석**이지 공식 SLA가 아니다. |
| Toss 시세·차트 | `quote_toss.py:1-15,88-130,168-190,220-285`: Client Credentials, 현재가, 종목 마스터, 일봉. 52주 범위·시가총액 일부는 파생값으로 표시한다. | **현재 `series()`는 `1d/1w` 조회를 `no_data`로 거절한다.** 공식 API에는 1분봉이 있으므로 ‘Toss가 장중 자료를 제공하지 않는다’는 결론은 틀리다. 1분봉→5분/시간 OHLCV 집계가 미구현이다. FX/지수 API도 현재 Toss 어댑터에 연결되어 있지 않다. |
| 공급원 선택 | `market_data.py:298-320,336-348,351-384`, `config.py:63-68,129-138,172-186`: 환경 기본 `auto`는 키가 있으면 Toss 우선, 없으면 Yahoo. 지표는 별도 Naver. | 선택된 Toss가 `no_data`를 반환해도 데이터 단위로 Yahoo를 재선택하는 구조가 아니다. ‘auto이니 장중도 자동 보완된다’고 설명하면 안 된다. 실제 환경의 키 존재 여부는 조사하지 않았다. |
| 브리핑 지수·FX | `briefing_market.py:1-18,55-70,144-220`: `IndicatorHistory.history(symbol,start,end,interval)`; KOSPI/KOSDAQ 일봉, 원/달러 5분봉. 아침 07:40/저녁 18:05 이전 관측을 회차에 고정한다. | 현재 Yahoo 형식 심볼에 의존한다. 현재값만 주는 공급원은 과거 회차 재생을 대체하지 못한다. 최근값·기준 종가·관측 시각·유효 시간 구간을 구분해야 한다. 공개 회차 조회 때 최신값으로 바꾸면 안 된다. |
| 뉴스·근거 | `dataset.py:100-109`의 기사 메타데이터, 기존 PoC 읽기 결과와 원문 버전/인용 위치를 사용한다. `docs/evidence/poc-backend.md:20,84,141-151`은 본문 저장·모델 전송 부여와 약관 한계를 분리해 기록한다. | 제목·원문 링크·검색 패시지로 전체 본문을 확보했다고 주장할 수 없다. 기존 `allow_model_send` 값은 권리자의 계약을 입증하는 문서 자체가 아니다. 신규 기사/출처 권한을 자동으로 확대하면 안 된다. |
| 소셜 | `social.py:29-48,94-95,113-151`: `SocialProvider.authorize_url/exchange`, `SocialIdentity{provider,subject,email,display_name}`, mock만 등록. state는 브라우저 쿠키 결합·10분·일회성. `accounts.py:314-343`: provider/subject 조회, 다른 가입방식 이메일은 자동 병합하지 않고 409. | Google/Kakao 실 제공자가 없다. nonce 저장/대조, 제공자 JWT 서명/issuer/audience/만료 검증과 이메일 미제공/미검증 처리가 필요하다. 계정 병합 방어는 유지한다. |

## 2. 필요한 기업 필드별 권장 매핑

| 필요한 필드 | 국내 추천·대체 | 해외 추천·대체 | 의미와 남는 공백 |
|---|---|---|---|
| 정식 법인명 | OpenDART `company.corp_name`, `corp_name_eng`; `stock_name`은 별도 화면 이름 [D1] | SEC submissions의 current name [S1]; 계약된 FMP `companyName`, Massive `name` [F1,M1] | 국내 `corp_code`와 종목코드는 다르다. 외국 법인과 국내 자회사/브랜드를 티커만으로 합치지 않는다. |
| 거래소·시장 | OpenDART `corp_cls`: Y/K/N/E; 종목코드와 함께 사용. KRX 종목기본정보는 대체지만 이용범위 제한 [D1,K1,K2] | SEC exchanges/tickers; 계약된 FMP exchange 정보, Massive `primary_exchange`(ISO 거래소 코드) [S1,F1,M1] | `KRX` 식별자와 KOSPI/KOSDAQ/KONEX, 거래소 MIC와 회사 국적을 각각 구분한다. |
| 대표·CEO | OpenDART `ceo_nm` [D1] | FMP profile의 CEO가 기능상 우선 [F1]; SEC 공시/회사 공식 자료에서 별도 확인 | SEC submissions/companyfacts를 CEO API로 취급하지 않는다. Massive Ticker Overview에는 CEO 필드가 없다. 보강 계약 전은 unknown/null이다. |
| 설립일 | OpenDART `est_dt`(YYYYMMDD) [D1] | 이번에 읽은 FMP/Massive 표준 프로필에서 **동등한 설립일은 확인되지 않음** | FMP `ipoDate`, Massive `list_date`, Toss `listDate`는 **상장일**이며 설립일로 매핑하지 않는다. 해외 설립은 회사 공식 법인/공시 자료의 별도 근거가 필요하다. |
| 홈페이지 | OpenDART `hm_url`, 별도 `ir_url` [D1] | FMP website 또는 Massive `homepage_url` [F1,M1] | 로고·사진을 가져올 수 있는 권리와 홈페이지 주소 데이터는 별개다. |
| 업종 | OpenDART `induty_code` [D1]; 코드→명칭 분류표 버전의 별도 확인 필요 | FMP industry/sector; Massive `sic_code/sic_description` [F1,M1] | 기존 `sector`와 KSIC/SIC/공급자 자체 분류는 같은 분류체계가 아니다. 원코드·체계·버전을 보존한다. 국내 명칭 분류표는 이번 조사에서 미확인이다. |
| 매출·이익·자산·부채·자본·현금흐름 | OpenDART `fnlttSinglAcntAll`의 BS/IS/CIS/CF, `account_id/nm`, 금액·통화 [D3] | SEC companyfacts의 표준 US-GAAP/IFRS 개념 [S1]; FMP income/balance/cash-flow는 계약된 대체 [F2] | 금액 문자열 파싱만으로 의미가 같아지지 않는다. 단일 분기/누적, 연결/별도, 통화/단위, 보고기간과 정정 공시를 함께 선택한다. |
| PER/PBR/EPS/배당·시가총액 | 재무 사실과 승인된 시세로 계산하거나 계약된 지표 공급원. 현재 Naver는 임시 [L1] | 계약된 FMP/Massive 지표; SEC는 공시 사실 제공 [F1,S1,M1] | 시세 시각과 재무 기간을 섞지 않는다. 파생값은 계산 근거를 표시한다. 재무제표가 시가총액을 직접 제공한다고 가정하지 않는다. |

## 3. 공급원 비교표

‘유지 계약’ 열은 Java/Spring 또는 다른 FE로 이전해도 보존할 데이터/HTTP 경계를 뜻한다. 특정 언어·라이브러리 선택을 확정하지 않는다. 표의 `본문`은 뉴스/공시 본문, `전송`은 외부 모델 제공자 전송, `표시`는 여러 사용자를 위한 화면 표시/재배포를 가리킨다.

| 필요한 필드 → 판단·주공급원/대체 | Coverage / 국내·해외 | Auth / 등록 | 가격 근거 | License / 본문 보관 / 모델 전송 / 재표시 | Rate / history | 프로토타입 현재 연결 방법 | Java/Spring·다른 FE에서 유지할 계약 |
|---|---|---|---|---|---|---|---|
| 국내 개황 → **OpenDART 추천**; KRX는 제한된 대체 [D1,D2,D4] | DART 공시대상 국내 법인. 개황은 정식명·시장구분·대표·설립·홈페이지·업종코드. 모든 법인/종목에 값이 있다고 보장하지 않음 | 회원/인증키 신청 필요. 회사 식별 8자리 `corp_code`, 종목 6자리와 연결 | 약관 제11조: 원칙 무료, 일부 유료 전환 가능 | 제5·16조는 저작권법·공공데이터법 준거. 구조화 사실 재사용 후보로 추천하되, 뉴스 본문 권리를 주지 않음. 본문/외부 모델 전송/광범위 재배포의 명시적 포괄 허가는 **unknown** | 오류020: 일반적으로 20,000건 이상에 제한, 설정별 상이. 이를 고정 일일 SLA로 단정하지 않음. 개황의 과거시점 이력 API는 미확인 | 미연결. 기존 catalog 읽기 경계 앞에서 종목↔corp_code 매핑 후 보강. PoC 원본 catalog에 직접 쓰지 않는 별도 adapter 후보 | `companyId` 보존, `legalName/displayName`, 시장·분류코드·설립일 구분, 필드별 source/asOf/null 이유. 공급원 원문 JSON을 FE 계약으로 노출하지 않음 |
| 국내 재무·실적 → **OpenDART 추천**; 주요계정 API는 작은 대체 [D3,D4] | 유가/코스닥 상장사·주요 비상장 IFRS 정기보고 XBRL. 공시자가 작성하며 정정 가능. 전 법인/전 계정 보장 아님 | 같은 인증키. `bsns_year`, `reprt_code`, `fs_div=CFS/OFS` | 원칙 무료 [D4] | 구조화 수치와 공시 출처를 보존. 본문 API 권한과 구분. 모델 전송·인용 재게시 범위는 계약/법률 근거 **unknown**, 자동 허용하지 않음 | 2015년 이후; 분기11013/반기11012/3분기11014/사업11011. 당기 3개월 금액과 누적금액 별도 | 미연결. `FinancialResponse`의 실제 생산자 추가 대상. Naver `metrics` 대체가 아니라 별도 재무 응답 | `period/accountingBasis/unit/source/asOf`, raw `rcept_no/account_id`, 정정 버전, 연결/별도, 당분기/누적을 보존 |
| 미국 공시 재무·법인명/티커 → **SEC EDGAR 추천**; FMP 계약형 대체 [S1] | SEC 제출 법인. 미국뿐 아니라 20-F 등 외국 발행인도 있으나 **세계 기업 전체를 의미하지 않음**. 표준·entity-wide XBRL만 집계; custom/segment 누락 가능 | 인증/API key 불필요. CIK 10자리. SEC 보안·자동 접근 정책 준수 필요 | 무키 공개 API 확인. 별도 요금표는 **unknown** | 공시 사실 조회 후보. API 공개성이 제출인의 모든 첨부물·사진·저작물의 LLM/재게시 권리까지 입증하지 않음. 본문/모델 전송·첨부물 권리는 **unknown** | 제출 전파 시 JSON 갱신, 야간 bulk ZIP. 재무는 공시별 상이. **이번 열람에서 수치 rate limit은 미확인**; 10 RPS를 검증된 값으로 적지 않음 | 미연결. 서버측 CIK resolver+submissions/companyfacts adapter. SEC 직접 페이지는403, Context7 공식 문서 인덱스에서 해당 절 열람; 실 API 동작 미검증 | 서버측 요청(SEC는 CORS 미지원), companyId↔CIK, concept/unit/start/end/filed/accession 등 기간·출처 보존. custom 계정을 추정 보충하지 않음 |
| 해외 프로필 CEO·홈페이지·업종/재무 → **FMP 기능상 조건부 추천**, SEC+공식 회사자료 대체 [F1–F3] | Starter 미국, Premium 영국/캐나다, Ultimate Global이라는 상품 설명. 현재 TSE/KRX 각각의 종목·필드 coverage는 **unknown** | 계정·API key. 다중사용자 Data Display and Licensing Agreement 선행 | Personal: Basic 무료250/day, Starter **$19/mo 연간 결제**, Premium **$49**, Ultimate **$99**. 상업·표시 계약 견적 **unknown** | §2.2.1 개인용은 제3자 접근 앱 금지. §2.2.2는 **무료/유료·내부/외부 모두** 여러 사용자를 위한 표시에 별도 agreement 요구. §6.3 종료 시 캐시 포함 삭제. 외부 모델 전송·파생 요약도 무승인 허용하지 않음. 본문 보관권 unknown | 300/750/3,000 calls/min 개인 상품. 5년/30년/전체 등 설명과 세부표 일부 범위 표현 차이; endpoint별 최종권한 확인 필요. bandwidth도 별도 제한 | 미연결. 회사 프로필·재무·지표별 adapter, 공식 stable endpoints. 가입 무료가 프로젝트 표시 무료라는 의미는 아님 | 원종목/거래소 매핑, 정식명·IPO/설립 구분, source/asOf; 재무 회계기준/통화·기간 유지. API key는 BE에만 |
| 국내 시장명·일별 OHLCV·지수 → **KRX 공식 사실 확인/제한된 비상업 활용 후보**, 고객향 배포·LLM은 비추천; Toss 계약형 대체 [K1–K3] | KOSPI/KOSDAQ/KONEX 종목기본·일별매매·지수. 장중/FX/CEO·설립/재무제표를 이 API에서 제공한다고 가정하지 않음 | 회원, 인증키 관리자 승인, API별 활용신청 관리자 승인. 키 이용기간1년/연장 | 읽은 약관·목록에 요금 근거 없음: **unknown** | 시행2025-12-26. §6.2 **비상업용만/제3자 대가 금지**, §11.2 **정보 제3자 제공 금지**. §10.3 화면 제작 시 ‘한국거래소 통계정보’ 명시. 화면 제작 조항을 제3자 제공금지의 포괄 예외로 읽지 않음. LLM 전송은 제3자 제공 범위 협의 전 비추천. 계약종료 뒤 이용금지 | §8.4 키당10,000/day. 유가/코스닥2010-01-04 이후, 코넥스2013-07-01 이후 | 미연결. 일봉/시장 매핑 adapter 후보. 기존 BFF→브라우저 데이터 제공 구조의 허용범위를 **등록 전에 확인** | 시장 세그먼트·거래일·출처명, 라이선스 범위와 계약종료 후 사용 중단. BE를 거치면 재배포가 아니라는 해석 금지 |
| 국내·미국 현재가/과거·장중 → **Toss 구현 재사용 우선, 권한 조건부 추천**; 미국은 Massive Business 대체 [T1–T3] | 국내/미국 주식. `1m/1d` 캔들·현재가·발행주식수. TSE 등은 문서 coverage 밖 | WTS 로그인→client 등록/발급→**허용 IP 등록**, Client Credentials. 시세는 계좌헤더 불필요; 계좌/주문은 별도 헤더. 계좌 개설/자격 상세 약관 본문은 정적 열람 실패로 **unknown** | 기술 문서에 API 요금 근거 없음: **unknown**. 매매 수수료와 데이터 라이선스 요금은 다른 항목 | 공식 API라는 사실은 확인. 오픈API 약관 페이지 본문을 읽지 못해 **제3자 표시·서버 장기보관·LLM 전송은 unknown**. 권리 확인 전 public-service 채택 불가. 원문뉴스 공급원 아님 | 문서상 MARKET_DATA15/s, CHART20/s, STOCK5/s; 변동 가능·응답헤더 우선. 캔들 최대200/nextBefore, 수정주가 기본true. 최장이력은 unknown | `TossClient/Provider` 이미 있음. 장중은 새1분봉 집계 필요. 현재 일봉→주봉 집계와 파생 시총/52주 범위 유지. 실제 키 여부 미확인 | 기존 `Quote/Bar/Series`와 `derived`, currency, ISO시간/시장 세션·수정주가 정책 보존. 공급자 OAuth를 사용자 Google/Kakao OAuth와 혼동하지 않음 |
| 과거시점 USD/KRW·KOSPI/KOSDAQ → **Toss 계약 확인 후 조건부 추천**; 지수 일봉은 KRX 제한형 대체, 해외 FX는 FMP/Massive 별도 coverage 확인 [T1,T4] | Toss USD↔KRW는 참고용 표시환율·1분 갱신·`dateTime` 특정시점 조회. 지수 KOSPI/KOSDAQ 1분/일봉. 다른 FX pair는 이 문서에서 확인되지 않음 | 위 Toss 토큰/IP 등록 | **unknown** | 표시환율은 실제 거래 적용 환율과 다를 수 있음. 보관·회차 재게시·외부 모델 전송 권한 unknown | FX MARKET_INFO3/s, 지수 CHART5/s. 환율 validFrom/validUntil; 특정시각 조회 제공은 확인, 최장 보존기간은 unknown | 현재 Toss 경로 미연결, 브리핑은 Yahoo `IndicatorHistory`. **현재환율 하나로 과거5분봉 history를 흉내내지 않음**. 특정시점 조회로 회차/기준값을 가져오는 연결 방식 검토 필요 | `observedAt/validFrom/validUntil`, 기준일·기준시각·표시환율 종류. `IndicatorHistory` 변경 필요 시 브리핑 caller도 함께 이동; 회차 불변성은 유지 |
| 미국 차트·회사 거래소/홈페이지 → **Massive Business 조건부 대체**, Individual 프로젝트 배포는 비추천 [M1–M4] | 미국 주식; US 전체 거래소라는 상품 설명. KRX/TSE 주식 coverage 대체로 인정하지 않음. 이름/MIC/홈페이지/SIC, CEO/설립은 없음 | 계정/API key, Business/거래소 이용권한. Polygon은2025-10-30 Massive로 변경 | 무료 개인5req/min은 확인. 핵심 유료 tier 숫자는 동적 pricing 카드 미추출: **unknown**. Business 견적 unknown | 공식 공개 Market Data Terms(2024-10-09) §1 개인 비사업·비상업 및 본인 외 end-user 앱 금지. §5 제3자 재배포·파생물·non-display 무승인 금지. §10 종료/정지시 삭제. Business 권한은 별도. 사이트 ‘Train models’ 문구를 개인약관 override로 보지 않음 | Custom Bars: Basic2년/EOD, Starter5년/15분지연, Developer10년/15분지연, Advanced/Business 전체/실시간. 전체자료 시작2003-09-10. 최대50,000 base aggregates/page, 무거래 interval은 봉 없음 | 미연결. 미국 전용 `QuoteProvider` 대체 후보; source provider enum과 FE 타입도 확장 필요 | OHLCV, adjusted 여부, 시간·세션, 실제 지연·source. `next_url` paging은 BE에 격리. 미국 coverage를 ‘해외 전체’로 표기하지 않음 |
| 현 무키 Yahoo 차트·FX → **provisional / 신규 라이브 확장·배포 비추천** [Y1,Y2,L1] | 도움말상 KOSPI/KOSDAQ20분·TSE20분 지연, 글로벌 FX 등. 이는 웹 서비스 coverage 설명이지 비공식 endpoint SLA가 아님 | 현 어댑터는 key 없음. **허락 없는 자동 수집이 합법이라는 의미 아님** | 현 어댑터 무과금 구조. 허가된 API/배포 요금은 **unknown** | Finance 공식 도움말: **Do not redistribute**. 일반약관 §2.4.9 자동수집 사전허락, §2.8 재사용 제한. body/storage/model-send 허가 없고 비추천. Yahoo 자신의 AI provider 동의 조항은 Zoop의 권리 아님 | 공식 차트 rate/history SLA unknown. 로컬 range 매핑/약60일 이력 주석은 구현 관찰 수준 | `quote_yahoo.py`와 브리핑 history에 현재 구현됨. 현재 코드 보존과 새 수집·공개서비스 권리 승격은 별개. 권리 있는 공급원으로 교체 결정 대상 | 기존 quote/series 실패 표현과 source 공식여부·지연표시 유지. 권한 없는 데이터를 다른 BE언어로 재구현해도 해결되지 않음 |
| 현 Naver 증권 지표 → **provisional / 정식 운영 공급원 비추천** [L1,N1] | 현 코드상 국내·미국·TSE. public JSON/ac resolver, undocumented | 무키. **Naver Search API key로 증권 데이터를 정식 사용한다는 대체 불가** | 정식 증권 API 가격 **unknown** | 읽은 Search 약관은 이 비공식 증권 JSON의 별도 데이터 라이선스가 아님. 증권 데이터 표시·보관·외부모델 허가 unknown. 미확인을 허락으로 해석하지 않음 | 공식rate/history unknown. 현재 metrics TTL30분/reference12h는 **BFF 캐시 정책**, 허용 보관기간 아님 | `NaverMetricsProvider.metrics`; `MarketData.metrics` 교체점. 이미 표시하는 지표와 신규 재무 API를 구분 | 코드/label/value/basis/asOf/source를 유지하되 계약된 공급원으로 변경. 문자열 지표를 재무 수치로 조용히 변환하지 않음 |
| 뉴스 검색 제목·링크/패시지 → **검색 UI 한정 NAVER API HUB 조건부**, AI 본문 공급원 비추천 [N1–N4] | 국내 중심 네이버 검색. 전체본문 없음. title/originallink/link/description/pubDate | 신규는 NCP/HUB 신청·Application/API key. 기존 Developers Search 신규접수2026-07-30 종료, 기존2027-06-30 종료 예정. 오래된 Client-Id 등록 안내만 따르면 안 됨 | HUB 사용가이드: **한시적 무료**, 유료전환 사전공지; 전환후단가 unknown | Developers 현행 §나2.3: 데이터·파생물 **AI 입력/학습/개선/평가/노출 금지**. §나2.2 독립·무가공 검색결과 및 출처/링크. HUB는 별도약관 요구; 상세권한 **unknown**, 금지해제 주장 불가. 본문은 제공하지 않음 | HUB overview FAQ: 검색 합산775,000/month, key50RPS. 개별 news API doc은25,000/day라고도 적어 **공식 문서 충돌**. 실제 신청조건/콘솔 한도 확인 필요. display100/start1000; 과거 전체 기사 아카이브 아님 | 현재 BFF 기사 공급자 아님. PoC 문서에 HUB 경로 존재만 확인. 새 검색결과를 PoC 본문 입력으로 바꾸지 않음 | 검색전용 DTO+출처/링크/수명; 기사 full-body/evidence DTO와 분리. 가공금지/캐시목적·기간 조건을 BE 변경시도 보존 |
| 해외 뉴스 **실제 본문** → **Massive Benzinga News Business 계약 후보**, 기존 승인 원문 재생이 당장 대체 [M5,M6] | 미국 시장 중심. `body` full text 있으나 일부 headline-only. 국내뉴스 coverage unknown | Massive key+별도 Benzinga News Business 상품/계약 선행 | 개인 News **$99/month, Individual use only**. Business는 Contact us for pricing → **unknown** | Business 상품 존재와 full-body schema는 확인. **영구보관·LLM inference/embedding/training·인용/요약 재게시·계약종료후 산출물 유지 범위는 unknown**. $99 개인상품을 여러사용자/AI권리로 채택하지 않음 | 실시간,2009-04-27 이후 history. limit기본100/최대50,000, next_url; rate한도는 계약상 unknown | 미연결. 계약 확보후 별도 수집 adapter로 기사id/version/body_scope/rights→기존 PoC readonly/승인 계약 연결. body없는 항목은 full로 승격하지 않음 | `body_scope`, 허가근거/만료/보관기간/모델전송 대상, body정규화버전+인용 offset, 원문url/last_updated. full-text API 응답만으로 downstream 권한을 확정하지 않음 |

### 뉴스 권한에 대한 구체적인 배제와 대체

1. **Naver Developers 검색 결과는 제목·패시지라도 LLM에 보내지 않는다.** 현행 약관의 AI 금지는 전체 본문에만 적용되는 문구가 아니며 데이터 가공·파생물도 포함한다. §나2.4의 예외 캐시 허용은 AI 금지 예외가 아니다.
   - 기기 캐시: 장애 대응/개인화 목적, **24시간 또는 새 질의까지 중 짧은 기간**.
   - 서버 캐시: 이력 조회 목적 **최대21일**; 개인화는 기기와 같은24시간/새 질의 조건. 목적별 분리보관과 기간경과 삭제가 필요하다.
   - 이를 ‘뉴스 DB 영구보관 허가’로 해석하지 않는다. HUB에 이 구약관이 그대로 적용되거나 반대로 전부 해제되었다고 단정하지 않는다.
2. **Massive 기본 `/v2/reference/news`는 전체 본문 공급원이 아니다.** 실제 schema는 description/article_url/title/publisher/insights 등이며 full body 필드가 없다. 공급자 sentiment는 Zoop의 문서×기업 자체 판정을 대신하지 않는다. 본문이 필요한 후보는 별도 **`/benzinga/v2/news`**다.
3. **공시는 뉴스 본문의 대체 출처일 수는 있어도 같은 문서가 아니다.** OpenDART `document.xml`은 인증키+접수번호로 ZIP 원문을 제공한다 [D5]. SEC의 공시도 법인 재무·발표 사실의 1차 자료 후보다. 원문 이용·외부 모델 전송·인용 재게시 근거를 따로 확인하고 `input_kind=filing` 등 실제 자료 종류를 보존해야 한다. 뉴스 전체본문인 것처럼 표시하지 않는다.
4. **기존 PoC 스냅샷/재생 자료의 읽기 연동은 유지할 수 있지만 새 수집권한을 넓히지 않는다.** 기존 조사 [P1]은 NVIDIA/SK하이닉스 약관에 자동수집·복제 금지 문구가 있음을 이미 기록한다. 운영자가 제한된 실험을 승인했다는 사실은 권리자의 허락을 대신하지 않으며, 상업/외부 배포 권리 확인이 완료되었다고 적지 않는다.
5. 국내 뉴스 전체본문+LLM+재게시를 동시에 허용하는 공급원은 **이번 최소 후보군에서 확인되지 않았다**. 다음 결정은 ‘권리자가 허용하는 국내 기사 본문 라이선스를 별도로 협의할 것인가, 그 전에는 기존 근거/권리 확인된 공시 자료만 처리할 것인가’다. 임의 크롤링을 대체안으로 두지 않는다.

## 4. Google·Kakao OAuth 비교

| 필요한 필드 → 추천주공급원/대체 | Coverage | Auth / 등록 | 가격 근거 | License / 보관 / 모델 전송 / 재표시 | Rate / history | 프로토타입 현재 연결 방법 | Java/Spring·다른 FE에서 유지할 계약 |
|---|---|---|---|---|---|---|---|
| Google account identity → **Google OIDC code flow 추천**; GIS ID-token 방식은 대체, mock은 개발전용 [G1–G3] | Google 사용자. `sub`가 안정적인 식별자. email/name은 scope·claim 제공조건을 확인 | Cloud project·OAuth client ID/secret·정확한 redirect URI·branding/consent 설정. 최소 `openid email profile`; scope/배포상태에 따른 심사 필요 여부는 등록 설정에서 확인 | 읽은 OIDC 문서에 로그인 요금표 없음: **unknown**. Google Cloud Identity Platform 요금과 혼동하지 않음 | 사용자 데이터 정책: privacy policy, 공개 OAuth설정에 URL, 접근/이용/저장/공유 공개, 최소권한, 새목적은 고지·동의. 로그인동의가 프로필을 LLM에 보낼 권리인 것은 아님. 이 조사 권고는 **인증 데이터는 모델에 보내지 않음** | 고정 sign-in rate SLA unknown. token exp·공개키 Cache-Control 준수. 재무 history와 무관 | mock만 있음. `SocialProvider.authorize_url/exchange`로 code교환→검증된 identity. state쿠키 결합 유지; nonce상태 추가 대상. 기존 이메일 자동병합금지 유지 | server callback·세션cookie, `(provider,sub)` 키, JWT서명/aud/iss/exp 검증 및 사용한nonce 대조, email_verified/미제공 처리. FE는 redirect만 수행; client secret/token을 브라우저 상태에 두지 않음 |
| Kakao account identity → **Kakao OIDC code flow 추천**; OAuth code+검증된 `/v2/user/me`는 대체, mock은 개발전용 [C1–C4] | Kakao사용자. OIDC sub는 앱별 식별자. nickname/email은 동의·제공여부에 종속 | 앱생성, REST API key, 로그인ON·redirect URI, OIDC ON. 현재 문서는 REST키에 client secret 기본활성 및 토큰요청 포함을 안내. 이메일 등 일부동의항목은 추가권한/비즈앱/심사 필요 | quota문서 무료월간3,000,000 전체API, login별 유료단가 미제시: **초과/별도계약 비용 unknown** | 최소 동의항목과 목적·개인정보처리방침. 이메일 `is_email_valid/is_email_verified/email_needs_agreement` 확인. 국외이전은 별도설정·고지 항목. 인증정보 LLM전송을 기본 허용하지 않음 | 사용자당 access token10분20개, refresh token60분30개; 변경 가능. JWKS캐시는 권장, 빈번조회 차단 가능 | mock만 있음. 검증후 provider/subject identity. **현재 필수email 계약과 불일치**: 사용자 별도이메일 등록/검증 또는 nullableidentity+회원 정책 변경을 Main이 선택해야 함. 가짜email생성은 비추천 | code/token 서버교환, `(provider,sub)`식별자, iss=`https://kauth.kakao.com`, aud=앱키, exp/nonce/서명/JWKS검증. app키를 바꾸면 같은sub가 유지된다고 가정하지 않음 |

### OAuth 비추천 판단

- 제공자 JWT를 Base64 decode만 하고 로그인시키는 방식, 브라우저가 보낸 이메일만 신뢰하는 방식, 이메일이 같다는 이유의 계정 자동 병합, 이메일이 없을 때 임의 주소 생성은 비추천한다.
- Google `tokeninfo`나 Kakao ID-token-info 디버깅 endpoint를 정상 프로덕션 인증 검증의 유일 경로로 삼지 않는다. 문서가 권장하는 라이브러리/JWKS 검증 경계를 사용한다.
- Java/Spring 이전 시에도 제공자 클라이언트 등록은 자동으로 생기지 않는다. callback origin/URI 변경은 제공자 설정 변경을 요구한다. FE 프레임워크 변경이 OAuth 프로토콜·권한을 바꾸지는 않는다.
- Google/Kakao 로그인 추가가 사용자의 실제 증권계좌 열람권한을 주지 않는다. Toss market-data Client Credentials와 사용자 소셜 인증을 별개로 유지한다.

## 5. Main이 선택할 수 있는 구현과 선행 조건

| 구분 | 추가 등록 없이 가능한 작업 | 실제 연결·배포 전에 필요한 것 |
|---|---|---|
| 기존 승인 데이터 | 현재 PoC 읽기 adapter·스냅샷/재생 연결을 재사용하고, 출처/버전/인용 위치와 기존 권한 경계를 보존한다. | 새본문수집·외부모델전송·재게시 범위를 기존 승인에서 자동 확대하지 않는다. 법적 권리 증거가 없는 기존 출처의 배포문제는 별도다. |
| 국내 profile/financials | OpenDART field mapper·회사식별 매핑·재무기간/연결별도/오류응답 adapter를 **문서 계약에 맞춰 구현**할 수 있다. 키없는실데이터를 지어내지 않는다. | 사용자가 기존 유효키를 보유했는지 **값을 읽지 않고 존재/등록상태로 확인**하거나 승인된 신규키 신청. 실제 호출·필드coverage·업종명 코드표·재사용 범위 확인. |
| 미국 SEC 재무 | 인증없는 서버 adapter 구현이 가능하다. 이번에는 credentials도 요청도 필요하지 않은 공식 계약을 조사했다. | 실제 네트워크 접근·정책(rate/User-Agent)·CIK coverage 확인이 남는다. 이번 도구는 sec.gov/data.sec.gov 직접읽기에403을 받았으므로 **작동 검증 완료가 아니다**. |
| chart/market | 기존 Toss 어댑터 재사용·1분봉 집계·지수/특정시점환율 mapper 구현을 설계할 수 있다. 권한 불명시 `not_connected/unavailable` 계약을 유지한다. | Toss 계정/키/IP와 이용약관 원문/제3자 표시·과거보관·LLM범위. FMP/Massive는 별도표시/Business계약과 종목coverage. KRX는 비상업/제3자제공 제한의 범위확인. Yahoo/Naver 비공식경로를 승인된폴백으로 확장하지 않는다. |
| 뉴스 | 기존 전체본문이 있는 권리범위내 재생/읽기자료만 연결. 검색UI와 본문/evidence입력을 분리한다. | 국내body계약 또는 Benzinga Business계약의 보관·외부LLM·인용/요약 재게시 권한. Naver Search AI금지는 키/유료가입으로 해제되지 않는다. HUB별도권한은 unknown이다. |
| 소셜 | Google/Kakao provider구현·JWT검증·nonce·이메일미제공처리·현재state/session 경계 이식은 가능하다. | 제공자앱등록·redirect/client 설정·동의항목/개인정보처리방침·필요심사. 기존email필수와Kakao선택제공을 해소할 정책결정. 실제code교환은 승인된등록이후다. |

**범위를 바꿀 최소 추가 근거:** (1) Toss 현행약관의 데이터 제3자표시/보관/모델전송 조항, (2) 국내뉴스 권리자의 full-body+LLM+재게시 허가, (3) FMP/Massive Business 실제주문서의 데이터권한과 현재 카탈로그 종목coverage, (4) SEC fair-access 원문과 네트워크 접근 확인, (5) Kakao 이메일을 필수로 받을 자격/정책. 이 문서는 이들 미확인을 허가로 바꾸지 않는다.

## 6. 실제 열람한 출처와 문서 절

외부 자료의 공통 조회일은 **2026-10-08**이다. 아래에 `직접`이라고 적은 자료는 본문/해당 절을 실제 읽었다. Context7는 공급자 공식 문서를 인덱스에서 읽는 보조 경로이며, 접근실패를 가리지 않았다. 검색 snippet만으로 약관을 인용하지 않았다.

| ID | URL·문서 절 / 버전·읽은 범위 | 뒷받침하는 주장·한계 |
|---|---|---|
| D1 | [OpenDART 기업개황](https://opendart.fss.or.kr/guide/detail.do?apiGrpCd=DS001&apiId=2019002) — 기본정보/요청인자/응답결과/메시지, 직접 | company.json, 정식명·시장구분·CEO·설립·홈페이지·업종코드, 인증키·제한 메시지 |
| D2 | [OpenDART 고유번호](https://opendart.fss.or.kr/guide/detail.do?apiGrpCd=DS001&apiId=2019018) — 기본정보/응답, 직접 | corpCode ZIP, corp_code/stock_code/modify_date |
| D3 | [전체 재무제표](https://opendart.fss.or.kr/guide/detail.do?apiGrpCd=DS003&apiId=2019020), [재무 API 목록](https://opendart.fss.or.kr/guide/main.do?apiGrpCd=DS003) — 요청/응답/대상법인·정정 주의, 직접 | 2015+, CFS/OFS, 보고서코드, 통화/3개월·누적구분, 제공범위·정정보장한계 |
| D4 | [OpenDART 이용약관](https://opendart.fss.or.kr/intro/terms.do) — 제5~11·16·19조, 직접 | 가입/용도/인증키, 원칙무료, 저작권/공공데이터법 준거·키공유금지. LLM에 대한 명시적포괄허가 없음 |
| D5 | [공시서류원본](https://opendart.fss.or.kr/guide/detail.do?apiGrpCd=DS001&apiId=2019003) — 기본정보/요청, 직접 | document.xml ZIP와접수번호·키. 뉴스와공시종류구분 |
| S1 | [SEC EDGAR APIs](https://www.sec.gov/search-filings/edgar-application-programming-interfaces) — Submissions/XBRL Data APIs/companyfacts/Bulk Data/CORS. Context7 `/websites/sec_gov_search-filings_edgar-application-programming-interfaces`에서해당본문절 열람 | 인증불필요·CIK/name/tickers/exchanges·표준entity-wide XBRL·실시간/야간bulk·CORS미지원. 직접URL/구URL/data.sec.gov/developer-resources/security문서 시도는403. 수치rate·모든첨부물권리는 미확인 |
| F1 | [FMP Company Profile](https://site.financialmodelingprep.com/developer/docs/stable/profile-symbol) — About/API, 직접; Context7 `/websites/site_financialmodelingprep_developer`의 stable profile/screener 문서도읽음 | name/CEO/industry/contact/IPO·globalidentifiers. 설립일동등필드 확인안됨 |
| F2 | [FMP Income Statement](https://site.financialmodelingprep.com/developer/docs/stable/income-statement) — About/endpoint/Related Balance Sheet, 직접 | stable실적endpoint·수익/순이익·balance대체후보. 실키응답schema/현재종목coverage는미검증 |
| F3 | [FMP Pricing](https://site.financialmodelingprep.com/pricing-plans), [Terms](https://site.financialmodelingprep.com/terms-of-service) — 개인상품·가격하단권리문구/§2.2.1·2.2.2·2.8·6.2·6.3, 직접. Terms페이지표시개정일2023-08-01 | 연간결제가격·tiercoverage·rate/bandwidth·무료/내부포함별도표시계약·종료삭제. 표시개정일이현재모든문구의변경시점을증명하지않음 |
| K1 | [KRX 서비스목록](https://openapi.krx.co.kr/contents/OPP/INFO/service/OPPINFO004.cmd) — 주식/지수서비스·시작일, 직접 | 종목기본/일별매매/지수 coverage |
| K2 | [KRX 이용약관](https://openapi.krx.co.kr/contents/OPP/INFO/OPPINFO002.jsp) — §5·6·8·10·11, 직접. 시행2025-12-26 | 비상업·제3자제공금지·출처표시·키10,000/day·1년·종료이후금지 |
| K3 | [KRX 이용방법](https://openapi.krx.co.kr/contents/OPP/INFO/OPPINFO003.jsp) — STEP01~04, 직접 | 인증키와API활용신청의관리자승인이각각필요 |
| T1 | [Toss overview](https://openapi.tossinvest.com/openapi-docs/overview.md) — 시세정보/시작하기/Rate Limits, 직접; [API reference](https://openapi.tossinvest.com/openapi-docs/latest/api-reference/README.md), 직접 | 국내/미국·ClientCredentials·허용IP·시장/계좌분리·그룹TPS. latest문서는개정일미표시 |
| T2 | [Toss MarketDataApi](https://openapi.tossinvest.com/openapi-docs/latest/api-reference/Apis/MarketDataApi.md) — getCandles/getPrices, 직접 | 1m/1d·200·nextBefore·adjusted기본true |
| T3 | [Toss StockInfo](https://openapi.tossinvest.com/openapi-docs/latest/api-reference/Models/StockInfo.md) — Properties, 직접 | name/market/ISIN/shares/listDate, 대표/설립/재무실적프로필아님 |
| T4 | [Toss MarketInfoApi](https://openapi.tossinvest.com/openapi-docs/latest/api-reference/Apis/MarketInfoApi.md) — getExchangeRate, [MarketIndicatorsApi](https://openapi.tossinvest.com/openapi-docs/latest/api-reference/Apis/MarketIndicatorsApi.md) — getMarketIndicatorCandles, 직접 | 특정시각FX·유효시간·지수1분봉. 최장FX이력미확인 |
| T5 | [Toss 오픈API 약관](https://home.tossinvest.com/ko/terms/v2?id=752), [대체페이지](https://corp.tossinvest.com/ko/contents/terms?id=752) — 정적HTML/영문경로/raw시도 | 약관본문은client rendering으로열람못함. 검색에서발견된2026-08-12개정·계좌자격문구를검증완료근거로사용하지않음. 표시/전송/가격은unknown |
| Y1 | [Yahoo Exchanges and data providers](https://help.yahoo.com/kb/finance/SLN2310.html) — 첫문단/coverage/data-provider disclaimers, 직접 | Do not redistribute, 한국/일본20분지연; APIlicense가아님 |
| Y2 | [Yahoo Terms](https://legal.yahoo.com/us/en/yahoo/terms/otos/index.html) — §2.4.9·2.5·2.8·6, 직접 | 자동수집사전허락·재사용제한. 자체AI기능동의가우리권리로이전되지않음. 지역/제품추가조건도확인필요 |
| M1 | [Massive Ticker Overview](https://massive.com/docs/rest/stocks/tickers/ticker-overview) — response/planhistory, 직접 | name/MIC/homepage/SIC/list_date; CEO/설립없음 |
| M2 | [Massive Custom Bars](https://massive.com/docs/rest/stocks/aggregates/custom-bars) — query/response/access·recency·history, 직접 | OHLCV·무거래봉없음·adjusted·page·tier이력 |
| M3 | [Market Data Terms PDF](https://massive.com/terms/market_data_terms.pdf) — 본문§1·2·5·10·11, 직접.표시개정일2024-10-09 | 개인용·외부사용자앱금지·재배포/파생/non-display·종료삭제·다른계약과충돌규칙 |
| M4 | [Massive stocks](https://massive.com/stocks) — free-tier/FAQ/AI문구, [pricing](https://massive.com/pricing), [공식rename](https://massive.com/blog/polygon-is-now-massive), 직접 | US·무료5req/min·Business필요·2025-10-30rename. 핵심가격카드는Loading이라금액미확인. AI마케팅과약관을분리 |
| M5 | [기본 News](https://massive.com/docs/rest/stocks/news), [Benzinga News](https://massive.com/docs/rest/partners/benzinga/news) — response/plan/history, 직접 | 기본news는본문없음; 별도benzinga/v2/news는body있음·headline-only도있음·2009history |
| M6 | [Benzinga 개인상품](https://massive.com/partners/benzinga) — Transparent Pricing, [Business](https://massive.com/partners/business-benzinga) — Plans for Business, 직접 | 개인News$99/month/Individualuseonly·Business가격문의. model-send·retention·redisplay세부주문서미확인 |
| N1 | [Naver API 약관](https://developers.naver.com/products/intro/terms/terms.md) — **raw HTML의ssrContent**를실제읽음. **2026-10-07개정**; 일반7.3/8, 검색특약2.1~2.4, 부칙 | AI명시금지·기간/목적제한캐시·원출처링크·신규중단/HUB별도절차. 검색snippet의2026-09-07보다실제본문을우선 |
| N2 | [Naver Developers 뉴스API](https://developers.naver.com/docs/serviceapi/search/news/news.md) — raw의개요/요청/응답, 직접 | 제목·패시지·원문URL만. 오래된25,000/day·등록설명은이관현재정책과구분 |
| N3 | [HUB 뉴스API](https://api.ncloud-docs.com/docs/naver-api-hub-search-news) — 요청/응답items, 직접. updated2026-09-17 | endpoint/header·본문없음·개별페이지25,000/day문구 |
| N4 | [HUB overview](https://guide.ncloud-docs.com/docs/apihub-overview), [사용준비](https://guide.ncloud-docs.com/docs/apihub-spec) — 기능/가격참고/FAQ, 직접. updated2026-09-17 | 한시적무료·월775,000/50RPS·개별news일한도와충돌. 별도HUB약관상AI권한미확인 |
| G1 | [Google OIDC](https://developers.google.com/identity/openid-connect/openid-connect) — Settingup/Serverflow/Exchange code/IDclaims, 직접 및Context7 `/websites/developers_google_identity` | 등록/redirect/code교환/state/nonce/sub. Google기존공식문서의각flow조건을구분 |
| G2 | [Google ID token verification](https://developers.google.com/identity/gsi/web/guides/verify-google-id-token) — Verifycriteria/emailauthority, 직접및Context7 | signature/aud/iss/exp·sub·email확인. tokeninfo는debug용이라는Context7공식문서절 |
| G3 | [Google API user data policy](https://developers.google.com/terms/api-services-user-data-policy) — privacy/minimalpermissions/unauthorizeduse, 직접 | 공개privacyURL·최소권한·고지목적·보안. 민감/제한scope추가요건을일반profile에무조건적용하지않음 |
| C1 | [Kakao 설정](https://developers.kakao.com/docs/ko/kakaologin/prerequisite) — 로그인/redirect/clientsecret/OIDC/동의/추가기능, 직접 | 앱등록·설정·이메일등추가권한선행 |
| C2 | [Kakao REST](https://developers.kakao.com/docs/ko/kakaologin/rest-api) — request-code/request-token/userinfo/OIDCresponse, 직접 | code·state/nonce·email조건·secret기본활성·앱별sub |
| C3 | [Kakao 활용](https://developers.kakao.com/docs/ko/kakaologin/utilize#oidc-id-token-verify) — OIDC검증절, 직접 | iss/aud/exp/nonce+JWKS서명검증·캐시권장 |
| C4 | [Kakao quota](https://developers.kakao.com/docs/ko/getting-started/quota) — 무료월quota/rate limits, 직접 | 전체API3m/month·사용자토큰발급제한. 요금정책변경가능 |
| L1 | `prototype/bff/src/zoop_bff/{quote_yahoo.py,quote_naver.py,quote_toss.py,market_data.py,config.py}`, §1에읽은범위표기 | 현재코드동작·부족한필드. 런타임/환경값을확인했다는뜻이아님 |
| P1 | `docs/evidence/poc-backend.md:20,84,93,141-151` | 기존뉴스권한부여와약관한계·원문버전/offset. 새법적허가를입증하지않음 |

## 조사 한계와 후속 검증

- SEC 공식직접열람은반복적으로403이었다. 공식Context7절로API계약을확인했지만, 네트워크호출성공·rate수치·모든첨부물권리는확인하지못했다.
- Toss의공식기술문서는읽었지만현행이용약관본문은정적reader/raw/대체URL로확보하지못했다. 이실패를‘금지없음’이나‘공개API=재배포가능’으로바꾸지않았다.
- HUB rate는같은공식문서군안에일/월표현충돌이있다. 월775,000/50RPS를현재overview설명으로기록하되다른문구를숨기지않았다. 별도이용계약의AI·보관권리는unknown이다.
- 상품coverage는공급자주장이고현재카탈로그종목별실응답확인이아니다. 특히일본기업설립일·대표와국내업종코드명칭은완료됐다고할수없다.
- 유료가입·실키요청·본문수집·계정설정·테스트는수행하지않았다. 후속승인후Main이실제공급원contract test(미제공·잘못된키·한도·기간·회계기준), OAuth취소/만료/state·nonce/서명/이메일없음·충돌, 재표시/보관기한정책을검증해야한다.
