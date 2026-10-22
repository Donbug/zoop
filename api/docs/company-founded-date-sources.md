| NASDAQ:AMZN | 1996-05-28 | [Amazon 정관(SEC 첨부)](https://www.sec.gov/Archives/edgar/data/1018724/000110465922065872/tm2215904d1_ex3-1.htm)의 최초 설립증서 접수일. 현재 법인 Amazon.com, Inc.(Delaware) 기준. 10-K는 1994년 Washington 설립만 밝히고 일자가 없어 사용하지 않음. |

확인일: 2026-10-22. 대상: `src/main/resources/company/demo-companies.json`의 해외 기업 15곳. 그중 공식 자료로 일자를 확인한 13곳만 채우고 Microsoft·Anthropic은 비운다.
기업 상세 D-COM-03 / `getCompany`의 `foundedDate`를 채운다. 연도나 월만 있는 자료를 임의의 일자로 보충하지 않는다.

공식 연혁의 창립일을 사용하되, 별도로 설립된 지주회사인 Alphabet·Broadcom·Arm Holdings와 사명 변경·재설립을 거친 Meta·Amazon은 카탈로그의 정식 법인명에 해당하는 법인의 설립일을 사용했다. OpenAI는 조직의 기원인 OpenAI, Inc. 설립일이며 현재 정식명 OpenAI Group PBC의 전환일이 아니다. 이 필드는 모든 기업의 현재 법인 등기일만을 뜻하지는 않는다.

| 기업 ID | 설립일 | 근거 및 기준 |
| --- | --- | --- |
| ORG:OPENAI | 2015-12-08 | [OpenAI, Inc. 설립증서 사본](https://gwern.net/doc/reinforcement-learning/openai/2017-openai-bylaws.pdf)의 Delaware 접수일. 2015-12-11은 공개 발표일이므로 사용하지 않음. |
| ORG:ANTHROPIC | 2021-01-26 | [Anthropic, PBC 정관 사본](https://www.scribd.com/document/1044265398/Anthropic-CoI-2024-5-20) 첫 페이지의 최초 설립증서 접수일. 회사 작성 원문을 제3자 보관본으로 확인. |
| NASDAQ:ASML | 1984-04-01 | [ASML 공식 창립 연혁](https://www.asml.com/en/company/stories/2024/asml-founding-story). ASM Lithography 창립일. |
| NYSE:TSM | 1987-02-21 | [TSMC 공식 20주년 연혁](https://investor.tsmc.com/static/annualReports/2006E/20years/milestones.html). |
| NASDAQ:NVDA | 1993-04-05 | [NVIDIA 공식 연혁](https://www.nvidia.com/en-in/about-nvidia/corporate-timeline/). |
| NASDAQ:AMD | 1969-05-01 | [AMD 투자자 FAQ](https://ir.amd.com/contacts-faq/faq). |
| NASDAQ:AAPL | 1976-04-01 | [Apple 공식 50주년 발표](https://www.apple.com/eg/newsroom/2026/03/apple-to-celebrate-50-years-of-thinking-different/). 창립일이며 1977년 법인화와 구분. |
| NASDAQ:MU | 1978-10-05 | [Micron 공식 CSR 정책](https://in.micron.com/about/corporate-citizenship/micron-gujarat-csr-policy). |
| NASDAQ:MSFT | 1975-04-04 | [Microsoft 공식 설명](https://devblogs.microsoft.com/oldnewthing/20160209-00/?p=93002)의 창립일. |
| NASDAQ:META | 2004-02-04 | [Meta 공식 회사 연혁](https://www.meta.com/about/company-info/). Facebook 창립 기준. |
| NASDAQ:AMZN | 1994-07-05 | [Amazon 1997년 10-K 사본](https://www.annualreports.com/HostedData/AnnualReportArchive/a/NASDAQ_AMZN_1997.pdf), 재무제표 주석의 최초 설립일. 웹사이트 개설일과 구분. |
| NASDAQ:GOOGL | 2015-07-23 | [Alphabet 설립증서(SEC 첨부)](https://www.sec.gov/divisions/corpfin/cf-noaction/14a-8/2021/cheveddenalphabet041621-14a8.pdf). Google 창립일이나 지주회사 전환 완료일이 아닌 Alphabet 법인 최초 설립일. |
| NASDAQ:INTC | 1968-07-18 | [Intel 공식 창립 연혁](https://www.intel.com/content/www/us/en/history/virtual-vault/articles/intels-founding.html). |
| NASDAQ:AVGO | 2018-01-17 | [Broadcom 설립증서 변경 공시](https://www.sec.gov/Archives/edgar/data/1730168/000119312518094342/d548679dex31.htm)의 최초 설립증서 접수일. 전신 Broadcom Corporation·Avago의 창립이나 2018-04-04 본점 이전 완료일과 구분. |
| NASDAQ:ARM | 2018-04-09 | [Arm 2026년 20-F](https://investors.arm.com/node/8281/html), Item 4.A. 현재 상장사 Arm Holdings plc(11299879)의 설립일. 자회사 Arm Limited(02557590)의 1990-11-12 설립일과 구분. |

API·스키마·마이그레이션 변경은 없다. 기존 DB의 화면에 반영하려면 `api/README.md`의 `catalog-import` 명령을 다시 실행한다.
