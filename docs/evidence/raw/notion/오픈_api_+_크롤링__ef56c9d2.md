# 오픈 api + 크롤링
notion_id: 3d6fef49-d8d5-80c6-ad10-e1c6ef56c9d2
database: 🤡회의록
- 날짜: 2026-09-09

## **기업 상세정보/재무/공시 **
[https://opendart.fss.or.kr/guide/detail.do?apiGrpCd=DS001&apiId=2019001](https://opendart.fss.or.kr/guide/detail.do?apiGrpCd=DS001&apiId=2019001)
[https://www.sec.gov/search-filings/edgar-application-programming-interfaces](https://www.sec.gov/search-filings/edgar-application-programming-interfaces)
→ 해외기업 확인해야함
## **주식 시세 및 종목 정보**
[https://developers.tossinvest.com/docs#description/introduction](https://developers.tossinvest.com/docs#description/introduction)
[https://openapi.krx.co.kr/contents/OPP/INFO/service/OPPINFO004.cmd](https://openapi.krx.co.kr/contents/OPP/INFO/service/OPPINFO004.cmd)
## **보도자료**
[https://www.newswire.co.kr/coalition](https://www.newswire.co.kr/coalition)
[https://developers.naver.com/docs/serviceapi/search/news/news.md#뉴스](https://developers.naver.com/docs/serviceapi/search/news/news.md#%EB%89%B4%EC%8A%A4)
( 네이버 뉴스 API는 2026년 9월 개정 약관에서는 검색 API 데이터를 **가공 없이 독립적으로 노출**하도록 하고, 검색 API 데이터를 복사·저장·캐싱하거나 파생물을 만드는 행위를 제한하는 내용)
- ▸ 네이버 뉴스 API
  ```
{
    "lastBuildDate": "Thu, 11 Jun 2026 19:03:00 +0900",
    "total": 2388472,
    "start": 1,
    "display": 2,
    "items": [
        {
            "title": "네이버, '로컬 그라운드' 캠페인 추진 … AI 기반 지역상권 지원 확대",
            "originallink": "http://www.worktoday.co.kr/news/articleView.html?idxno=85535",
            "link": "http://www.worktoday.co.kr/news/articleView.html?idxno=85535",
            "description": "네이버는 부산 지역과의 협력 사례로 로컬 브랜드 '모모스 <b>커피</b>'를 소개하며, 플랫폼을 통한 지역 브랜드의 전국 확산 가능성을 강조했다. 이번 캠페인은 로컬 상권의 디지털 전환과 관광·소비 활성화를 동시에 겨냥한... ",
            "pubDate": "Thu, 11 Jun 2026 18:34:00 +0900"
        },
        {
            "title": "인천시, 송도 아파트서 '마을기업 연계축제' 개최",
            "originallink": "https://www.gukjenews.com/news/articleView.html?idxno=3606281",
            "link": "https://www.gukjenews.com/news/articleView.html?idxno=3606281",
            "description": "행사장에서는 천연버물리, <b>커피</b>드립백, 나전칠기 키링 만들기 등 온 가족이 즐길 수 있는 무료 문화 체험 프로그램도 운영된다. 마을기업 연계축제는 주민 생활공간인 아파트 단지에서 열려, 마을기업의 가치와 제품을... ",
            "pubDate": "Thu, 11 Jun 2026 18:30:00 +0900"
        }
    ]
}
```
  이것도 요약 원문이 나오는 것은 아님.
### RSS
- Google News RSS → 실패
  - 언론사 원문 URL이 아니라 Google 중계 링크이거나, 해당 언론사가 자동 요청을 차단하기 때문
- ‣ 한경 RSS → 성공
- ‣ 매일경제 RSS → 성공
- ‣ 
- ‣ 
- ‣  동아일보 RSS
- ‣ 연합뉴스 RSS 
- ‣ 
공시 → 공식적인 사실과 수치
뉴스 → 사건에 대한 설명과 시장 반응
GraphDB → 기업·이슈의 연결 관계
AI → 내용을 요약하고 영향 가능성을 설명
주가 데이터 → 공시 전후 실제 시장 반응 확인
크롤링 시간에 따라 목표하는 방향…