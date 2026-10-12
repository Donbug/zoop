# erd

- Notion ID: 3f3fef49-d8d5-80f0-b1ae-cdaf2bd7d404
- Source: https://www.notion.so/3f3fef49d8d580f0b1aecdaf2bd7d404
- Collected: 2026-10-10T16:50:38.619971+09:00
- Last edited (metadata only): 2026-10-08T17:49:00.589000+09:00

<!-- block: b5c4dd94-52a2-440d-ae15-25159616f96f; type: table -->
<!-- block: da4c0c43-7ddd-47c3-a969-710ef38d00a3; type: table_row -->
| 기능 단위 | 주요 엔티티 | 주 담당 |

<!-- block: 7f8093db-57c7-436b-9011-4480dd57b540; type: table_row -->
| 1. 회원·인증 | MEMBER, MEMBER_SESSION, SOCIAL_IDENTITY, TERM, TERM_AGREEMENT | 임현 |

<!-- block: ab7b03df-cd52-4160-bd5b-e71f4d8daaad; type: table_row -->
| 2. 온보딩·개인설정·관심종목 | MEMBER_SETTING, WATCHLIST, COMPANY | 임현 |

<!-- block: 3192f35b-725a-443e-9349-a4869bb1e317; type: table_row -->
| 3. 모의계좌·보유종목 | PORTFOLIO_CONNECTION, HOLDING, COMPANY | 임현 |

<!-- block: 966c9102-349f-4822-9a32-b678271bcd15; type: table_row -->
| 4. 기업·콘텐츠·근거 조회 | COMPANY, ARTICLE, EVENT, EVENT_ARTICLE, EVIDENCE, DOCUMENT_SENTIMENT | 정세빈 |

<!-- block: 7065c668-2291-42b3-bfa9-3d219b68cabf; type: table_row -->
| 5. Graph 연계·관계 조회 | COMPANY_EVENT_RELATION, GRAPH_VERSION, COMPANY, EVENT, EVIDENCE | 정세빈 |

<!-- block: f1273f8b-ad0f-4dcd-92a4-c6a8875710b6; type: table_row -->
| 6. 브리핑 | BRIEFING_ROUND, BRIEFING_ITEM, BRIEFING_OUTLOOK, BRIEFING_CORRECTION, GRAPH_VERSION | 홍정현 |

<!-- block: c25ed6e1-cd72-4b23-b8cb-9a4ca367cd87; type: table_row -->
| 7. AI 챗봇 | CHAT_SESSION, CHAT_JOB, CHAT_RESULT, CHAT_CITATION | 김도현 |

<!-- block: 4c8ec2fc-88a5-4e02-a474-050ae9a10e8b; type: table_row -->
| 8. 관리자·검수·운영 | ADMIN, ADMIN_SESSION, AUDIT_LOG, REVIEW_CANDIDATE, REVIEW_DECISION, ANALYSIS_JOB | 홍정현 |


<!-- block: 3f3fef49-d8d5-80c5-b2d1-da3acfa92014; type: text -->

<!-- block: 3f3fef49-d8d5-800f-ae1b-f4659f780c85; type: sub_sub_header -->
#### 1 회원·인증 ERD 

<!-- block: 3f3fef49-d8d5-8007-9250-ec981fc8dcf3; type: image -->
- image: mermaid-diagram (1).png
  source: attachment:d8d0f0e5-8b57-44f7-b9d3-a9606c4c3471:mermaid-diagram_(1).png

<!-- block: 3f3fef49-d8d5-80ca-be55-dcc760347dfe; type: text -->

<!-- block: 3f3fef49-d8d5-800f-9295-f54f31541c2c; type: sub_sub_header -->
#### 2 온보딩·개인설정·관심종목 ERD

<!-- block: 3f3fef49-d8d5-8068-b329-e221ffba2614; type: image -->
- image: mermaid-diagram (2).png
  source: attachment:cde69921-c1bf-4066-a0ff-4f6e2d9ef22d:mermaid-diagram_(2).png

<!-- block: 3f3fef49-d8d5-8076-b103-e90768606635; type: text -->

<!-- block: 3f3fef49-d8d5-8073-8e83-f255e66f4300; type: sub_sub_header -->
#### 3 모의계좌·보유종목 ERD

<!-- block: 3f3fef49-d8d5-80f8-aef5-e17ddf659167; type: image -->
- image: mermaid-diagram (3).png
  source: attachment:9a6ad557-9054-4aa3-afc3-b92ee5c7560e:mermaid-diagram_(3).png

<!-- block: 3f3fef49-d8d5-80a9-81af-da0c3606f4d5; type: text -->

<!-- block: 3f3fef49-d8d5-80ab-acca-ffe34de20a7d; type: sub_sub_header -->
#### 4 기업·콘텐츠·근거 조회 ERD

<!-- block: 3f3fef49-d8d5-8010-959a-cae382526f3f; type: image -->
- image: mermaid-diagram (4).png
  source: attachment:69ce0518-ef8c-4233-99cc-bbb647f59066:mermaid-diagram_(4).png

<!-- block: 3f3fef49-d8d5-8068-abee-da749a16bb8a; type: text -->

<!-- block: 3f3fef49-d8d5-80be-9c84-d0c5109274d2; type: sub_sub_header -->
#### 5 Graph 연계·관계 조회 ERD

<!-- block: 3f3fef49-d8d5-80eb-bf09-fd50f7884cbf; type: image -->
- image: mermaid-diagram (5).png
  source: attachment:7a7f1876-2454-4786-bee7-7b99180fe168:mermaid-diagram_(5).png

<!-- block: 3f3fef49-d8d5-802f-86eb-fef8693d807d; type: text -->

<!-- block: 3f3fef49-d8d5-8035-a949-e6faf4f2a270; type: sub_sub_header -->
#### 6 브리핑 ERD

<!-- block: 3f3fef49-d8d5-80de-83ef-f159b551c5de; type: image -->
- image: mermaid-diagram (6).png
  source: attachment:476af069-c5dd-4250-8a37-5d270cf2c974:mermaid-diagram_(6).png

<!-- block: 3f3fef49-d8d5-80bf-bc74-e88a0cf7b72e; type: text -->

<!-- block: 3f3fef49-d8d5-8032-ae16-ef7c72f3d5ba; type: sub_sub_header -->
#### 7 AI 챗봇 ERD

<!-- block: 3f3fef49-d8d5-80cf-850f-eab73e1ce0bf; type: image -->
- image: mermaid-diagram (7).png
  source: attachment:73f60743-a328-417d-a1f1-6481cc4a5999:mermaid-diagram_(7).png

<!-- block: 3f3fef49-d8d5-806b-ab56-c1801140842f; type: text -->

<!-- block: 3f3fef49-d8d5-8003-a5ef-ddd508cd1ca1; type: sub_sub_header -->
#### 8 관리자·검수·운영 ERD

<!-- block: 3f3fef49-d8d5-8030-a465-f719f185ce2d; type: image -->
- image: mermaid-diagram (8).png
  source: attachment:2c52b313-975d-4a26-979b-bf48558cb699:mermaid-diagram_(8).png

<!-- block: 3f3fef49-d8d5-80e2-8664-cb0fd7c019e7; type: text -->

<!-- block: 3f3fef49-d8d5-8029-a810-fda675ec5949; type: text -->

<!-- block: 3f3fef49-d8d5-8017-be3a-ff409f09b048; type: file -->
- file: zoop-core-erd.md
  source: attachment:7a4bb06c-2901-427d-b7a4-acb8b8fdf103:zoop-core-erd.md

<!-- block: 3f3fef49-d8d5-8092-b33c-d5c7da141458; type: text -->

<!-- block: 3f3fef49-d8d5-8049-af65-cfdd3050f8c1; type: text -->

