# 역할 배정

- Notion ID: 3edfef49-d8d5-80c5-8c43-c30b18ce9cbb
- Source: https://www.notion.so/3edfef49d8d580c58c43c30b18ce9cbb
- Collected: 2026-10-10T16:50:38.619971+09:00
- Last edited (metadata only): 2026-10-06T13:50:03.479000+09:00

<!-- block: 3edfef49-d8d5-8047-b336-eccd60671fe4; type: sub_sub_header -->
#### 역할분담 (FE 2, BE 3, AI 2, Cloud 1)
<!-- block: fa2d74d6-b26b-41f5-a18e-3165e7624b68; type: sub_header -->
### 1. 백엔드 A — 회원·포트폴리오·기업 상세

<!-- block: 531a4b88-69dc-4b6e-a1fe-a130f90e48b7; type: text -->
담당자: __________

<!-- block: 1c057b37-1b1b-4fb7-9691-d6c70b48317a; type: sub_sub_header -->
#### 담당 범위

<!-- block: 2ec595d2-0c98-4c5a-994c-f9c2cd7854cc; type: bulleted_list -->
- 회원가입·로그인·소셜 로그인

<!-- block: 62d0f851-925e-4aee-af99-a8a00d828fef; type: bulleted_list -->
- JWT 인증, 비회원/회원/관리자 권한

<!-- block: 58755757-ad3d-4cf3-bda5-25fed3ff1a56; type: bulleted_list -->
- 온보딩 상태 저장

<!-- block: 501b327f-43d9-4d61-b68d-09d757ff2d57; type: bulleted_list -->
- 관심 종목·가상계좌·모의 보유 데이터


<!-- block: 350d7052-ca74-4b8d-a192-1b01cec85175; type: bulleted_list -->
- 기업 기본 정보·재무·시세·뉴스·공시 조회 API

<!-- block: 079612e6-eb29-425a-a735-d99cec723b57; type: bulleted_list -->
- 기업 상세 페이지용 API < 주식차트, (그래프, 타임라인 제외)

<!-- block: 4f9942ab-d255-4662-a454-d4b18036c6c3; type: sub_sub_header -->
#### WBS 연결

<!-- block: 5ed409c3-cd70-44fa-a0f1-25f4405cdf7f; type: bulleted_list -->
- FS001~FS016

<!-- block: 402b0ea3-7c89-4214-8d7b-53d962e0caf1; type: bulleted_list -->
- FS054 사용자·모의 보유

<!-- block: d44d0b40-43d3-4885-b19c-6e5119d12504; type: bulleted_list -->
- FS061 소셜 인증 연동

<!-- block: 128ec65b-dc18-403c-a17f-f770f2952549; type: bulleted_list -->
- FS062 가상계좌 데이터 연동

<!-- block: 9740e807-a3a1-41ad-a7be-3b53719660d6; type: bulleted_list -->
- FS038~FS044

<!-- block: 75770682-786a-45db-b091-f8ce3122af51; type: sub_sub_header -->
#### 완료 기준

<!-- block: 11a382b7-dc34-499d-814a-b89bc26098b0; type: code -->
```plain text
로그인
→ 관심 종목 선택
→ 가상 보유 종목 확인
→ 기업 상세 진입
→ 기본 정보·차트·재무·뉴스·공시 조회
```

<!-- block: f4035e59-34e8-40f6-bd3d-83dc4c27a547; type: sub_sub_header -->
#### 맡지 않는 것

<!-- block: 7ba68853-4699-4e39-b968-82d1891fa9f4; type: bulleted_list -->
- GraphDB 관계 탐색

<!-- block: 1f6b2bd3-d30f-4385-b5f8-83c4554ee550; type: bulleted_list -->
- 뉴스 이슈 추출

<!-- block: f77e0fad-0e2e-4a2e-b978-314ea196b284; type: bulleted_list -->
- 브리핑 생성

<!-- block: 4eb2aec6-9bf9-4d6d-8271-344a333a4103; type: bulleted_list -->
- 챗봇 프롬프트·답변 생성

<!-- block: 8128d020-947a-4d6c-a1e8-6d55c9aa84ff; type: divider -->

<!-- block: ea20f2a5-10cc-4224-80a8-31509a0a5b7b; type: sub_header -->
### 2. 백엔드 B — GraphDB·관계 그래프 API

<!-- block: 20346254-b8a8-4a8b-a7e2-d3d7ef29ed83; type: text -->
담당자: __________

<!-- block: a35ed238-37de-49b0-8b36-a3ac68d3befb; type: sub_sub_header -->
#### 담당 범위

<!-- block: f3580fa1-e420-48e9-9d00-c7ee00c8762f; type: bulleted_list -->
- Neo4j 노드·간선 스키마 < 보여주는것? 

<!-- block: c7fe69d3-231e-4feb-9a91-055790be2fb1; type: bulleted_list -->
- 기업·이슈·문서·제품 관계 적재

<!-- block: 5c5da9a5-2ddb-47ca-b046-8cab5a4758e1; type: bulleted_list -->
- 전체 그래프·관심 종목 그래프·보유 종목 그래프 API

<!-- block: a27fc4f2-834e-4187-a5ea-5d93e9a9c869; type: bulleted_list -->
- 최대 2-hop 관계 탐색

<!-- block: cac95f87-5436-4268-8718-fc334e6e8891; type: bulleted_list -->
- 기업 노드·이슈 노드·간선 상세 조회

<!-- block: 386dc2c1-3f33-472e-b343-a77e138e69e8; type: bulleted_list -->
- 관계 근거 문서 조회

<!-- block: 64001648-4ffe-4474-8c5f-f12bde0186f6; type: bulleted_list -->
- 기준 시점 기반 관계 그래프 조회 < 타임라인

<!-- block: 1b3bada0-a6c6-4453-8cb1-55cbafde251b; type: sub_sub_header -->
#### WBS 연결

<!-- block: 554d6bc1-c756-4d49-bffc-e4d6417020a3; type: bulleted_list -->
- FS055 관계와 근거 연결

<!-- block: 0cbd18f4-2b22-4ec4-82c7-e3a2c0849db3; type: bulleted_list -->
- FS056 이슈와 문서 구분

<!-- block: 24e455d8-a4bf-4efb-9b7a-fce13e24a371; type: bulleted_list -->
- FS017~FS027

<!-- block: cd918544-51ff-442d-ab28-e22f20e7ecc0; type: bulleted_list -->
- FS032 브리핑 관계 그래프

<!-- block: c42b47f6-59a9-4b2f-a9e9-e6ac16025994; type: bulleted_list -->
- FS040-01 시점 기반 관계 그래프

<!-- block: be4f7322-0569-47ac-aa44-686e779f9837; type: sub_sub_header -->
#### 완료 기준

<!-- block: 0de87fbc-c540-460f-99cb-9865b1b7ac02; type: code -->
```plain text
기업 선택
→ 기업과 연결된 이슈·기업·제품 조회
→ 노드·간선 반환
→ 간선 클릭
→ 관계 설명과 근거 뉴스·공시 반환
```

<!-- block: a8586467-0d85-44d0-86b5-0e0de3ab5993; type: sub_sub_header -->
#### AI 담당자에게 받는 데이터

<!-- block: 9ac227d3-6182-4535-82bd-1c2325dc5250; type: code -->
```plain text
{
  "issueId": "ISSUE-001",
  "issueType": "DEMAND_SUPPLY",
  "companies": ["005930", "000660"],
  "relation": "AFFECTS",
  "direction": "POSITIVE_POSSIBLE",
  "confidence": 0.82,
  "evidenceDocIds": ["NEWS-101", "DART-204"],
  "reviewStatus": "VERIFIED"
}
```

<!-- block: 662a272c-c623-45bb-bd3c-fddc1de27028; type: text -->
AI 결과 중 VERIFIED 상태만 실제 사용자 그래프에 넣어.

<!-- block: e228eb95-491f-4839-9772-e23de36aa6dd; type: divider -->

<!-- block: 3daaa760-019e-4731-a13f-885935b05b9a; type: sub_header -->
### 3. 백엔드 C — 데이터 수집·브리핑·AI 실행 연동

<!-- block: 934ac35c-8f6c-4b52-b692-39f774b3dc34; type: text -->
담당자: __________

<!-- block: 6a380b44-dab2-43ab-ac98-45fb930aae7f; type: sub_sub_header -->
#### 담당 범위

<!-- block: 1e0f532c-abda-4ebc-a167-c9151b250d76; type: bulleted_list -->
- 뉴스·공시·시장 데이터 API 연동

<!-- block: 438b1450-4be0-403f-8828-c1d8afbb09f7; type: bulleted_list -->
- 원문·메타데이터 RDB 저장

<!-- block: 3f1fef49-d8d5-8059-89b4-e39a95cdb9f3; type: bulleted_list -->
- AI 이슈 분석 작업 요청·결과 저장



<!-- block: 0b6affd6-36a9-459b-b7dd-5e3d1470e3eb; type: bulleted_list -->
- 뉴스 수집 스케줄러 < 크롤링

<!-- block: f8f9aa01-448e-48dc-8432-0858237d1ed2; type: bulleted_list -->
- AI가 사용할 데이터 조회 도구 제공



<!-- block: 3f1fef49-d8d5-8029-88e9-e0041d43adce; type: bulleted_list -->
- 브리핑 생성 요청·저장·조회 API

<!-- block: 3f1fef49-d8d5-805d-b325-f00c63dae8c4; type: bulleted_list -->
- 챗봇 세션·질문·답변 저장

<!-- block: d8db4ce4-8c63-4b8d-adbf-d0198fbb2aaa; type: sub_sub_header -->
#### WBS 연결

<!-- block: 8c6101a7-1a9e-48ae-a8dd-1ea86420fa75; type: bulleted_list -->
- FS057 브리핑 정보 저장

<!-- block: 5bf46023-4181-4144-9b5a-07f49e39e9a8; type: bulleted_list -->
- FS058 경제 뉴스 수집·이슈 분석

<!-- block: aece50a6-cc6a-48ea-94fd-e5c987607484; type: bulleted_list -->
- FS059 분석 결과 저장·조회 반영

<!-- block: 457ab83e-9658-4c1a-8360-f3444992b504; type: bulleted_list -->
- FS060 대화·질문 기록

<!-- block: 1172e854-0d09-4fe1-84a2-e72db15c37b0; type: bulleted_list -->
- FS063 뉴스·시장 데이터 연동

<!-- block: 70565c34-a90c-4e89-95c6-043eb699eec0; type: bulleted_list -->
- FS064 AI 분석 연동

<!-- block: 044a2f4e-a7fe-4859-9fc7-1ab755f7b71a; type: bulleted_list -->
- FS028~FS035의 서버 API

<!-- block: 33a9d145-b28b-4c3b-9e81-0c4947ecf6b6; type: sub_sub_header -->
#### 완료 기준

<!-- block: d1657871-5f88-4a20-9733-a9d7b6fae3a4; type: code -->
```plain text
뉴스·공시 수집
→ RDB 저장
→ AI 분석 요청
→ 이슈·관계 후보 결과 저장
→ 검증 완료 결과를 GraphDB 담당에게 전달
→ 브리핑·챗봇에서 조회 가능
```

<!-- block: e99636b5-8aed-4617-8a8f-80f3d126b194; type: sub_sub_header -->
#### 맡지 않는 것

<!-- block: 6bae5862-88d3-4c94-b68d-c830937e8c52; type: bulleted_list -->
- 이슈를 판단하는 프롬프트·군집화 로직

<!-- block: ce6ab40f-1337-4429-bc27-662d7e8850dd; type: bulleted_list -->
- GraphDB Cypher 쿼리 설계

<!-- block: c2b4274f-5518-4869-9e21-28c9f0d2c11b; type: bulleted_list -->
- 브리핑 문장 자체 생성

<!-- block: c2e38993-133b-4ba4-9c43-16a6477358df; type: divider -->

<!-- block: f9285224-870b-4da5-8b7e-0b64542c6a7b; type: sub_header -->
### 4. AI 담당 — 이슈 추출·관계 후보 생성

<!-- block: 493b68f6-8ac3-4e2d-9eeb-f089f18af632; type: text -->
담당자: __________

<!-- block: cd031146-d474-4649-b372-e7e9b17a2822; type: sub_sub_header -->
#### 담당 범위

<!-- block: f1ec5734-f85e-4c41-9375-8c73be926380; type: bulleted_list -->
- 기사·공시 전처리

<!-- block: fe0033c9-ba47-474b-9970-57cb1ce8b983; type: bulleted_list -->
- 기업·제품·산업 엔티티 추출

<!-- block: 5b70e63c-b578-4f76-8da8-21b7f20663f1; type: bulleted_list -->
- 이슈 후보 구조화

<!-- block: 36e94b49-f190-4ad4-90bd-bab7cff63ad1; type: bulleted_list -->
- 임베딩 생성과 유사 후보 검색

<!-- block: c003377d-7137-43c7-a607-412a2cfd0e15; type: bulleted_list -->
- 같은 사건 군집화

<!-- block: f569cd28-fb04-4866-8cd3-01d064a4fc2d; type: bulleted_list -->
- 이슈-기업 영향 관계 후보 생성

<!-- block: 6d3a52b4-834e-4628-9d41-a4180c754e16; type: bulleted_list -->
- 관련도·신뢰도·검수 상태 산정

<!-- block: ae6b3f9c-cdf9-40f0-b42c-5b351467e775; type: bulleted_list -->
- 품질 평가 데이터셋 작성

<!-- block: 343240d3-e70a-4f00-8e39-c6552648504d; type: sub_sub_header -->
#### P1 파이프라인

<!-- block: c899912f-f699-4abf-9f81-fdf52e435b5b; type: code -->
```plain text
뉴스 원문
→ 기업·제품·행위·시점 추출
→ 이슈 후보 JSON
→ 유사 후보 검색
→ 동일 사건 군집화
→ 상위 이슈 생성
→ 이슈-기업 관계 후보
→ VERIFIED / REVIEW_REQUIRED / REJECTED
```

<!-- block: 58efd22e-f0ba-4a16-b8aa-9298ca7c122d; type: sub_sub_header -->
#### 완료 기준

<!-- block: 3117ff43-82ca-4c39-a542-9f2c1883a956; type: bulleted_list -->
- 기사 1건에서 구조화된 이슈 후보를 추출한다.

<!-- block: 0daf4219-e046-417d-8f45-4a9ee78f11a7; type: bulleted_list -->
- 유사한 기사 여러 건을 하나의 이슈 후보로 묶는다.

<!-- block: bcc749fc-d040-449d-9b62-dad2a9e2a9f9; type: bulleted_list -->
- 이슈와 기업의 연결 근거 문서를 남긴다.

<!-- block: 5c21ba6a-ebb7-418a-92a1-93683eeb1455; type: bulleted_list -->
- 근거가 부족하면 REVIEW_REQUIRED로 보낸다.

<!-- block: 66e6f721-5cb6-4d02-a7df-c76b284740aa; type: bulleted_list -->
- 모델이 생성한 후보를 바로 공개 GraphDB에 넣지 않는다.

<!-- block: b56b3c3e-aa09-42ee-8cb2-37ab341960c9; type: sub_sub_header -->
#### 맡지 않는 것

<!-- block: 3f1fef49-d8d5-80d3-a5b1-d5816edff1ef; type: text -->

<!-- block: 0a4575fa-20fe-45ca-9eea-9c2f2c8dc177; type: bulleted_list -->
- 수집 스케줄러 운영

<!-- block: d3ec1cd1-336c-43e6-b809-6fbcd0863c61; type: bulleted_list -->
- GraphDB 적재 쿼리 작성

<!-- block: 1b760dcc-005f-4fe0-bf5a-64a5764d405b; type: bulleted_list -->
- 사용자용 챗봇 화면

<!-- block: ab113806-76d0-41b1-9c1b-fae3055ec566; type: bulleted_list -->
- 투자 추천

<!-- block: 49629039-ba49-4576-ac25-97368b50eb99; type: divider -->

<!-- block: a4d970aa-3a3b-4b28-b763-fa131e681bac; type: sub_header -->
### 5. AI/프론트 담당 — 브리핑·챗봇 AI와 일반 화면

<!-- block: 67287352-f4e7-44e3-bb15-0c58b0664d24; type: text -->
담당자: __________

<!-- block: 68e0c8af-9f2e-4e95-ac8b-347c7b1ec7d9; type: sub_sub_header -->
#### AI 담당 범위

<!-- block: ad5d9709-dc8c-4ef8-96c3-bbe9fc54e309; type: bulleted_list -->
- 출근·퇴근 공통 브리핑 프롬프트

<!-- block: 9030bffc-4e53-4403-b027-f8320e4b1587; type: bulleted_list -->
- 핵심 이슈·시장 지표 기반 브리핑 생성

<!-- block: a6651f61-d838-47a9-876d-3c5a90befb38; type: bulleted_list -->
- 챗봇 질문 해석·되묻기

<!-- block: e596198e-98de-4528-a6fb-2bd8cd8d9f20; type: bulleted_list -->
- GraphDB·뉴스·공시 근거 기반 답변 생성

<!-- block: 5c15b901-6a59-46dc-89db-5bf41d36013b; type: bulleted_list -->
- 답변의 근거·한계·후속 질문 구조화

<!-- block: df28e962-8eb7-4fcc-bbc2-09f195deb694; type: bulleted_list -->
- 투자 권유·가격 예측 차단 규칙

<!-- block: 1b88df0d-0ee3-40a7-b657-9d4325ea9ed9; type: sub_sub_header -->
#### 프론트 담당 범위

<!-- block: 65f5806a-3afe-40f3-bee7-e91eda7d335e; type: bulleted_list -->
- 로그인·회원가입·온보딩 UI

<!-- block: 7669b825-3167-4198-990f-3a8b31b6e157; type: bulleted_list -->
- 관심 종목 선택·가상계좌 연결 UI

<!-- block: 27ddf0a7-3bb4-4a0e-b409-ede5cbb2de07; type: bulleted_list -->
- 출퇴근 브리핑 화면

<!-- block: 43fe3878-18a1-48f1-a731-44a2f0beb5e1; type: bulleted_list -->
- AI 챗봇 패널

<!-- block: e0db8b32-a831-4085-8037-93d094322921; type: bulleted_list -->
- 답변 근거 카드·후속 질문 UI

<!-- block: bfa797c5-92ed-4a11-a96d-87a5d194d652; type: bulleted_list -->
- 새 대화·처리 중·오류 상태 UI

<!-- block: 0a2aa5dc-f07e-4870-96fe-e1cb18993b28; type: sub_sub_header -->
#### WBS 연결

<!-- block: 7b6a1464-a7c4-4247-8eb5-9689b3bd64c1; type: bulleted_list -->
- FE: FS001~FS016, FS028~FS035, FS045~FS051

<!-- block: ff91b122-0663-439c-8882-466e9ca9a3d1; type: bulleted_list -->
- AI: 핵심 이슈 선정, 브리핑 생성, 챗봇 답변 생성

<!-- block: 23a9897f-9ca4-4c5a-b922-7415b270b697; type: sub_sub_header -->
#### 중요 원칙

<!-- block: 479ce805-6e16-4b73-8ccb-92fa55c38be8; type: text -->
개인화 브리핑, 좋아요/싫어요, 복잡한 대화 목록은 P2야.

<!-- block: 775b5fc4-c5b4-4771-8e57-9083bc46923e; type: text -->
이 담당자는 MVP에서 아래 두 흐름만 완성하면 돼.

<!-- block: c1a151e6-f604-4f93-a484-03e95a16c526; type: code -->
```plain text
공통 시장 브리핑
→ 핵심 이슈
→ 관련 기업 그래프
→ 근거 문서
```

<!-- block: f0094822-909e-4573-b356-88efeaa6d666; type: code -->
```plain text
기업·이슈·관계 선택
→ AI 질문
→ 근거 기반 답변
→ 그래프·원문 탐색
```

<!-- block: 5507c72d-80e5-49ea-bb9f-3b0e8c250935; type: divider -->

<!-- block: 7f7d40d9-f5b6-4855-a961-18f0eeef408b; type: sub_header -->
### 6. 프론트 담당 — 관계 그래프·기업 상세

<!-- block: 516b6fb0-6f8d-4cd0-a5b1-aac1996b836b; type: text -->
담당자: __________

<!-- block: cc5cd31e-4673-40b7-ba42-e6e8724a0bb6; type: sub_sub_header -->
#### 담당 범위

<!-- block: 0905d5f1-6031-4a45-855c-9c62ad9b07b4; type: bulleted_list -->
- 전체·관심 종목·보유 종목 관계 그래프

<!-- block: b4ef966b-2a24-41c0-a1ec-9ae85f8d7595; type: bulleted_list -->
- 노드 확장·접기·확대·축소·이동

<!-- block: eda4f14c-e120-4af2-a6a3-4cefb50b080c; type: bulleted_list -->
- 기업·이슈·제품 노드 표현

<!-- block: 9a4a1ab5-fee1-4d50-a30f-66d81646d8f5; type: bulleted_list -->
- 기업/이슈/간선 선택 패널

<!-- block: b861c068-3b89-4721-b3ea-57cbea426972; type: bulleted_list -->
- 관계 근거 패널

<!-- block: 627767ff-dd50-4c09-800d-7955ddd4705f; type: bulleted_list -->
- 사이드바 종목 선택·필터

<!-- block: 848bdd96-12fe-4e2c-ba7f-cb8e89157452; type: bulleted_list -->
- 기업 상세 페이지

<!-- block: ae3e0d24-50e6-4fb2-904e-66b6ec359a7d; type: bulleted_list -->
- 차트·타임라인·시점 기반 관계 그래프

<!-- block: 2fac62b1-f585-4c44-b4c3-0e0d162197a2; type: sub_sub_header -->
#### WBS 연결

<!-- block: fdbc8036-17a8-4234-a0fd-175168afba32; type: bulleted_list -->
- FS017~FS027

<!-- block: 81c1baa1-0612-4891-96ac-4e0e63ba430a; type: bulleted_list -->
- FS038~FS044

<!-- block: c7f797f1-2e1f-464f-a7bf-adc948356a34; type: bulleted_list -->
- FS040-01

<!-- block: 8f774209-072d-40d4-9d83-d567a07b9d03; type: sub_sub_header -->
#### 완료 기준

<!-- block: 40ed592c-c91e-484a-b3e1-50c163a36cfe; type: code -->
```plain text
그래프 진입
→ 기업 노드 선택
→ 관련 기업·이슈 노드 확장
→ 이슈 선택
→ 근거 뉴스 노드·문서 표시
→ 간선 선택
→ 관계 설명·근거 표시
→ 상세 페이지 이동
```

<!-- block: 50cdc392-49bc-4648-94c2-6dbdebe24faf; type: text -->
이 사람은 그래프 완성도를 책임지는 사람이므로 로그인·브리핑·챗봇 일반 화면을 맡기면 안 돼.

<!-- block: 16875600-9558-4165-a7f4-ec9a68f26c50; type: divider -->

<!-- block: 64ba9bc5-62bf-4527-be89-c6ce0f9100af; type: sub_header -->
### 7. 클라우드·DevOps 담당 — 실행 환경·배포·운영

<!-- block: 81901d3c-8d78-48e7-bd68-29aeea663819; type: text -->
담당자: __________

<!-- block: 7009c66c-3116-4fb3-aa96-e50ef5a81c6e; type: sub_sub_header -->
#### P1 담당 범위

<!-- block: 65413116-597d-4b0a-ae4f-e030a7da35da; type: bulleted_list -->
- Docker Compose

<!-- block: e33b4a81-71e1-4d12-a8b6-20f4f5a534e3; type: bulleted_list -->
- 개발·테스트·배포 환경

<!-- block: e3753d08-1025-4e76-ab32-cd4424734549; type: bulleted_list -->
- 프론트·백엔드·AI 서비스 배포

<!-- block: 5533d189-7ab5-4030-a766-9083265fc2c6; type: bulleted_list -->
- PostgreSQL·Neo4j 실행

<!-- block: 52ef8ece-4486-4d27-be94-23b8c0023fa9; type: bulleted_list -->
- 환경변수·API Key·Secret 관리

<!-- block: e0bf671c-de29-47e0-8a12-3a0ec15ae233; type: bulleted_list -->
- CI/CD 기본 파이프라인

<!-- block: 3122ccba-50cf-4f81-8bc6-cb5526bb4d98; type: bulleted_list -->
- 뉴스·브리핑 스케줄러 실행 환경

<!-- block: d7d3d51b-8875-44e7-b2ce-e4bb3e374ba9; type: bulleted_list -->
- 로그·오류 확인

<!-- block: 2cb5ede2-40c3-48af-b792-77973058dfdc; type: bulleted_list -->
- 배포 후 헬스체크

<!-- block: 380c7b63-bc83-4150-814c-01884621cf7e; type: sub_sub_header -->
#### P2로 미룰 것

<!-- block: 756e02ac-66e1-4f42-9118-b184e59dca35; type: bulleted_list -->
- 자동 백업·복구 체계

<!-- block: 4ee349be-9aaf-4c20-a6df-eda07fac9d89; type: bulleted_list -->
- 고도화된 성능 모니터링

<!-- block: 89b9c3d4-197d-47fd-b669-5b2ffa198395; type: bulleted_list -->
- 정교한 네트워크·보안 정책

<!-- block: 33020fc3-d749-4f23-bf69-5ad8fe491bc0; type: bulleted_list -->
- AI 비용 대시보드

<!-- block: 20a32901-4f6b-4da4-ac07-0d62ac6363e6; type: bulleted_list -->
- Kubernetes

<!-- block: 504ec367-0b51-4ccd-be54-4372c93c1653; type: bulleted_list -->
- 복잡한 장애 자동 복구

<!-- block: d02c6709-e946-48b9-a801-e2108d3918c1; type: sub_sub_header -->
#### 완료 기준

<!-- block: 69b4edc3-6277-4e48-aa7a-1e838667cb9a; type: code -->
```plain text
git push
→ CI 실행
→ Docker 이미지 빌드
→ 서버 배포
→ PostgreSQL·Neo4j·API·FE 정상 연결
→ 수집·브리핑 스케줄러 실행 확인
```

<!-- block: fd8f4a5e-9db2-4aab-8b42-bbc5ef02a101; type: divider -->

<!-- block: 4f833493-d181-4ff8-83c2-0f77734aae97; type: sub_header -->
### 필수 협업 지점

<!-- block: bd52302a-a041-478d-afad-de84823f1670; type: table -->
<!-- block: e8900c64-fc79-42eb-8af7-d98fb988bd98; type: table_row -->
| 전달자 | 수신자 | 전달물 |

<!-- block: 6c9c8954-ee15-47a2-9386-01d3307f8968; type: table_row -->
| AI 담당 | 백엔드 B | 검증 상태가 포함된 이슈·관계 후보 JSON |

<!-- block: c575ae81-d434-4b24-a925-56a2e7e30a2d; type: table_row -->
| 백엔드 B | 프론트 담당 | 그래프·노드·간선·근거 API |

<!-- block: 974b838e-eaf7-46eb-8135-2962d4322c79; type: table_row -->
| 백엔드 C | AI 담당 | 뉴스·공시 원문·시장 데이터 |

<!-- block: 1cd11d04-0d38-4204-9f31-d9fa9f4964cb; type: table_row -->
| 백엔드 C | AI/프론트 | 브리핑·챗봇용 데이터 조회 API |

<!-- block: d1cbe2f6-c3d1-42af-b9f3-bd40cec517a2; type: table_row -->
| AI/프론트 | 프론트 담당 | 챗봇·브리핑에서 그래프 강조할 대상 ID |

<!-- block: aed8c45b-48c1-4243-84fc-dc499663e814; type: table_row -->
| 클라우드 담당 | 전원 | 개발 환경, 배포 URL, 환경변수 규칙 |


<!-- block: fde71f12-c1be-435b-9d03-7903ebb013ea; type: text -->
팀장 또는 한 명이 맡아야 할 업무 (프로젝트 관리)

<!-- block: 1edb4463-859c-4972-9705-3a6a6be0de00; type: bulleted_list -->
- API 계약서 관리

<!-- block: 578a96dc-bbb7-4a21-86ac-2fd2f79e1a26; type: bulleted_list -->
- 데이터 샘플·Mock 데이터 기준 관리 

<!-- block: 0ac0ffa4-b6aa-41a4-90c8-2325ce89581a; type: bulleted_list -->
- 기능 통합 순서 관리

<!-- block: 35fe75b1-4e6a-4bea-8b1a-a594767c68af; type: bulleted_list -->
- 10월 23일, 30일, 11월 5일 데모 체크포인트 진행

<!-- block: d02449c0-5d85-4c6e-aeec-c21f85dc030f; type: bulleted_list -->
- 최종 시연 데이터 관리

<!-- block: beaa755e-ddc6-4a15-b16d-02fe2399add7; type: text -->


<!-- block: 3f1fef49-d8d5-803f-836e-ec0846ccc143; type: toggle -->
- 상세
<!-- block: bdf83349-f79f-4a79-a7fa-cd51e9c1c16e; type: text -->

<!-- block: a9fdb969-8e42-4583-9246-ce459810c3b8; type: divider -->

<!-- block: 5a2f8a97-5f42-445f-a4cf-7d70a89d50e3; type: header -->
## 전체 구성

<!-- block: d11910d3-c154-4460-bacf-9665a700aae5; type: table -->
<!-- block: c0ce0d2e-2a76-4ea9-a049-c9ebde98d988; type: table_row -->
| 담당 | 핵심 책임 |

<!-- block: 3acd6a7f-8421-4bbe-b6fe-32c55f8177ff; type: table_row -->
| BE A | 회원·관심 종목·가상 보유 관리와 기업 상세 조회 API |

<!-- block: 751f9ee0-0532-4a5f-a956-76131e80f0e9; type: table_row -->
| BE B | GraphDB 저장 구조와 관계 그래프·근거·타임라인 API |

<!-- block: 72bd6740-4f9e-4ccb-8954-a65992f824c6; type: table_row -->
| BE C | 외부 데이터 수집, AI 실행 관리, 브리핑·대화 저장 |

<!-- block: baf19a46-00ec-4ae8-9ae4-5c381458ea14; type: table_row -->
| AI A | 사건 추출, 같은 사건 묶기, 이슈·기업 관계 후보 생성 |

<!-- block: 4be120d3-0ba5-48db-b8b6-f334a4a04da2; type: table_row -->
| AI B | 공통 브리핑과 근거 기반 챗봇 답변 생성 |

<!-- block: 045adbef-14d9-4b80-b689-8cd1bf3082aa; type: table_row -->
| FE A | 회원·관심 종목·브리핑 화면과 챗봇 패널 |

<!-- block: 170dc154-7fa0-45da-98f5-cbc9fe8ea07d; type: table_row -->
| FE B | 관계 그래프·기업 상세·주가 차트·타임라인 화면 |

<!-- block: 8cb484e2-715b-4d6a-b867-77cfd2b02666; type: table_row -->
| Cloud | 개발 환경, DB 실행, 배포, 로그와 운영 확인 |


<!-- block: 43295236-4a4e-4946-a680-b17561600277; type: text -->
  팀장은 이 8명 중 한 명이 겸임하고, API 계약과 통합 순서 및 데모 진행을 관리합니다.

<!-- block: 4a79da86-d4b4-4ca5-852d-d959b3f70e88; type: header -->
## 1. BE A — 회원·포트폴리오·기업 상세 조회

<!-- block: 143941f7-5824-4512-8ca0-62dab5f4b4e1; type: text -->
  담당자: __________

<!-- block: 9aea19ae-c628-4c63-ab8c-8263c84a1d43; type: quote -->
  사용자가 누구인지, 어떤 종목을 선택했는지 관리하고 기업 상세 화면에 필요한 정보를 API로 제공하는 담당자입니다.

<!-- block: 31df6cce-f221-4dc7-b89f-f45f2861bc49; type: sub_header -->
### 직접 구현할 업무

<!-- block: 39dab270-5b2a-4067-beae-c8fa43701665; type: table -->
<!-- block: 15032617-ab9b-4500-adc1-00a24f8c683d; type: table_row -->
| 업무 | 실제로 구현할 내용 |

<!-- block: f5786da1-6e8b-4a39-85cf-ec6ad45f3581; type: table_row -->
| 회원가입·로그인 | 가입 정보 저장, 로그인 검증, 성공·실패 응답 처리 |

<!-- block: 2b2cd7e2-984e-4c97-bf49-5e2b813e780d; type: table_row -->
| 소셜 로그인 | 소셜 인증 결과를 서비스 회원과 연결하고 신규 회원·기존 회원 처리 |

<!-- block: c6980852-3f6b-4569-b744-9498fa55cf2a; type: table_row -->
| JWT 인증 | 토큰 발급·검증, 만료 처리, 로그인 사용자 식별을 위한 공통 코드 |

<!-- block: ee3c4c68-b834-4e32-863a-4a120a23b4c4; type: table_row -->
| 권한 구분 | 비회원·회원·관리자를 구분하고 다른 백엔드 담당자가 사용할 인증·권한 기준 제공 |

<!-- block: 7b8aeb50-bcec-4bd1-85e7-f9ba567bfbda; type: table_row -->
| 온보딩 | 사용자가 어디까지 진행했는지, 완료했는지 저장하고 재접속 시 조회 |

<!-- block: fc679ccc-a6e2-4c01-b6e0-6fb19387e8e6; type: table_row -->
| 관심 종목 | 사용자별 종목 추가·삭제·조회, 중복 등록 처리 |

<!-- block: f0cfc3ec-ce45-4e82-a81f-a3629a018866; type: table_row -->
| 가상계좌·모의 보유 | 사용자와 계좌의 연결 상태, 보유 종목 및 보유 정보를 관리·조회 |

<!-- block: 150844d5-ef18-411d-ae80-c670f391f7ff; type: table_row -->
| 기업 상세 조회 | 기업 기본 정보·시세·재무·뉴스·공시를 화면에 필요한 형식으로 반환 |

<!-- block: 8452b3fd-cc0a-4528-8c8b-b5a2b4f804c4; type: table_row -->
| 주가 차트 데이터 | 기업과 조회 기간을 받아 가격 시계열 데이터를 반환 |


<!-- block: 3d6913fb-271a-4fbd-99c7-a863d5bd3c53; type: sub_sub_header -->
#### 기업 상세에서 어디까지 맡는가?

<!-- block: 78d232f6-04d2-4a84-b1ec-9ccc91cac8d3; type: text -->
  예를 들어 사용자가 기업 상세에 들어오면 BE A는 다음 정보를 내려줍니다.

<!-- block: b3004ab7-dbdb-4af8-98dc-7dd32e70c6a4; type: bulleted_list -->
  - 기업명, 업종 등 기본 정보

<!-- block: 88d68ace-8776-401f-a8f4-eebab9f9ece7; type: bulleted_list -->
  - 현재 시세와 주가 차트용 데이터

<!-- block: 79054c41-7299-41b3-b4e6-4481cceb1978; type: bulleted_list -->
  - 재무 정보

<!-- block: 57bf8345-c630-424e-9a0b-bba9340c5c5a; type: bulleted_list -->
  - 관련 뉴스·공시 목록

<!-- block: 1184c2e5-c560-4346-94a2-2e7d5a826a7e; type: text -->
  주가 차트를 실제로 그리는 작업은 FE B, 기업 관계와 과거 관계를 조회하는 작업은 BE B입니다.

<!-- block: 9dd22a28-c1ca-4735-a854-99444ba0b917; type: text -->
  공용 기업·재무·시장 데이터의 외부 수집은 BE C에 모으는 안으로 정리했습니다. BE A는 수집된 데이터를 기업 상세용 API로 제공합니다. 소셜 인증과 사용자별 가상계좌 연결은 BE A가 맡습니다.

<!-- block: d46d9125-d18b-45fd-90cb-ebb365bd9e5a; type: sub_header -->
### 협업 상대

<!-- block: 432f1a95-28c6-4584-8230-6c400377fdbd; type: table -->
<!-- block: 530f436a-c971-4e06-8616-f6c2fd05344d; type: table_row -->
| 상대 | 주고받을 내용 |

<!-- block: cda19637-cfd2-44f2-9110-425ad7cb321d; type: table_row -->
| BE C | 기업·재무·시세·뉴스·공시 데이터와 기준 시각을 받음 |

<!-- block: eafcce1c-aa2d-4c43-ac02-263212677bd2; type: table_row -->
| BE B | 사용자의 관심·보유 종목을 조회할 방법 제공 |

<!-- block: 986bd48a-0179-4fa4-a362-08087de449b7; type: table_row -->
| FE A | 회원·온보딩·관심 종목·가상계좌 API 제공 |

<!-- block: be435c0e-1093-4b6a-837e-d7291915052f; type: table_row -->
| FE B | 기업 상세·주가 차트 API 제공 |


<!-- block: d4f892e0-f9f0-4ad2-a0cd-4884a8747050; type: text -->
  공통 인증 구조는 BE A가 만들고, 각 API에 필요한 권한 검사는 해당 API 담당자가 적용합니다. 예를 들어 AI 분석 재실행 API의 권한 처리는 BE C가 맡습니다.

<!-- block: 8ab4e8cc-4f1f-4ebe-8b41-ad6ddd039c23; type: sub_header -->
### 완료 기준

<!-- block: 20dd3bc5-5244-4fb0-b604-3e867c98d8ea; type: text -->
  로그인 → 관심 종목 저장 → 재접속 후 선택 유지 → 모의 보유 조회 → 기업 상세에서 기본 정보·차트·재무·뉴스·공시 확인

<!-- block: ddb93277-a0f8-40a5-8f78-252667b90ea2; type: text -->
  여기에 다른 사용자의 보유 정보를 조회할 수 없는지, 데이터가 없는 경우 프론트가 상태를 구분할 수 있는지도 확인합니다.

<!-- block: 2e9aff88-7cbb-45ca-a9ff-476ce1f51880; type: header -->
## 2. BE B — GraphDB·관계 그래프·타임라인 API

<!-- block: 50a20651-25be-4771-9ae8-35618aadfa8b; type: text -->
  담당자: __________

<!-- block: ad98981d-3280-4ec3-b80f-a899a917a1a8; type: quote -->
  기업·사건·이슈의 관계를 저장하고, 필요한 관계와 근거를 조회할 수 있게 만드는 담당자입니다.

<!-- block: 98bf137e-a8bc-4808-86d1-6d974fddc673; type: sub_header -->
### “Neo4j 노드·간선 스키마”는 무엇인가?

<!-- block: f5fbe6de-76af-4b11-8826-addcf266fd0e; type: text -->
  초안에 적어주신 “보여주는 것?”은 FE B의 역할입니다.

<!-- block: 2a5c0810-420a-44ec-82af-9610c5df6549; type: text -->
  BE B가 정하는 것은 다음과 같은 저장 구조와 연결 규칙입니다.

<!-- block: 30bef0dd-cb9e-4904-b5ae-0ca3dd97e4f3; type: table -->
<!-- block: 2933619e-edbc-418d-aea1-bcf9c4ab2d72; type: table_row -->
| BE B가 정할 내용 | 예시 |

<!-- block: 21c1041d-f6e1-4805-a65f-75476785cc9f; type: table_row -->
| 어떤 대상을 관리할지 | 기업, 사건, 이슈, 제품, 근거 문서 |

<!-- block: 47697c4c-1e92-45c8-8cc6-f20e909c8abf; type: table_row -->
| 대상을 어떻게 구별할지 | 기업 ID, 사건 ID, 이슈 ID, 문서 ID |

<!-- block: 78a531bb-91a3-4f48-99ff-b1ac38c961aa; type: table_row -->
| 어떤 관계를 저장할지 | 기업이 제품을 생산함, 이슈가 기업에 영향을 줄 수 있음 |

<!-- block: 816866a0-02e3-4682-a30e-c33ebae9cffe; type: table_row -->
| 관계에 무엇을 기록할지 | 출발·도착 대상, 설명, 영향 해석, 근거 문서, 검증 상태, 시각 |


<!-- block: 45513f36-4f49-47d4-997a-c34e36b62c31; type: text -->
  FE B는 이 데이터를 받아 노드의 모양·색·배치·확장 동작을 구현합니다.

<!-- block: cb9b84c9-f12b-4d21-8fbb-1ae926ef4997; type: sub_header -->
### 직접 구현할 업무

<!-- block: 32376194-51b3-4f53-8b94-4052014762f7; type: table -->
<!-- block: 7b5292c5-e1ca-40b9-bd4b-2e2431e5a286; type: table_row -->
| 업무 | 실제로 구현할 내용 |

<!-- block: fc019380-83ce-4ec3-88d1-9ac1c70314e8; type: table_row -->
| GraphDB 구조 설계 | 노드·관계 종류와 속성, 공통 ID, 저장·조회 기준 정의 |

<!-- block: 60fbf821-6e6e-4adc-90cb-ab3b5ef42100; type: table_row -->
| 분석 결과 적재 | BE C가 전달한 승인된 결과를 GraphDB에 저장 |

<!-- block: 74010c84-80b7-4692-9372-982469929e45; type: table_row -->
| 중복 반영 방지 | 같은 결과를 다시 받아도 노드와 관계가 중복 생성되지 않도록 처리 |

<!-- block: 6c9d2e78-ef62-4df1-acb0-957aa592d90b; type: table_row -->
| 관계 수정·철회 | 수정된 결과나 공개 중단 상태를 반영하고 필요한 이력 보존 |

<!-- block: 1c50458b-44e6-469c-b45f-75d3fa04fe37; type: table_row -->
| 그래프 조회 | 전체·관심 종목·보유 종목 조건에 맞는 노드와 관계 반환 |

<!-- block: 5cb53a04-efaa-4419-b7cf-6b8eaee8c4d3; type: table_row -->
| 주변 관계 탐색 | 선택한 대상에서 최대 2-hop까지 확장하는 조회 API |

<!-- block: fa64a714-8a9c-4a78-8fd2-98b9e67dc5e5; type: table_row -->
| 상세·근거 조회 | 기업·이슈·관계의 설명과 근거 문서 정보 반환 |

<!-- block: 8a039876-4069-400c-a2c3-3ac79413f102; type: table_row -->
| 타임라인 | 기업과 연결된 사건·관계의 시간 정보와 변경 이력 조회 |

<!-- block: 5111563a-5381-4905-b3ca-8256a3913322; type: table_row -->
| 과거 시점 그래프 | 선택한 기준 시점에 해당하는 관계를 조회 |


<!-- block: c546d834-e211-4a6a-8b02-3d7bfaae4b48; type: text -->
  2-hop은 선택한 대상에서 연결선을 최대 두 번 따라가며 탐색하는 범위입니다.

<!-- block: e6f024b5-233a-436a-ab1a-b65047e22818; type: sub_header -->
### 차트·타임라인 담당 구분

<!-- block: e1df603b-d532-40e7-94ba-9e65a8eb453f; type: table -->
<!-- block: 64ceccfa-d553-433a-a14c-81099521a778; type: table_row -->
| 항목 | 서버 담당 | 화면 담당 |

<!-- block: 801af316-dba7-4a98-ba57-fb86715519b9; type: table_row -->
| 주가 차트 | BE A — 가격 시계열 조회 | FE B |

<!-- block: 42717906-6b10-4817-a11d-4cabdecd7151; type: table_row -->
| 사건·관계 타임라인 | BE B — 사건과 관계의 시간 정보 조회 | FE B |

<!-- block: 104bfaeb-e8b8-497b-afcc-391b8c053ed5; type: table_row -->
| 과거 시점 관계 그래프 | BE B — 해당 시점의 관계 조회 | FE B |

<!-- block: 0da61055-bb1f-4257-ac03-e3dddfd39aa7; type: table_row -->
| 기사 발행·수집·수정 시각 | BE C — 원천 시각 정보 저장 | 필요한 API를 통해 전달 |


<!-- block: 3a441e67-8890-4823-ae8f-0e189f03d3fa; type: text -->
  여기서는 “그 날짜에 발생한 사건”과 “그 날짜까지 공개된 관계”를 구분해야 합니다. 어떤 의미의 과거 조회인지 API 계약에 적어야 BE B와 FE B가 같은 기능을 구현할 수 있습니다.

<!-- block: 4be5a343-9562-4bb1-b906-7ca36c62aeba; type: sub_header -->
### 협업과 완료 기준

<!-- block: e86a1d45-b67a-4007-a4dc-6115a1518a49; type: text -->
  BE C에게 승인된 관계와 근거를 받아 저장하고, FE B와 AI B가 사용할 조회 기능을 제공합니다.

<!-- block: 7d54888d-b03f-4b86-9b00-d72c4c35ef43; type: text -->
  기업 선택 → 주변 관계 확장 → 관계 설명 확인 → 근거 문서 확인 → 시점 변경 → 해당 시점의 관계 확인

<!-- block: 3a6817cb-4a3f-4a7f-b5a5-d934981172cb; type: text -->
  승인되지 않은 후보가 사용자 그래프에 나타나지 않는 것까지 확인합니다. 관계 근거를 여는 화면 동작은 기존 화면계획을 따릅니다.

<!-- block: d0481906-15cd-4ca9-8b39-735651cd01e1; type: header -->
## 3. BE C — 데이터 수집·AI 실행 관리·브리핑·대화 저장

<!-- block: 29da857d-701f-4d90-b095-405e35912144; type: text -->
  담당자: __________

<!-- block: 1c51e81a-188b-425e-b9d9-98c5927181eb; type: quote -->
  외부 데이터를 가져와 저장하고, AI에게 일을 요청한 뒤 결과를 저장하고 다음 기능으로 전달하는 담당자입니다.

<!-- block: 3542d4b1-f37c-4e6d-9597-bc371c04bd0e; type: sub_header -->
### 직접 구현할 업무

<!-- block: 1400c259-7060-41c6-96fe-2f2cdc3b0eb3; type: table -->
<!-- block: 4ddb49dd-a773-4366-bb49-2d1e5bfb506e; type: table_row -->
| 업무 | 실제로 구현할 내용 |

<!-- block: fd79e759-c95a-48cd-8199-2dddd80493fc; type: table_row -->
| 외부 데이터 연동 | 뉴스·공시·시장 데이터 API 연결. 이 분담안에서는 공용 기업 기본 정보·재무 수집도 담당 |

<!-- block: 202ccdb6-4da5-4b8d-81e6-52f6069661cd; type: table_row -->
| 수집 실행 | 정해진 주기로 자료를 수집하는 실행 코드와 스케줄러 |

<!-- block: ecfff0df-5d0a-469c-902d-bb2b898b0e2c; type: table_row -->
| 원문 저장 | 문서 ID, 제목, 본문, 출처, 원문 주소, 발행·수집 시각 저장 |

<!-- block: c29c78fd-2f4a-4b71-84f9-d08df043f3c5; type: table_row -->
| 중복·지연·수정 기사 처리 | 이미 저장한 문서인지 확인하고 늦게 발견하거나 수정된 자료를 구분 |

<!-- block: c2229c44-0020-4319-8132-77bb295134e1; type: table_row -->
| AI 분석 요청 | 분석할 문서, 작업 ID, 기준 시각을 AI A에게 전달 |

<!-- block: 38021e6c-ed23-42e8-b904-cce15ad1572e; type: table_row -->
| 작업 상태 관리 | 대기·실행·완료·실패 상태와 실패 원인 저장 |

<!-- block: 8b6234fa-2672-47a4-9ef4-e16007a287c5; type: table_row -->
| 권한·동시 실행 제한 | 요청자의 권한과 이용 한도를 확인하고 중복 실행 제한 |

<!-- block: 4a081cb3-859c-46e2-8ffd-f65d2927158c; type: table_row -->
| 분석 결과 저장 | AI가 반환한 사건·이슈·관계 후보와 근거 및 검수 상태 저장 |

<!-- block: 2ff6f489-f264-4978-8e60-88cbf5482370; type: table_row -->
| GraphDB 반영 연결 | 승인된 결과를 BE B에게 전달하고 반영 성공·실패 기록 |

<!-- block: 17703695-94e5-4d18-b6a4-a83aa3350ecd; type: table_row -->
| AI 조회 도구 | AI가 원문·시장 데이터·기업·관계를 조회할 수 있도록 백엔드 기능 연결 |

<!-- block: 3e2bc9bd-b00b-4a5f-86a0-d5eb77ae63fc; type: table_row -->
| 브리핑 처리 | 회차와 기준 시각 확정, AI B에게 생성 요청, 결과 저장·조회 API |

<!-- block: 5dfb235d-ad49-409d-81de-696fa9aa714e; type: table_row -->
| 챗봇 처리 | 질문 접수, AI B 호출, 세션·질문·답변·근거·작업 상태 저장 |


<!-- block: e438017b-50e8-4b73-b845-19b7335553f9; type: sub_header -->
### “뉴스 수집 스케줄러 = 크롤링”인가?

<!-- block: 487219a0-3ada-4bdc-a9be-aea7c29155bc; type: text -->
  두 작업을 구분해서 적는 게 좋습니다.

<!-- block: 47566c4d-5007-4053-ad6e-07958f7ec98a; type: bulleted_list -->
  - 스케줄러: 언제 수집 작업을 실행할지 담당

<!-- block: f6c4e990-923e-487d-8460-caedf6b7ffe7; type: bulleted_list -->
  - API 연동·크롤러: 자료를 어떻게 가져올지 담당

<!-- block: edfda878-9391-4eeb-8084-6a3006ad78fb; type: text -->
  예를 들어 뉴스 API를 주기적으로 호출하는 서비스라면, API 연동 코드와 스케줄러를 구현합니다. 별도 웹 수집이 필요한 공급원에 대해서만 크롤러를 구현합니다.

<!-- block: fc2fa317-eaed-4221-9a26-dd8fd3a326c0; type: sub_header -->
### AI 담당자와의 경계

<!-- block: 35b15589-361f-4abe-bfaa-2e4d917b11b4; type: table -->
<!-- block: 539bb209-21ee-4d3a-9942-40f0f933d923; type: table_row -->
| 처리할 일 | 담당 |

<!-- block: 4def1a04-e9c6-4d57-938c-b70d3b95abdd; type: table_row -->
| 원문 가져오기·저장하기 | BE C |

<!-- block: 1fa7f52d-d0fc-4f82-b553-c3c0a14a98d8; type: table_row -->
| 기사에서 사건과 관계 판단하기 | AI A |

<!-- block: 0caa6a88-23e5-4372-ad79-e473b6d4911d; type: table_row -->
| 분석 요청·실패·재시도 관리하기 | BE C |

<!-- block: b149fa9c-727c-4573-889f-4bfcf729447b; type: table_row -->
| 브리핑 문장·챗봇 답변 생성하기 | AI B |

<!-- block: c2837884-ece1-488b-957c-5831ce90bd07; type: table_row -->
| 생성 결과 저장·조회하기 | BE C |


<!-- block: 33dc8625-d162-4a4e-b8cb-40a944bec49c; type: text -->
  BE C가 확인하는 것은 필수 필드, 존재하는 기업·문서 ID인지, 근거 연결 형식이 맞는지 같은 서버 검증입니다. 관계 내용의 타당성을 판단하는 검증 기준은 AI A 및 검수 책임자와 맞춥니다.

<!-- block: 7d4651ce-7689-42f0-9273-695632d20770; type: sub_header -->
### 재시도에서 구현할 것

<!-- block: c77b8fe4-024c-4bcd-8af4-d641c38b27fa; type: bulleted_list -->
  - 같은 실패 작업의 재시도는 기존 작업 ID를 유지하고 실행 시도 이력을 추가합니다.

<!-- block: b9353fbf-c9c5-40d5-9516-c9a99342ab9e; type: bulleted_list -->
  - 재시도에도 권한·이용 한도·동시 실행 제한을 적용합니다.

<!-- block: edee8d88-009f-40f8-9a1c-c71d1ded2d43; type: bulleted_list -->
  - 대상이나 기간이 바뀌면 별도 작업으로 처리합니다.

<!-- block: 887ff85f-50ef-4cc9-9e92-0afa30af7846; type: bulleted_list -->
  - GraphDB 반영만 실패했다면 저장된 승인 결과를 다시 전달합니다. 이 경우에는 AI 분석을 처음부터 다시 수행할 필요가 없습니다.

<!-- block: 6c54a853-23e1-4945-8efe-38045fb4a3b5; type: sub_header -->
### 완료 기준

<!-- block: 374f695c-985c-40bb-b807-22809bc02af4; type: text -->
  자료 수집 → 원문 저장 → AI 분석 요청 → 후보 결과 저장 → 검수 상태 기록 → GraphDB 반영 → 브리핑·챗봇에서 조회

<!-- block: c765758e-119e-4df5-a663-e93c1bba58be; type: text -->
  이 흐름에서 어떤 단계가 실패했는지 확인하고, 해당 단계부터 다시 처리할 수 있어야 합니다.

<!-- block: 27c47570-e45c-43c0-8918-c6f175bfcb9d; type: header -->
## 4. AI A — 사건 추출·이슈 정리·관계 후보 생성

<!-- block: 43bef21d-6321-4a9e-b63e-8178ee3b5e58; type: text -->
  담당자: __________

<!-- block: a3459e84-eb8f-45bb-86d2-33323c105a11; type: quote -->
  기사와 공시를 읽고 “무슨 일이 있었고, 어떤 기업과 연결되며, 근거는 무엇인지”를 구조화하는 담당자입니다.

<!-- block: 5830c056-b359-46fb-ac2e-8c7977f9d0b4; type: sub_header -->
### 직접 구현할 업무

<!-- block: e8f72dfb-6452-46a9-a57e-b77e3c09ee5e; type: table -->
<!-- block: 69332822-adb6-45b9-a1ee-d1a6ef938df0; type: table_row -->
| 업무 | 실제로 구현할 내용 |

<!-- block: 807e1195-7001-483d-a0b7-6f07dd0bd222; type: table_row -->
| 분석용 전처리 | 불필요한 문구를 정리하고 근거 문장을 원문과 연결할 수 있도록 준비 |

<!-- block: 5a7838b0-e051-4ea0-a710-de750478456b; type: table_row -->
| 기업·제품·산업 추출 | 등장 대상을 찾고 같은 기업의 다른 이름을 공통 ID로 연결 |

<!-- block: aa6476a2-4787-498d-877b-a74fcad0932b; type: table_row -->
| 사건 추출 | 누가·무엇을·언제 했는지 구분하고 실제 발생·계획·전망을 분리 |

<!-- block: 055b32c2-a558-4125-9c49-d03741b65c9f; type: table_row -->
| 임베딩 생성 | 문서나 사건의 유사성을 비교할 수 있는 표현 생성 |

<!-- block: d0f3d9fa-f63d-4f43-b0a2-f6b94d5c1c1f; type: table_row -->
| 저장·색인·유사 검색 | 임베딩을 저장하고 기존의 비슷한 사건 후보를 검색하는 코드 |

<!-- block: 5ebb07c1-de4a-4a20-9371-629ac43c3846; type: table_row -->
| 동일 사건 묶기 | 같은 발표·계약 등을 다룬 여러 기사를 하나의 사건에 연결 |

<!-- block: 564e41a4-05c2-4011-b427-a48f1bd5e009; type: table_row -->
| 상위 이슈 연결 | 관련 사건들을 공통 주제로 묶어 추적할 이슈 후보 생성 |

<!-- block: 18a2daf6-0b0a-449a-a9a6-f6318320dfce; type: table_row -->
| 기업 영향 관계 | 어떤 사건·이슈가 어느 기업과 어떻게 연결되는지 관계 후보 생성 |

<!-- block: b11ed437-d3fe-4b86-b350-2271b75b8092; type: table_row -->
| 근거·검수 의견 | 관계별 근거 문서와 문장 위치, 신뢰도, 검수 필요 사유 반환 |

<!-- block: e921ab18-176b-44ab-83f4-08aa7309e349; type: table_row -->
| 품질 평가 | 잘못된 기업 연결, 다른 사건의 오병합, 근거 없는 관계 등을 평가 |


<!-- block: 852b1004-7bfd-4c62-af8b-7b45ddd71c9d; type: sub_header -->
### 사건과 이슈는 이렇게 구분하면 됩니다

<!-- block: 7ec68103-fb37-4ed4-9020-410bd6cb085b; type: text -->
  아래는 설명용 가상 예시입니다.

<!-- block: 06e302c0-3837-442a-81fa-790fb81262b0; type: bulleted_list -->
  - 문서: A기업의 공급 계약을 보도한 기사 3건

<!-- block: d51509d5-b8e7-4501-91b9-8f6f50c67aae; type: bulleted_list -->
  - 사건: A기업의 특정 공급 계약 발표 1건

<!-- block: 6fa11195-343e-4221-9f25-f3e05eca21a3; type: bulleted_list -->
  - 다른 사건: B기업의 생산 설비 증설 계획 발표

<!-- block: e9a0e196-5096-42a6-ae3e-b3694479a871; type: bulleted_list -->
  - 이슈: 해당 산업의 공급 확대

<!-- block: 5065bced-607b-4549-9530-06b828dfe3f9; type: text -->
  따라서 같은 사건을 보도한 기사들을 묶는 작업과 서로 다른 사건을 상위 이슈에 연결하는 작업을 각각 구현해야 합니다.

<!-- block: fca507ad-2e50-4154-a245-a0c225ad29b5; type: sub_header -->
### BE C에게 반환할 결과

<!-- block: fde41859-58ff-481d-b6a0-1e1a00b36d16; type: text -->
  단순한 기사 요약만 반환하면 다음 담당자가 관계 그래프를 만들기 어렵습니다. 다음 정보가 필요합니다.

<!-- block: d73e3bff-3cce-49bb-aa51-2c653e7a84af; type: bulleted_list -->
  - 추출한 기업·제품·사건과 시점

<!-- block: 42e8f039-4fdc-4c7f-9d51-e765d2b011c2; type: bulleted_list -->
  - 동일 사건으로 묶은 문서 목록

<!-- block: ba74bf1b-2901-4cc7-b7db-b3621d232852; type: bulleted_list -->
  - 연결할 상위 이슈 후보

<!-- block: b21f1931-2360-4c61-b4cb-7854062d74d5; type: bulleted_list -->
  - 관계의 출발 대상과 도착 대상

<!-- block: 188c48fc-c5c1-4ebf-9527-be0a738d5f9b; type: bulleted_list -->
  - 관계 종류와 영향 설명

<!-- block: cbde2340-a4c6-4e72-8023-6a9583449bba; type: bulleted_list -->
  - 관계별 근거 문서

<!-- block: 13ac4913-253b-4780-8ca0-4389be52088c; type: bulleted_list -->
  - 신뢰도와 검수 필요 사유

<!-- block: 43ab8fe6-a978-4559-8a53-9d3f4f7d20b8; type: text -->
  기존 JSON의 companies: ["005930", "000660"]만으로는 어느 기업에 어떤 관계와 근거가 연결되는지 분명하지 않습니다. 각 관계에 출발·도착 대상과 근거를 붙이는 구조가 필요합니다.

<!-- block: a7f5f762-633f-4895-b806-2b28b999d3cb; type: sub_header -->
### 완료 기준

<!-- block: 1b38fc6e-3cc7-4f60-8a08-c52db56ff880; type: text -->
  기사 입력 → 사건 추출 → 동일 사건 기사 묶기 → 이슈 연결 → 기업 관계 후보 생성 → 관계별 근거 확인

<!-- block: b004565e-dc52-4a5c-a103-f124039bfe6f; type: text -->
  비슷한 주제지만 다른 사건은 구분하고, 근거가 부족한 관계에는 검수 필요 사유를 남겨야 합니다.

<!-- block: b20d1140-b326-4f69-8d8c-5dde179c66df; type: header -->
## 5. AI B — 공통 브리핑·근거 기반 챗봇

<!-- block: d74569c2-27c6-490e-81fc-f3c3f9ce9326; type: text -->
  담당자: __________

<!-- block: c8f266b7-3bec-47ae-9690-367b55d1445f; type: quote -->
  저장된 시장 데이터와 이슈·관계·문서를 읽어 브리핑과 사용자 질문에 대한 답변을 만드는 담당자입니다.

<!-- block: b7fe2a4a-20f5-464a-baed-ab22d8202517; type: sub_header -->
### 브리핑에서 구현할 업무

<!-- block: d35cf311-1a33-49e5-a8dd-c8a8470551ca; type: table -->
<!-- block: 3fe220c1-ddcb-4d85-9fb3-20916a01fd2d; type: table_row -->
| 업무 | 실제로 구현할 내용 |

<!-- block: b08f9c5b-0aa6-4535-9288-44157a03923e; type: table_row -->
| 입력 구성 | 회차·기준 시각·시장 지표·직전 브리핑·이슈·근거를 모델 입력으로 구성 |

<!-- block: 50b90023-b57e-48af-94c9-c66dafa621b0; type: table_row -->
| 핵심 이슈 선정 | 이번 회차에서 보여줄 이슈와 선정 이유 정리 |

<!-- block: cd16236f-34b3-4dea-80b5-635081163689; type: table_row -->
| 본문 생성 | 시장 요약, 핵심 이슈, 관련 기업, 후속 확인 사항 작성 |

<!-- block: f1fb1832-9be9-4e3b-9511-f6aece3792cc; type: table_row -->
| 근거 연결 | 설명을 뒷받침하는 문서·시장 데이터의 출처 연결 |

<!-- block: 239b030d-af8b-4c77-94ae-97ff19507d22; type: table_row -->
| 그래프 연결 | 관련 기업·이슈의 실제 ID를 결과에 포함 |


<!-- block: 6a950c97-3807-4d38-9191-c42c4fa821bd; type: text -->
  BE C가 언제 생성할지 결정하고 요청·저장합니다. AI B는 어떤 자료를 읽고 어떤 내용으로 만들지 구현합니다.

<!-- block: 76fa2852-dd18-4934-b5c8-98a2719ae13c; type: sub_header -->
### 챗봇에서 구현할 업무

<!-- block: ff4fdde3-88c7-4d66-8b81-336f7f4d4cec; type: table -->
<!-- block: 00cb9734-5c11-4467-a9a1-645f8be8bd5c; type: table_row -->
| 업무 | 실제로 구현할 내용 |

<!-- block: ec529363-4ecd-4ab8-95c6-b3e6c107d6d2; type: table_row -->
| 질문 해석 | 현재 기업·선택 대상·기간·질문 의도 파악 |

<!-- block: d1f23541-6763-4b36-89c9-aed4d0e45f67; type: table_row -->
| 되묻기 | 대상이나 조건이 모호할 때 필요한 정보 질문 |

<!-- block: 5860e9af-2061-48c8-b6f9-cdb83c4b464f; type: table_row -->
| 조회 도구 사용 | 기업 정보·관계·원문 중 필요한 도구를 선택해 호출 |

<!-- block: c42dc516-69ba-402d-84c2-968457314327; type: table_row -->
| 답변 생성 | 조회한 근거를 이용해 질문에 맞는 설명 작성 |

<!-- block: c45f3ade-78fc-453b-a7bb-3af9ada2b5b1; type: table_row -->
| 결과 구조화 | 답변, 근거, 한계, 후속 질문, 관련 대상 ID 반환 |

<!-- block: 503c6d9d-1116-4ea0-91b5-796764e3e915; type: table_row -->
| 응답 규칙 | 근거 없는 단정, 투자 권유·가격 예측 등 서비스 제한 규칙 적용 |


<!-- block: c9eaa5e6-397a-42f6-a859-43714a85fa70; type: text -->
  예를 들어 “이 기업이 이 이슈와 어떻게 연결돼?”라는 질문이 오면 다음처럼 나뉩니다.

<!-- block: 72c1113d-7e5a-4525-8ee5-cf7c246b6068; type: bulleted_list -->
  - BE B: 관계 조회 API 구현

<!-- block: 543f0b26-3be7-4126-b957-0c6b3bd0521e; type: bulleted_list -->
  - BE C: AI가 사용할 조회 도구와 실행 흐름 연결

<!-- block: 987ab7ce-9976-4213-b211-4f2a2075151e; type: bulleted_list -->
  - AI B: 해당 도구를 선택해 조회하고 결과를 설명

<!-- block: 70f44523-580b-4370-bd39-802786b8557f; type: sub_header -->
### 완료 기준

<!-- block: 5795122f-7878-4d51-836b-aad91d1d30f1; type: text -->
  브리핑: 생성 요청 → 시장 요약·핵심 이슈 생성 → 실제 기업·이슈·근거 문서로 연결

<!-- block: 124b04fa-ddc0-4e19-ac6d-0214eb88c487; type: text -->
  챗봇: 기업 상세에서 질문 → 필요한 자료 조회 → 근거가 있는 답변 → 그래프·원문 탐색

<!-- block: a11f72c7-2447-4652-ba10-954c9851a2e4; type: text -->
  근거가 없는 질문에서는 자료 부족을 알리거나 조건을 되묻는 동작까지 확인합니다.

<!-- block: f54e37d4-2b74-482e-8f77-49c9484df485; type: text -->
  개인화 브리핑, 좋아요·싫어요, 복잡한 대화 목록은 기존 초안대로 P2로 유지합니다.

<!-- block: 26fd3d6a-a7c1-44bb-bbd0-17d51e84c96e; type: header -->
## 6. FE A — 회원·브리핑 화면·챗봇 패널

<!-- block: c4528860-2115-46e3-87c2-07a6f88f1948; type: text -->
  담당자: __________

<!-- block: ca44af53-cb49-4a8d-b263-b8ee2dd80f3e; type: quote -->
  사용자가 로그인하고 종목을 선택하며, 브리핑을 읽고 AI에게 질문하는 화면을 만드는 담당자입니다.

<!-- block: 7780d697-e791-4c5c-8d1f-b1d114e69243; type: sub_header -->
### 직접 구현할 업무

<!-- block: 3ffcd52c-6ef7-4bea-9490-fc8312672a88; type: table -->
<!-- block: e7a2fd59-01c5-4c7c-ad7f-8f5b903f65d0; type: table_row -->
| 화면 | 실제로 구현할 내용 | 연결 담당 |

<!-- block: c541086a-901a-4192-96ca-afd4bf49b0a9; type: table_row -->
| 회원가입·로그인 | 입력 폼, 입력 오류, 성공·실패, 소셜 로그인 흐름 | BE A |

<!-- block: 2728dd92-f976-4567-9793-2c9770ab4dd7; type: table_row -->
| 온보딩 | 단계별 화면, 선택값 저장, 이전 진행 상태 복원 | BE A |

<!-- block: c306ef17-8d71-4b6a-820e-3d07dcfcd3d5; type: table_row -->
| 관심 종목 | 검색·선택·해제·저장 결과 표시 | BE A |

<!-- block: 96255636-a1f2-49ad-a434-d75bb6f4420c; type: table_row -->
| 가상계좌·보유 정보 | 연결 상태, 보유 목록, 실패·빈 상태 표시 | BE A |

<!-- block: b5071c0a-d9a0-475d-b83a-8ea7d332b4aa; type: table_row -->
| 공통 브리핑 | 출근·퇴근 회차, 시장 요약, 이슈·근거 카드 표시 | BE C |

<!-- block: d0b0ebf3-e5e8-4d87-ac09-e71f9c22c11f; type: table_row -->
| 그래프 이동 | 선택한 기업·이슈 ID를 그래프 화면으로 전달 | FE B |

<!-- block: b2005244-572e-4cdb-a60b-cb885da9185e; type: table_row -->
| 챗봇 패널 | 질문 입력, 답변, 근거 카드, 후속 질문, 새 대화 | BE C |

<!-- block: 8508623f-52df-4218-a745-7a3f62a704aa; type: table_row -->
| AI 처리 상태 | 처리 중 표시, 실패, 재시도, 중복 실행 제한 | BE C |


<!-- block: b6129ea1-5a31-48fa-81a3-48ddda7e950e; type: sub_header -->
### 기업 상세 안의 챗봇은 누가 붙이는가?

<!-- block: fa278e90-1409-4545-962f-66a19e914b56; type: text -->
  다음처럼 나누면 됩니다.

<!-- block: 06b39d86-540d-48cc-8722-c218bad0ebb1; type: table -->
<!-- block: 747c4a6e-63a4-465e-86a4-dfc1ada85777; type: table_row -->
| 담당 | 책임 |

<!-- block: cf9c8c61-0830-453e-b94a-ac1ae23e3598; type: table_row -->
| FE B | 기업 상세 페이지, 현재 기업·기간 상태, 챗봇 패널이 들어갈 위치 |

<!-- block: 61008517-8ca8-4c65-917c-a2a86c76e836; type: table_row -->
| FE A | 삽입 가능한 챗봇 패널, 질문·답변·근거·처리 상태 UI |

<!-- block: 5c9ec040-5999-4e0d-8e3d-cb5266d44d9f; type: table_row -->
| BE C | 대화·작업 상태 저장과 재조회 |

<!-- block: ef130662-de06-4577-86ee-c8135abc0950; type: table_row -->
| AI B | 답변 생성 |


<!-- block: 6b10ce95-1b15-4a90-8c7c-5eb739892900; type: text -->
  FE B가 기업 상세 화면에 FE A의 챗봇 패널을 넣고, 현재 기업·기간·선택 맥락을 전달하는 구조입니다.

<!-- block: 7fdaeaaf-028d-4905-9264-eb447aaa3e60; type: sub_header -->
### 반드시 연결할 상태 동작

<!-- block: 9180d178-3c1e-4140-8af1-2e212c6d46e3; type: bulleted_list -->
  - 패널을 닫았다 열어도 기존 대화와 작업 상태 복원

<!-- block: 3f3f10f2-8970-4277-9f52-0f2d8c86d70e; type: bulleted_list -->
  - 재진입만으로 같은 작업을 다시 실행하지 않도록 처리

<!-- block: 782d2e9b-990f-4d72-a241-92989a5701bc; type: bulleted_list -->
  - 대상·기간 변경 후 실행하면 새 작업으로 요청

<!-- block: 4f2fc3a1-6b51-4b80-bf3d-1696ccfdb3dd; type: bulleted_list -->
  - 이전 대상의 늦은 답변을 현재 대상의 답변으로 표시하지 않도록 처리

<!-- block: 3dd5c12e-3ca7-4fac-abf5-6562a8810865; type: bulleted_list -->
  - 실패 재시도는 기존 작업 ID로 요청

<!-- block: 25a29230-d02f-40d8-8940-8ee2ac3edbde; type: bulleted_list -->
  - 서버가 반환한 권한·이용 한도·동시 실행 제한 상태 표시

<!-- block: 69499e5d-73a0-4591-8783-cc1176ed4c4f; type: sub_header -->
### 완료 기준

<!-- block: 922fadf2-414d-4b2d-bea5-6f024f0d4777; type: text -->
  로그인 → 관심 종목 저장 → 브리핑 조회 → 기업 상세 이동 → 챗봇 질문 → 패널 닫기 → 다시 열어 대화·작업 상태 확인

<!-- block: ca90255e-b9ac-4536-8241-9f5e66e097d7; type: header -->
## 7. FE B — 관계 그래프·기업 상세·차트·타임라인

<!-- block: a91c13bf-9588-44a2-a5d6-85a20c14eb54; type: text -->
  담당자: __________

<!-- block: 0e09d24d-e46f-44c4-9329-f69dbb81ee65; type: quote -->
  기업과 이슈의 관계를 직접 탐색할 수 있게 보여주고, 기업 상세 정보를 화면으로 완성하는 담당자입니다.

<!-- block: 2a36224a-3e97-47e9-b201-05c0ded2786f; type: sub_header -->
### 직접 구현할 업무

<!-- block: 039128c3-d60b-470d-bac8-06f3036c7114; type: table -->
<!-- block: 0251c509-f9f2-4fef-8e56-4c814f670df6; type: table_row -->
| 화면·기능 | 실제로 구현할 내용 | 연결 담당 |

<!-- block: 906ee507-26ba-4d1f-b04c-3658fa7fac1a; type: table_row -->
| 관계 그래프 | 전체·관심·보유 종목 모드의 노드·연결선 표시 | BE B |

<!-- block: 25901d7e-e8d2-46be-b907-590ce73f8758; type: table_row -->
| 노드 표현 | 기업·이슈·제품 등의 모양·문구·선택 상태 구분 | BE B |

<!-- block: ee7cff70-3604-4d66-aaa6-b82a29aa6f0d; type: table_row -->
| 그래프 조작 | 확대·축소·이동·노드 확장·접기 | BE B |

<!-- block: c8a1c364-16cd-47da-ab91-a08986cf6178; type: table_row -->
| 대상 정보 패널 | 선택한 기업·이슈의 설명과 연결 정보 표시 | BE B |

<!-- block: e09ac048-bad0-4858-86d6-494134645dd0; type: table_row -->
| 관계 근거 패널 | 기존 화면 방식에 맞춰 관계 설명과 근거 문서 표시 | BE B |

<!-- block: 68b02d2b-c5f2-4acf-bb70-d8f5d71d8671; type: table_row -->
| 사이드바·필터 | 종목 선택과 필터를 그래프 요청 조건에 반영 | BE A·BE B |

<!-- block: 046cd327-a90c-4ef7-a18b-797340dc9160; type: table_row -->
| 기업 상세 | 기본 정보·재무·뉴스·공시 표시 | BE A |

<!-- block: 9a718a93-115e-4241-a2ad-269d280dec7c; type: table_row -->
| 주가 차트 | 가격 데이터를 받아 차트 표시, 기간 변경·빈 상태 처리 | BE A |

<!-- block: 3106c3cd-af0b-4186-ab6e-ad6559b61f84; type: table_row -->
| 타임라인 | 사건과 관계 변화를 시간 순서로 표시 | BE B |

<!-- block: 3d873b09-b711-4eb0-9048-97cb455e6bc1; type: table_row -->
| 과거 관계 그래프 | 선택한 기준 시점을 서버에 보내 해당 그래프로 갱신 | BE B |

<!-- block: 8b3079c7-79a9-4170-87f1-df428c8d8c29; type: table_row -->
| 챗봇 결합 | FE A의 패널을 기업 상세에 배치하고 맥락 전달 | FE A |


<!-- block: ec49f02f-6fec-4ba6-86a5-7107165cbcaf; type: text -->
  GraphDB에 문서를 저장한다고 해서 모든 문서를 화면의 노드로 그려야 하는 것은 아닙니다. 화면에 노출할 노드 종류와 근거 표시 방식은 기존 화면계획을 따릅니다.

<!-- block: 61872206-432b-4e0b-bd76-33a63d78d330; type: sub_header -->
### 완료 기준

<!-- block: f62a7cba-e4e1-4212-abeb-3abfb0157330; type: text -->
  그래프 진입 → 기업 선택 → 주변 관계 확장 → 근거 패널 확인 → 기업 상세 이동 → 주가 차트·재무 조회 → 과거 시점 선택

<!-- block: ffa7b3f7-bbb5-47d4-8961-58da45fec182; type: text -->
  브리핑에서 전달된 기업·이슈 ID가 올바른 그래프 대상으로 연결되는 것까지 FE A와 함께 확인합니다.

<!-- block: 7b4cbe55-765d-4e06-a731-3c265421e287; type: header -->
## 8. Cloud — 실행 환경·배포·운영

<!-- block: 8790a0fd-36fc-4357-8b58-d186003dde90; type: text -->
  담당자: __________

<!-- block: 0aac0431-3559-45c9-a015-a7fe76bcc7fc; type: quote -->
  각 담당자가 만든 서비스가 배포 서버에서 DB와 연결되어 함께 실행되도록 만드는 담당자입니다.

<!-- block: 721ff08b-0a91-4b99-bcba-27b8066ad306; type: sub_header -->
### 직접 구현할 업무

<!-- block: 3e82e425-16ec-41e1-96a1-ab5453ff5cc2; type: table -->
<!-- block: 5855c104-ee11-48f5-9a53-5a6078e64290; type: table_row -->
| 업무 | 실제로 구현할 내용 |

<!-- block: 41c3f111-b0bf-4ee5-86df-b194d3361aa9; type: table_row -->
| Docker Compose | 서비스·PostgreSQL·Neo4j를 함께 실행할 설정 |

<!-- block: c6755b21-b1e1-4efe-8622-70b9eeaa7828; type: table_row -->
| 실행 기준 정리 | 각 서비스의 빌드 명령, 실행 명령, 포트, 환경변수 취합 |

<!-- block: 8c87a306-3d33-4517-a77f-0cfe34c43084; type: table_row -->
| DB 연결 | 접속 설정, 기본 접근 권한, 데이터 볼륨 구성 |

<!-- block: 32909dd3-b383-4cd6-9f2d-a46815fb3e63; type: table_row -->
| 환경변수·Secret | 개발·배포 환경 분리, API Key와 비밀값 주입 방식 |

<!-- block: 355ee5d0-c1b7-4afe-b1a2-c709e42c5c88; type: table_row -->
| CI/CD | 정해진 브랜치·배포 조건에서 빌드·이미지 생성·배포 |

<!-- block: 195087fc-f853-420f-bab2-7224aa6f4e30; type: table_row -->
| 스케줄러 실행 환경 | BE C가 만든 수집·브리핑 작업이 실행될 환경 구성 |

<!-- block: 14dde37f-1efd-4cd0-80ec-95b02904c4dc; type: table_row -->
| 로그 확인 | 서비스별 로그와 오류 확인 방법 제공 |

<!-- block: 8787b06d-6015-4f5d-8a4b-0331c95d18b2; type: table_row -->
| 배포 후 확인 | FE 접속, BE·AI 호출, DB 연결, 수집·브리핑 실행 확인 |


<!-- block: 62a1fbaf-e8e8-4382-a77e-a30353b30fda; type: sub_header -->
### 다른 개발자와의 경계

<!-- block: c5504703-7499-4a38-b794-2251eb922834; type: table -->
<!-- block: e9da10e9-362f-42ad-8ec6-9b334fae9720; type: table_row -->
| 작업 | 담당 |

<!-- block: eb768c11-70a4-4297-a957-904c6fcb6d88; type: table_row -->
| 서비스가 로컬에서 정상 실행되도록 구현 | 각 서비스 담당자 |

<!-- block: e0e66bfc-a5dc-4776-a7da-9bd5488155cd; type: table_row -->
| 서비스의 헬스체크 응답·기능 로그 구현 | 각 서비스 담당자 |

<!-- block: cc9b9245-6ea5-498a-b5c8-b086fcc0c5af; type: table_row -->
| 공통 배포 설정·서비스 연결·로그 확인 환경 | Cloud |

<!-- block: a45d4832-c30f-4c10-b04e-83de7224f8cb; type: table_row -->
| 수집 주기·수집 로직·중복 방지 | BE C |

<!-- block: fd81a5a5-9763-46ed-97d1-4ea6d1b0aa2b; type: table_row -->
| 수집 작업을 배포 환경에서 실행 | Cloud |


<!-- block: ab069fd6-cf61-4093-a9a0-572faa01175c; type: text -->
  P1에는 배포·기본 접속 설정·비밀키 관리·데이터 유지·로그 확인을 포함합니다. 자동 백업·복구, 고급 모니터링, Kubernetes 등은 기존 초안대로 P2입니다.

<!-- block: d0607e95-1415-45e2-9cd3-6c0ec03b3d6d; type: sub_header -->
### 완료 기준

<!-- block: f19996bc-5702-4af6-88e4-4096783bf88e; type: text -->
  정해진 배포 트리거 → CI → 이미지 빌드 → 서버 배포 → 서비스·DB 연결 → 수집·브리핑 실행 확인

<!-- block: 99154edb-0aba-46e3-91c6-c045b867da8b; type: text -->
  컨테이너를 재시작해도 저장 데이터가 유지되는지 함께 확인합니다.

<!-- block: 049ae05c-e509-443e-a71d-f454cbab8b51; type: header -->
## 9. 반드시 명확히 정할 협업 지점

<!-- block: 0faf142b-4a68-42f3-9b86-ad4f5fc7c897; type: sub_header -->
### ① 분석 결과는 BE C를 거쳐 BE B에 전달

<!-- block: 2499c513-4049-4a8a-9ad9-9dfa61ae7aab; type: text -->
  현재 초안은 AI → BE B와 AI → BE C → BE B가 함께 있어서 전달 경로가 모호합니다. 다음처럼 통일하는 안입니다.

<!-- block: aaa75bef-4a0d-4be8-a247-96ed74f6f60d; type: table -->
<!-- block: d0b49a8d-1cbb-44c2-b331-2b555220c5f9; type: table_row -->
| 순서 | 담당 | 결과 |

<!-- block: 2c6dd1a5-03dc-443f-9e6a-4f5d45745601; type: table_row -->
| 1 | BE C | 분석할 원문과 작업 조건 전달 |

<!-- block: ed2f4b89-2292-45af-ba2f-fc1c37778456; type: table_row -->
| 2 | AI A | 사건·이슈·관계 후보와 근거 생성 |

<!-- block: 9418ded6-6f40-4e6e-93b6-337d3e470be5; type: table_row -->
| 3 | BE C | 후보 저장, 검증 절차 실행·상태 기록 |

<!-- block: 4556c16c-a3ea-48cd-90fa-b9154af0a30b; type: table_row -->
| 4 | BE B | 최종 승인된 결과를 GraphDB에 반영 |

<!-- block: c6804df5-9bfd-4fcb-9a51-9e96983c1a72; type: table_row -->
| 5 | FE B | 그래프와 근거 표시 |


<!-- block: 37669025-75ed-4e45-a542-d3dc14f8ca99; type: text -->
  AI A와 BE B는 JSON 형식을 함께 설계하고, 실제 결과 저장과 전달은 BE C가 관리합니다.

<!-- block: ca031bee-d0ab-4514-a2c3-2aceba0f349d; type: sub_header -->
### ② VERIFIED를 누가 확정하는지 정하기

<!-- block: 6d6c3321-052e-4c44-ab49-7513922b8808; type: text -->
  confidence: 0.82와 VERIFIED는 같은 의미로 사용하면 담당 경계가 흐려집니다.

<!-- block: f29b1156-6c13-47d8-aecc-6c487ea7f0e1; type: table -->
<!-- block: b107d606-3526-4d67-a1aa-98ed9e9b5d9e; type: table_row -->
| 구분 | 책임 |

<!-- block: 50174308-95a8-425b-b9c7-8a698a516cc3; type: table_row -->
| 후보·근거·신뢰도·검수 의견 생성 | AI A |

<!-- block: c32c71d3-6921-4847-844b-db895ee8a0e5; type: table_row -->
| 자동 검증 기준·평가 로직 | AI A |

<!-- block: 9364cb04-7dde-4b77-b0e2-c8b88c33f87b; type: table_row -->
| 형식 검사·검증 실행·최종 상태 기록 | BE C |

<!-- block: b691dd33-cf09-454a-8d2c-a267d473201b; type: table_row -->
| 수동 검수가 필요한 경우 내용 확인 | 지정 검수 담당자 |

<!-- block: f9c60823-0015-4281-b518-a03ffa621069; type: table_row -->
| 승인된 결과의 그래프 반영 | BE B |


<!-- block: 566e6f2c-2cb7-422b-ae03-e56bdeceb7ba; type: text -->
  자동·수동 검수 범위는 기존 정책을 따르고, 미정이라면 P1 시연용 데이터는 팀장이 내용 검수를 겸임하는 안을 권합니다. 모든 운영 데이터를 사람이 전수 검수해야 한다는 새 요구사항으로 확정한 것은 아닙니다.

<!-- block: 31ab58c4-d02a-4fac-a53b-036c0e0ea657; type: text -->
  또한 브리핑·챗봇에서 그래프로 연결할 관계는 승인된 해당 버전의 GraphDB 반영 성공까지 확인한 결과를 사용해야 연결이 끊기지 않습니다.

<!-- block: 1f31b271-f483-4de7-b54e-32e2168d4221; type: sub_header -->
### ③ 팀장이 관리할 것

<!-- block: 8f279807-e12c-493e-9479-cb85de480d53; type: text -->
  팀장이 모든 API를 직접 설계하기보다, 각 담당자가 작성한 계약을 모아 충돌을 조정하도록 나누면 됩니다.

<!-- block: 90063a3b-ae7d-4f92-a2f7-3caeacf77545; type: table -->
<!-- block: 7e5de637-b3c5-4e88-b29b-56c7d6a54251; type: table_row -->
| 관리 항목 | 구체적으로 할 일 |

<!-- block: 1b7c3079-6913-48f9-bb80-42310911e3ee; type: table_row -->
| API 계약 | 요청·응답·오류 형식과 담당자 정리 |

<!-- block: 72b5c291-21e9-412b-927e-95f971c4559d; type: table_row -->
| 공통 데이터 기준 | 기업·문서·이슈 ID와 시각 기준 통일, 기존 Mock 기준 유지 |

<!-- block: 215c0591-90c2-4174-8bfd-6fbef97c685d; type: table_row -->
| 통합 순서 | 누구의 결과가 누구의 입력이 되는지 정하고 연결 일정 관리 |

<!-- block: 38fec6ec-f09c-4760-870d-8186dfb48d14; type: table_row -->
| 검수 책임 | 검증 기준과 책임자, 시연용 승인 범위 확인 |

<!-- block: 6ffa7888-a6b2-46f8-9986-e8e32d64a2c5; type: table_row -->
| 최종 시연 | 브리핑·그래프·기업 상세·챗봇이 같은 대상과 근거로 이어지는지 확인 |


<!-- block: ca94bc97-cc94-4ff6-8f6a-094680769072; type: text -->
  초안의 데모 날짜에는 다음 목표를 배정할 수 있습니다.

<!-- block: c01ab42b-d023-4fa1-8594-e271af63eab1; type: table -->
<!-- block: 3c5510af-fae7-4337-93df-5b18c132f29e; type: table_row -->
| 날짜 | 확인할 목표 |

<!-- block: ce2a90c8-888b-4775-a0b7-b8538e1cd800; type: table_row -->
| 10월 23일 | 로그인·기업 상세·그래프 기본 연결, 수집 저장, AI 입출력 형식 연결 |

<!-- block: d4622451-9665-447e-aa59-09e1875e857d; type: table_row -->
| 10월 30일 | 수집 → 분석 → 검수 상태 → 그래프 반영, 브리핑·챗봇 근거 연결 |

<!-- block: 4603055a-8e64-4925-b9d6-c518e34946b3; type: table_row -->
| 11월 5일 | 배포 환경에서 전체 시연, 과거 시점·실패 재시도까지 확인 |


<!-- block: 92f25f37-44f1-48aa-96c9-0a0d94f23cf5; type: text -->
  각 담당자의 완료 조건에는 “내 기능 구현”과 함께 “다음 담당자가 실제로 사용할 수 있는지 확인”을 넣는 것이 좋습니다. 예를 들어 BE B는 그래프 API 반환까지, FE B는 그 API로 그래프와 근거가 정상 표시되는 것까지 함께 확인하는 방식입니다.


<!-- block: 3f1fef49-d8d5-8026-b806-d0a034be2e69; type: toggle -->
- 상세2
<!-- block: c9fe46fa-b496-46b5-aea3-eece89ed48ac; type: header -->
## 1. 기능별 분담 전체표

<!-- block: be4a7e48-11ee-4985-9a20-9d438441ab51; type: table -->
<!-- block: 1dcf043c-8cc4-44a1-8c30-ee771bc6b2cf; type: table_row -->
| 기능 묶음 | 포함 범위 | 기능 완료 책임자 제안 | 함께 구현할 담당 |

<!-- block: 277c6645-65a0-4711-9ed6-6cb2c0b67e12; type: table_row -->
| ① 회원·포트폴리오 | 가입·로그인·온보딩·관심 종목·가상계좌·모의 보유 | BE A | FE A |

<!-- block: f045dccd-6b1c-4d76-9fbe-49c4399ec40a; type: table_row -->
| ② 기업 상세 | 기업 정보·주가 차트·재무·뉴스·공시 | FE B | BE A |

<!-- block: e1db8ced-482e-4104-bd3c-4dbddf743bb1; type: table_row -->
| ③ 관계 그래프·과거 기록 | 관계 탐색·근거·타임라인·시점별 그래프 | BE B | FE B |

<!-- block: 2a9f985e-a31f-4ed1-ac91-ffe67c1605ff; type: table_row -->
| ④ 공통 출퇴근 브리핑 | 회차 생성·핵심 이슈·시장 요약·근거 연결 | AI B | BE C, FE A |

<!-- block: 9c297427-1f3c-4151-9c32-4dd18915640d; type: table_row -->
| ⑤ 기업 상세 챗봇 | 질문·근거 기반 답변·후속 질문·대화 상태 | FE A | BE C, AI B, FE B |

<!-- block: 7480a9ca-5709-4e2b-9bef-fdcab51fa081; type: table_row -->
| ⑥ 외부 데이터 수집 | 뉴스·공시·기업·재무·시장 데이터 수집·저장 | BE C | 필요한 데이터 계약은 BE A·AI A와 협의 |

<!-- block: 6f91074e-5cb7-4ac0-a78f-99e05b73c37b; type: table_row -->
| ⑦ 사건·이슈·관계 분석 | 사건 추출·동일 사건 묶기·이슈 연결·관계 후보·검증 | AI A | BE C, BE B |

<!-- block: efea23cf-a8ce-4c9c-bc38-56ccdefe7ef5; type: table_row -->
| ⑧ 실행 환경·배포 | Docker·DB·환경변수·CI/CD·로그·헬스체크 | Cloud | 각 서비스 담당자 |


<!-- block: 69dd1660-d147-41a2-9bd9-bc860ed79dbf; type: text -->
  이렇게 하면 회의에서도 **“백엔드 B 얼마나 했어?”**보다 **“관계 그래프 기능에서 저장·조회·화면 중 어디까지 연결됐어?”**라고 진행 상황을 확인할 수 있습니다.

<!-- block: 83344b32-560b-4abc-82f9-b5f36f26634a; type: divider -->

<!-- block: 5515ee07-c941-4571-93dc-74a7bb724e6c; type: header -->
## 2. 기능별로 실제 할 일 나누기

<!-- block: 2069e37e-4e6a-4f9f-a6c2-5da1066b7d0e; type: sub_header -->
### ① 회원·포트폴리오 기능

<!-- block: a7d1082f-42a2-4279-ae82-45c4cc7b4d8c; type: text -->
  목표: 사용자가 로그인하고, 관심 종목과 모의 보유 종목을 관리할 수 있게 한다.

<!-- block: 921014ae-5ad5-4aee-b1bc-0d045c04324d; type: sub_sub_header -->
#### 포함할 기능

<!-- block: f1d7676a-a315-4e7f-8326-b46aecd01834; type: bulleted_list -->
  - 회원가입·로그인·소셜 로그인

<!-- block: 36438872-8c6a-4d93-8906-5c4ad36b7256; type: bulleted_list -->
  - 비회원·회원·관리자 권한 구분

<!-- block: 7729d161-de18-4d39-b4cd-4abc959191f2; type: bulleted_list -->
  - 온보딩 진행 상태

<!-- block: bd162050-b5a8-4351-94f8-8602d1cf91cb; type: bulleted_list -->
  - 관심 종목 검색·선택·해제

<!-- block: 34989b8c-432b-4d22-918b-de6a59fe57a5; type: bulleted_list -->
  - 가상계좌 연결 상태

<!-- block: b48950ea-bb76-4eac-a132-618994ce06f9; type: bulleted_list -->
  - 모의 보유 종목 조회

<!-- block: b2ec8f63-9121-440e-8f22-c1f06f94a8e3; type: sub_sub_header -->
#### 구현 분담

<!-- block: 883f218b-7c4c-47d4-a5c8-506254e59322; type: table -->
<!-- block: ec0c32ed-9b4a-4da6-8cc9-1d75883eaa75; type: table_row -->
| 담당 | 구현할 내용 |

<!-- block: 24f34d96-f6f1-4b70-ab7b-f22b00928d39; type: table_row -->
| FE A | 회원가입·로그인·온보딩 화면, 관심 종목 선택 화면, 계좌 연결·보유 목록 표시 |

<!-- block: 9602f6ce-a02b-43f3-af6c-5ab4a50c70b1; type: table_row -->
| BE A | 회원 저장, 인증·권한 공통 코드, 온보딩 상태 저장, 관심 종목·계좌·보유 데이터 API |


<!-- block: 5512ece4-7bca-4189-96a4-d5510d1f23ee; type: text -->
  완료 흐름

<!-- block: 018dd37c-63a8-471f-be2a-8e98609aa54f; type: text -->
  로그인 → 온보딩 → 관심 종목 선택 → 가상계좌·보유 종목 확인 → 재접속 후 상태 유지

<!-- block: 5f1c76fa-c158-479d-b316-92b5615d0d4e; type: text -->
  이 기능에서 만든 관심·보유 종목 데이터는 관계 그래프 기능에서도 공통으로 사용합니다.

<!-- block: 2b14c6ac-7ced-46dd-b9e0-103a9787c96a; type: divider -->

<!-- block: 1b5b1eee-569b-4aaf-9547-de4eebca1f60; type: sub_header -->
### ② 기업 상세 기능

<!-- block: c411365c-f9af-46f9-8dfb-5eeabc74ff03; type: text -->
  목표: 특정 기업을 선택하면 기업 정보와 주가·재무·뉴스·공시를 한 화면에서 확인할 수 있게 한다.

<!-- block: 4d8ba7e2-64ce-4131-b86b-4d65d6e27fae; type: sub_sub_header -->
#### 포함할 기능

<!-- block: 08bdb9fc-570f-4a77-aae7-78546dd824a3; type: bulleted_list -->
  - 기업 기본 정보

<!-- block: 7a8dd10d-0bd0-4276-a44f-3973a269764f; type: bulleted_list -->
  - 현재 시세

<!-- block: 47a65349-12d5-4c62-8679-d6b974383b51; type: bulleted_list -->
  - 주가 차트와 기간 선택

<!-- block: 8e5357bc-7c69-4593-adf0-4e1f41eeaf02; type: bulleted_list -->
  - 재무 정보

<!-- block: 7b86ae50-78d3-412d-8c60-e39f62adb597; type: bulleted_list -->
  - 관련 뉴스·공시 목록과 원문 이동

<!-- block: 86ee6552-957b-4007-9e88-d018ab64192a; type: bulleted_list -->
  - 정보가 없거나 조회에 실패했을 때의 화면

<!-- block: 155946d0-a7db-4047-8868-b51c8716ddf9; type: sub_sub_header -->
#### 구현 분담

<!-- block: b5d98e05-c5df-495d-bfa6-44aed87e0663; type: table -->
<!-- block: 2319b352-5ac2-49eb-a0c9-c24b209c8cbb; type: table_row -->
| 담당 | 구현할 내용 |

<!-- block: bd112d6b-bbff-4c01-a53b-b15c4fb02531; type: table_row -->
| FE B | 기업 상세 화면, 주가 차트, 재무 표시, 뉴스·공시 목록과 원문 연결 |

<!-- block: 0086bc1d-4da1-48ca-8fe1-17f7d9fac3ed; type: table_row -->
| BE A | 기업 기본 정보·시세·차트·재무·뉴스·공시 조회 API |

<!-- block: 7f5d47e0-b71d-450f-a94f-94af590208ce; type: table_row -->
| BE C | 공통 데이터 수집 기능에서 기업 상세에 필요한 원천 데이터 제공 |


<!-- block: 7a87bfdb-081e-4c7c-a94f-3136bb2eaf4f; type: text -->
  완료 흐름

<!-- block: e6e7af68-fc8a-4d6d-9231-c78d98b25339; type: text -->
  기업 선택 → 기본 정보 확인 → 차트 기간 변경 → 재무 확인 → 뉴스·공시 원문 열기

<!-- block: 31e6f078-8dc8-42b1-82fd-4b43b9d9b0c0; type: text -->
  여기서 주가 차트 데이터는 BE A, 과거 관계 그래프와 사건 타임라인 데이터는 다음 ③ 기능의 BE B가 제공합니다. 화면은 모두 FE B가 연결합니다.

<!-- block: 22395c86-f265-4655-b9bf-f2afcec70e3c; type: divider -->

<!-- block: c81c79a0-1869-4aeb-b268-89dc38c9b4ce; type: sub_header -->
### ③ 관계 그래프·근거·과거 기록 기능

<!-- block: f0772f35-8ded-4378-b271-66a20a37df25; type: text -->
  목표: 기업과 이슈의 연결 관계를 탐색하고, 그 근거와 시간에 따른 변화를 확인할 수 있게 한다.

<!-- block: 7bcc6e09-3cb6-42b1-8262-25f3792d68e5; type: sub_sub_header -->
#### 포함할 기능

<!-- block: 37918bf9-b7d2-414e-aa10-32ec4714f187; type: bulleted_list -->
  - 전체·관심 종목·보유 종목 그래프

<!-- block: 25c2d362-7404-480b-a6cc-6534dfb05c01; type: bulleted_list -->
  - 기업·이슈·제품 등 노드 표시

<!-- block: c026bc83-631d-42c6-af6b-56d58ac5284f; type: bulleted_list -->
  - 노드 확장·접기·확대·축소·이동

<!-- block: fbd91df4-141d-48c9-97b1-2b5b3ff7a8bb; type: bulleted_list -->
  - 기업·이슈 정보 패널

<!-- block: 78d75cd4-f924-45fa-b430-3298b1bab8fa; type: bulleted_list -->
  - 관계 설명과 근거 문서

<!-- block: 1c90fd19-b071-482a-a37a-d7876b246fd0; type: bulleted_list -->
  - 사건·관계 타임라인

<!-- block: adff3dfa-492c-4c7b-acdc-80a8a1ab8f5a; type: bulleted_list -->
  - 선택한 시점의 관계 그래프

<!-- block: 7ffaab6b-909c-4488-94f3-0c3e83afb4e5; type: sub_sub_header -->
#### 구현 분담

<!-- block: 8e4d2cfd-b19a-4246-8575-a59fe1975604; type: table -->
<!-- block: de462da5-332c-4bd8-9a3b-59de51bc7716; type: table_row -->
| 담당 | 구현할 내용 |

<!-- block: 50a2ad4d-43b0-413a-830d-16554823e1c1; type: table_row -->
| BE B | GraphDB 저장 구조, 승인된 관계 적재, 그래프·상세·근거·타임라인·과거 시점 조회 API |

<!-- block: 8261b8ac-d8ff-412c-bb88-ec6fa04da646; type: table_row -->
| FE B | 노드와 연결선 표시, 그래프 조작, 정보·근거 패널, 날짜 선택과 그래프 갱신 |


<!-- block: 85a17b59-b74d-43d2-b933-bd7ebc2f045d; type: text -->
  분석에 필요한 사건·이슈·관계 후보는 ⑦ 분석 기능에서 받아 사용합니다.

<!-- block: b29db7eb-5f8c-4ca4-aa42-64f120b5ec25; type: text -->
  완료 흐름

<!-- block: 5e8814cb-1998-4916-b235-34312b04e995; type: text -->
  기업 선택 → 주변 관계 확장 → 관계 설명·근거 확인 → 타임라인 확인 → 과거 시점 선택 → 해당 관계 표시

<!-- block: ee08aefc-66a1-4db6-a5d9-69cab993dbda; type: text -->
  기능을 구체화할 때 “사건이 발생한 날짜”와 “서비스에 관계가 공개된 날짜” 중 무엇을 기준으로 조회하는지도 BE B와 FE B가 함께 정해야 합니다.

<!-- block: 93248d00-0516-40a9-84b4-bac3165e477a; type: divider -->

<!-- block: 3d3fe00f-103d-4c15-9289-a01738d81773; type: sub_header -->
### ④ 공통 출퇴근 브리핑 기능

<!-- block: 1b306f7d-6e0e-4416-934b-f1159b32c627; type: text -->
  목표: 정해진 회차의 시장 상황과 핵심 이슈를 브리핑으로 제공하고 관련 그래프·근거로 연결한다.

<!-- block: 4516e340-9558-4b8e-9e76-1e2b365a810e; type: sub_sub_header -->
#### 포함할 기능

<!-- block: e7fcee58-848d-42b0-ad7c-2babd927ee07; type: bulleted_list -->
  - 출근·퇴근 회차와 데이터 기준 시각

<!-- block: 5a8c33f1-40db-40b5-a165-2ed31ccba231; type: bulleted_list -->
  - 브리핑 생성 요청

<!-- block: 8b3f53e3-c23d-4fb3-857c-c4b5684885bb; type: bulleted_list -->
  - 핵심 이슈 선정

<!-- block: 91cae40b-b3df-48c8-874f-4695762d74d6; type: bulleted_list -->
  - 시장 요약과 이슈 설명

<!-- block: 12d6a8b2-b77e-402b-aabc-af2958592cbb; type: bulleted_list -->
  - 관련 기업·이슈·근거 연결

<!-- block: a5dcfc8e-ac0e-46d7-a34c-44e53aba0f06; type: bulleted_list -->
  - 생성 결과 저장·조회

<!-- block: 468ad10a-8559-4af9-9ffb-1d470a90fca5; type: bulleted_list -->
  - 처리 중·실패·자료 없음 표시

<!-- block: 6c43d623-a7df-4512-b577-d89ab2ec9d69; type: sub_sub_header -->
#### 구현 분담

<!-- block: 023267d7-b2f4-42c6-9c0f-313c9b6118ad; type: table -->
<!-- block: bd4d315a-5618-438c-bffc-a454dd74ced6; type: table_row -->
| 담당 | 구현할 내용 |

<!-- block: c93683d3-763f-46f8-bcf3-5d25bb301f1c; type: table_row -->
| BE C | 회차·기준 시각 확정, 필요한 자료 조회, 생성 요청, 결과·근거 저장, 조회 API |

<!-- block: ae31f8b8-6f05-4313-9897-2b963787c5d6; type: table_row -->
| AI B | 핵심 이슈 선정, 시장 요약·이슈 설명 생성, 근거와 관련 대상 ID 반환 |

<!-- block: 1c4a7204-7f0b-4190-a060-3ed871d29f0b; type: table_row -->
| FE A | 브리핑 화면, 회차 선택, 핵심 이슈·근거 카드, 그래프 이동 |


<!-- block: 34a8856c-cbd6-45dc-8268-b517df80a822; type: text -->
  완료 흐름

<!-- block: 3f7488d6-185b-4bfb-9b2e-b797c9e1738b; type: text -->
  회차 생성 → AI 브리핑 생성 → 저장 → 화면 표시 → 관련 기업·이슈 그래프 이동 → 근거 확인

<!-- block: c35c01ac-353c-4997-b990-08fe9a74833b; type: text -->
  예를 들어 “브리핑 기능 완료”라고 하려면 AI가 글을 생성하는 것에서 끝나지 않고, 저장된 브리핑을 화면에서 읽고 실제 그래프와 근거를 열 수 있어야 합니다.

<!-- block: e1396906-5c8e-4aa4-b02d-efcba07e0d3f; type: text -->
  개인화 브리핑은 기존 초안대로 P2로 유지합니다.

<!-- block: 01761eb4-9b6e-4217-ad87-7f2c1aad54ed; type: divider -->

<!-- block: 4cadebad-f468-4ab3-a749-f49b876d351a; type: sub_header -->
### ⑤ 기업 상세 챗봇 기능

<!-- block: 9b4b0734-017e-4b90-8c9f-27289fa9481b; type: text -->
  목표: 사용자가 현재 보고 있는 기업·이슈·관계를 바탕으로 질문하고 근거가 있는 답변을 받게 한다.

<!-- block: e28426e7-6b71-4102-971e-6c545c224b8c; type: sub_sub_header -->
#### 포함할 기능

<!-- block: 0c360b1a-fe73-4dc7-b67e-bc6b362697d0; type: bulleted_list -->
  - 현재 기업·대상·기간을 포함한 질문

<!-- block: e90f6660-c0d8-47bc-a372-a94f5c0eedcc; type: bulleted_list -->
  - 질문이 모호할 때 되묻기

<!-- block: 6cc5ce9d-dfc8-4f1c-8f93-00764f41b04b; type: bulleted_list -->
  - 기업·관계·문서 조회

<!-- block: 91d10d8c-4f7f-4a2f-a108-50deab391584; type: bulleted_list -->
  - 답변·근거·한계·후속 질문 표시

<!-- block: 7295a88e-c1f0-45d6-a889-28067d8b5bb9; type: bulleted_list -->
  - 새 대화

<!-- block: 1b6964cc-02ae-47d7-bc9d-6984d1db8f01; type: bulleted_list -->
  - 처리 상태와 재시도

<!-- block: c89a0979-3d8d-4fdf-804c-6d7880f7a465; type: bulleted_list -->
  - 패널을 닫았다 열었을 때 대화·작업 상태 복원

<!-- block: 5b2d913e-c26f-432b-9662-e0a97e422f43; type: sub_sub_header -->
#### 구현 분담

<!-- block: 969212bd-1aac-49b2-8c3c-f51cf54aabed; type: table -->
<!-- block: 5066de3c-0745-4e1e-ac86-8896bcafc70c; type: table_row -->
| 담당 | 구현할 내용 |

<!-- block: 3509d384-0489-4eda-adbd-6bb9e44c1da5; type: table_row -->
| FE A | 챗봇 패널, 질문 입력, 답변·근거·후속 질문, 처리 상태·재시도 UI |

<!-- block: 2b4dab25-ef42-4c61-a5d9-bf3a7673aaa2; type: table_row -->
| BE C | 세션·질문·답변 저장, AI 호출, 작업 상태, 권한·이용 한도·동시 실행 제한 |

<!-- block: 8e5bde38-fe0c-4a9c-9108-d5d713b9558a; type: table_row -->
| AI B | 질문 해석, 조회 도구 선택, 근거 기반 답변·후속 질문 생성 |

<!-- block: 7d243bf9-7a3a-4cd5-b0b1-453c9028371e; type: table_row -->
| FE B | 기업 상세에 챗봇 패널 배치, 현재 기업·기간·선택 대상 전달 |


<!-- block: dc4e7605-6569-4d6e-b695-7a509595330b; type: text -->
  완료 흐름

<!-- block: b7b9900e-4d13-4122-bcfa-3a1022d043d9; type: text -->
  기업 상세 진입 → 질문 → 필요한 정보 조회 → 답변·근거 표시 → 패널 닫기 → 다시 열어 대화·작업 상태 확인

<!-- block: a36a0b5e-6740-4604-8cca-8e11b57c8106; type: text -->
  동일한 실패 작업의 재시도는 기존 작업 ID를 사용하고, 대상·기간이 달라진 실행은 별도 작업으로 처리하는 기존 기준을 연결합니다.

<!-- block: 99aa80be-1533-49aa-a896-fc8f47d62642; type: divider -->

<!-- block: 8e60603b-2774-4903-80b4-b64fb39cdbf5; type: sub_header -->
### ⑥ 외부 데이터 수집 기능

<!-- block: c2041dad-8112-4428-b32c-e857d62719f4; type: text -->
  목표: 기업 상세·분석·브리핑·챗봇이 사용할 원천 데이터를 공통으로 확보한다.

<!-- block: e534587f-7c92-454e-b37e-2e45a31002dd; type: sub_sub_header -->
#### 포함할 기능

<!-- block: 704f6eb7-8dd1-4f95-8556-e94924850221; type: bulleted_list -->
  - 뉴스·공시 수집

<!-- block: b847bb1e-3a17-4fe7-9db8-4033824a247d; type: bulleted_list -->
  - 기업 기본 정보·재무·시장 데이터 수집

<!-- block: 432abf9b-b920-4b45-a6fb-4ceb7efdc3df; type: bulleted_list -->
  - API 연동과 필요한 수집기

<!-- block: 45019f77-1132-4ada-ae24-5bb9217c70b2; type: bulleted_list -->
  - 수집 스케줄러

<!-- block: 4a5621bd-2aba-4db6-b622-f5a3d0dc70d4; type: bulleted_list -->
  - 원문·출처·발행 시각·수집 시각 저장

<!-- block: 33176db5-50eb-48db-a106-36008bd06963; type: bulleted_list -->
  - 중복 문서 처리

<!-- block: f2891bd9-1a5f-4074-8083-399049065cc0; type: bulleted_list -->
  - 지연·수정 기사 처리

<!-- block: 8f2addfe-4369-420f-8705-152b9c7b5104; type: bulleted_list -->
  - 수집 실패 기록·재처리

<!-- block: f52be3dc-beab-4730-9c6a-e277217710fd; type: sub_sub_header -->
#### 구현 분담

<!-- block: 711e6fd1-872f-4032-a7bf-e7d18e5f11e1; type: table -->
<!-- block: 094ce370-f7f6-47fc-b245-d7668f467ee0; type: table_row -->
| 담당 | 구현할 내용 |

<!-- block: 8b8ccd33-3a3f-4e84-b13d-27cd78499016; type: table_row -->
| BE C | 수집기, 스케줄러, 저장, 중복·수정·실패 처리 |

<!-- block: a8c6c774-7db8-457b-9986-eea8e62f8f40; type: table_row -->
| Cloud | 수집 코드가 배포 환경에서 실행되도록 환경 구성 |

<!-- block: 203ee257-44f7-479a-961d-a28a3c1eeefc; type: table_row -->
| BE A·AI A | 기업 상세와 분석에 필요한 데이터 항목을 BE C와 합의 |


<!-- block: 89066848-7a20-43b1-9b89-b9abcc8ef494; type: text -->
  완료 흐름

<!-- block: 08cb9c52-4efa-4ae4-9697-8d09cd0d510e; type: text -->
  외부 자료 수집 → 원문·메타데이터 저장 → 중복·수정 구분 → 다른 기능에서 조회 가능

<!-- block: 5abe2bd0-0d0a-4615-aed0-90fab7af8340; type: text -->
  이 데이터는 ② 기업 상세, ④ 브리핑, ⑤ 챗봇, ⑦ 분석이 함께 사용합니다.

<!-- block: 866172da-5f5a-4e84-ad6b-ea71c8ec9822; type: divider -->

<!-- block: beea2d00-e4a9-4871-9034-9b9b67ca8e7f; type: sub_header -->
### ⑦ 사건·이슈·관계 분석 기능

<!-- block: 81e1f6c7-20c1-443e-9ff3-1bd7f52e2eb1; type: text -->
  목표: 수집한 문서에서 사건을 추출하고, 이슈와 기업 사이의 관계 후보 및 근거를 만든다.

<!-- block: 6f9138fa-56ad-4ce3-aa10-98eb8add59bc; type: sub_sub_header -->
#### 포함할 기능

<!-- block: ddf8bc07-5d79-4e64-9b8b-dd059ed5f89c; type: bulleted_list -->
  - 분석용 전처리

<!-- block: 475ed655-cf91-4ca8-bba0-d120266b5f5e; type: bulleted_list -->
  - 기업·제품·산업 추출

<!-- block: e7e8146a-b921-4f95-bf3a-2d8473b2c1f5; type: bulleted_list -->
  - 사건 추출과 발생·계획·전망 구분

<!-- block: 1e66e36f-9f23-4f2c-9d50-5315e266a01f; type: bulleted_list -->
  - 임베딩 저장·검색

<!-- block: 9a369011-6e58-430b-895c-feb5ecb58e5f; type: bulleted_list -->
  - 동일 사건 기사 묶기

<!-- block: f9d553af-4188-4d0e-b7af-f3b2a31c21be; type: bulleted_list -->
  - 상위 이슈 연결

<!-- block: e1fa696c-750b-4f6d-97cb-67bc3d1b7a05; type: bulleted_list -->
  - 기업 영향 관계 후보 생성

<!-- block: 1b256fed-efa9-4853-bcaf-89ee2b162d0b; type: bulleted_list -->
  - 관계별 근거·신뢰도·검수 의견

<!-- block: f4f35aab-ce2c-41af-8216-d3b0309e88c7; type: bulleted_list -->
  - 분석 품질 평가

<!-- block: e96e8afb-639d-4d4c-aa32-7cdbc7790aec; type: sub_sub_header -->
#### 구현 분담

<!-- block: c16f7476-141c-4c59-88c3-16ae98ff9d58; type: table -->
<!-- block: e14c5825-09ee-4f67-95bd-5812c4f59f20; type: table_row -->
| 담당 | 구현할 내용 |

<!-- block: c4d7827b-d0c8-4436-b504-7ab07cf1fc54; type: table_row -->
| AI A | 사건 추출, 유사 검색, 동일 사건 묶기, 이슈·관계 후보, 근거·평가 로직 |

<!-- block: fd9d7292-ecff-4646-ac71-76907f4ee014; type: table_row -->
| BE C | 분석 대상 전달, 실행·재시도 관리, 결과 저장, 검증 절차와 최종 상태 기록 |

<!-- block: 78aaf6d0-fea0-4ad3-a326-e0b104db6d9b; type: table_row -->
| BE B | 승인된 결과를 GraphDB 저장 구조에 맞게 반영 |


<!-- block: cfc7b527-f59c-43bb-962a-4bf21af63ba2; type: text -->
  완료 흐름

<!-- block: 3cd742f9-1383-41a2-b80f-53f0e7018772; type: text -->
  저장된 문서 → 사건 추출 → 동일 사건 묶기 → 이슈 연결 → 관계 후보·근거 생성 → 검증 상태 확정 → 그래프 반영

<!-- block: 334782b6-d35c-4594-a01d-e2a134fe28af; type: text -->
  VERIFIED의 판정 방식과 공개 기준은 기존 정책을 따릅니다. AI가 만든 후보, 검증 완료 결과, GraphDB 반영 완료 상태를 구분해서 관리합니다.

<!-- block: ba8ceb45-da35-47a1-b8ed-fe38c175cb4a; type: divider -->

<!-- block: 63da8622-8932-4f81-9e79-95cab624b02b; type: sub_header -->
### ⑧ 실행 환경·배포 기능

<!-- block: 1edd883d-98f1-410b-963a-54b4619413ed; type: text -->
  목표: 앞의 기능들이 배포 서버에서 함께 실행되도록 한다.

<!-- block: bc2d7266-ed00-46d8-8018-fd1ccf256efb; type: sub_sub_header -->
#### 포함할 기능

<!-- block: 1095bb95-7f72-401d-86fb-90ed6c28aebe; type: bulleted_list -->
  - Docker Compose

<!-- block: c0b40f53-6a84-4de1-b5c3-5dbc10681c16; type: bulleted_list -->
  - PostgreSQL·Neo4j 실행과 연결

<!-- block: cff4295e-4139-4c5d-baf0-52e2b2ef22ac; type: bulleted_list -->
  - 환경변수·API Key·Secret 관리

<!-- block: 6ca122b8-7a66-4bb1-9fa0-42fdced12eaa; type: bulleted_list -->
  - FE·BE·AI 서비스 빌드·배포

<!-- block: 44a46fe8-edf6-455c-84b5-a3be1bb221b6; type: bulleted_list -->
  - CI/CD

<!-- block: 640e0a4b-752e-4365-b406-0cce97201467; type: bulleted_list -->
  - 수집·브리핑 스케줄러 실행 환경

<!-- block: 41fb9f47-f01e-4ef1-836d-aba5b78ac70a; type: bulleted_list -->
  - 로그·헬스체크

<!-- block: 67954efe-9e0f-4666-82d2-1b57949eaf20; type: bulleted_list -->
  - 재시작 후 데이터 유지

<!-- block: ea8e6cfd-1b07-4830-82b1-425efe28a077; type: sub_sub_header -->
#### 구현 분담

<!-- block: 5a3a14de-42c1-42c7-986c-fb7f52792166; type: table -->
<!-- block: 86d93cc0-96f1-4c5f-9508-a3fa568fb9a6; type: table_row -->
| 담당 | 구현할 내용 |

<!-- block: f6f77ad7-864a-487d-818f-f2be33ffd0b8; type: table_row -->
| Cloud | 공통 실행 환경, DB·서비스 연결, 배포 설정, 로그 확인 환경 |

<!-- block: 2b4114ad-5c77-4266-bd50-efa7c51b2e0c; type: table_row -->
| 각 서비스 담당자 | 자신의 빌드·실행 명령, 필요한 환경변수, 헬스체크와 기능 로그 |


<!-- block: b079d3ec-9be7-432b-8157-b86a8be37b90; type: text -->
  완료 흐름

<!-- block: bb9ebfd9-8ce3-4a6b-a7ff-dcede9436051; type: text -->
  정해진 배포 트리거 → 빌드 → 배포 → 서비스·DB 연결 → 수집·브리핑·화면 동작 확인

<!-- block: 98dea7b7-5f72-4eb4-94be-1ffa2e8a3f45; type: divider -->

<!-- block: ece923ac-eb02-44e0-9eab-e8f0bf9109e0; type: header -->
## 3. 이렇게 나누었을 때 사람별 실제 업무

<!-- block: 11786791-f6e0-4197-ac44-6d29fd3c84f6; type: text -->
  기능별로 묶더라도 한 사람이 여러 기능에 참여하기 때문에, 아래 표를 함께 두면 업무량을 확인하기 좋습니다.

<!-- block: ba90b081-2f11-48e2-bbf5-f3949ff4ef84; type: table -->
<!-- block: 3d9651c8-ed01-40da-aafb-854e26be9754; type: table_row -->
| 사람 | 실제 구현하는 부분 |

<!-- block: 2506568f-fac0-4ec2-9b78-23efe5a1594e; type: table_row -->
| BE A | ① 회원·포트폴리오 서버, ② 기업 상세 조회 API |

<!-- block: 586477c5-3c14-4059-903d-ca44359b346a; type: table_row -->
| BE B | ③ 그래프·근거·과거 기록 API, ⑦ 승인 결과의 GraphDB 반영 |

<!-- block: 53f940aa-d73e-4a0e-b664-5889ad6e9ce1; type: table_row -->
| BE C | ⑥ 수집, ⑦ 분석 실행·저장, ④ 브리핑 서버, ⑤ 챗봇 서버 |

<!-- block: adda7e5f-7509-44bc-a16c-550e5d80759d; type: table_row -->
| AI A | ⑦ 사건·이슈·관계 분석 |

<!-- block: a9037136-992f-4eab-b1dd-812bb871cfef; type: table_row -->
| AI B | ④ 브리핑 생성, ⑤ 챗봇 답변 생성 |

<!-- block: 725c5170-f685-4a80-b787-da8dc261d0da; type: table_row -->
| FE A | ① 회원·포트폴리오 화면, ④ 브리핑 화면, ⑤ 챗봇 패널 |

<!-- block: 47f4f1c0-6fc8-4f94-ae6f-c11f5c9f274c; type: table_row -->
| FE B | ② 기업 상세 화면, ③ 관계 그래프·과거 기록 화면, ⑤ 상세 맥락 연결 |

<!-- block: 8c2c3fad-7b29-45aa-ab8f-3fdb6fd202d4; type: table_row -->
| Cloud | ⑧ 공통 실행 환경과 배포 |


<!-- block: 9153e7d3-3e4b-4c41-9248-3b339ef02cd8; type: text -->
  BE C에는 여러 기능의 연결 업무가 집중됩니다. 따라서 AI A와 AI B가 각각 실행 가능한 분석·생성 모듈과 명확한 입력·출력 형식까지 제공하고, BE C는 공통 실행·상태·저장 코드를 재사용하도록 작업을 나누는 게 좋습니다.

<!-- block: f6182eb6-0938-457a-b945-fb1d00802a01; type: text -->
  실제 작업 목록도 다음처럼 기능 이름 아래에 구현 작업을 배치하면 됩니다.

<!-- block: 28678808-d639-4707-ba6a-ae54ac87dced; type: sub_sub_header -->
#### 예시 — 공통 브리핑 기능

<!-- block: b5e960b7-8d35-4a2a-96cb-17128b7d86e7; type: bulleted_list -->
  - BE C: 회차 생성·데이터 조회·AI 요청·결과 저장·조회 API

<!-- block: cb303f83-1a60-490e-bbae-084d1e4c78bb; type: bulleted_list -->
  - AI B: 핵심 이슈 선정·브리핑 생성·근거 연결

<!-- block: 1b591abe-ab36-4069-bf98-80e081498460; type: bulleted_list -->
  - FE A: 브리핑 화면·처리 상태·그래프 이동

<!-- block: 1fc0e526-65a5-4f35-badb-68a4f99f54f4; type: bulleted_list -->
  - 기능 완료 확인: 저장된 브리핑을 화면에서 열고, 관련 그래프와 근거 문서까지 이동

<!-- block: 5943d0d6-43be-4b8c-b339-7b43cbdd1e35; type: text -->
  이 형식으로 8개 기능을 관리하면 담당자의 작업 진행률과 사용자가 실제로 쓸 수 있는 기능의 완성도를 함께 확인할 수 있습니다.


<!-- block: 3f1fef49-d8d5-80af-9fea-f634de37fa7f; type: text -->

