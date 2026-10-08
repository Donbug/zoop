# 구조도 원문

`diagrams.json`의 같은 노드·간선으로 그림과 Mermaid를 생성합니다. 실선: 현재. 점선: 별도·승인 후 또는 목표. 구현 표시는 실호출 승인이나 전체 수용 기준 통과가 아닙니다.

## 1. 전체 시스템 구성도

사용자는 React 화면에서 FastAPI BFF가 제공하는 게시 자료와 앱 저장 결과를 읽습니다. 별도 PoC 원장은 관리자 검수 후 게시하며, 별도 AI worker의 작업 결과는 현재 권리와 공개 정책 검증 후 앱에 반영합니다. 합성 재현이며 실모델 실행 승인은 별도입니다.

```mermaid
flowchart LR
  screen["사용자 화면<br/>React · 기존 게시본 예시"]
  bff["화면용 서버<br/>FastAPI · /api"]
  snapshot["게시된 자료<br/>고정 JSON"]
  appdb["앱 저장소<br/>세션 · 검수 · 회차"]
  market["외부 시장 자료<br/>설정 시 연결"]
  raw["뉴스·공시 원문<br/>"]
  poc["뉴스 분석·검증<br/>PoC · 승인 후"]
  ledger["분석 원장·진단<br/>PostgreSQL / Neo4j"]
  publish["관리자 검수·공개<br/>"]
  input["고정 입력<br/>문서 · 기업 · 회차"]
  worker["AI 생산 worker<br/>요약 / 기업별 판정"]
  gate["권리·결과 검증<br/>현재 권리 → 반영"]
  workerdb["자체 SQLite<br/>"]
  screen <-->|"요청·응답"| bff
  snapshot -->|"그래프·근거"| bff
  appdb -->|"세션·저장 결과"| bff
  market -.->|"시장 값"| bff
  raw -.->|""| poc
  poc -.->|""| ledger
  ledger -->|"관리자 조회"| publish
  publish -->|"새 게시 버전"| snapshot
  input -->|""| worker
  worker -->|"결과·영수증"| gate
  gate -->|"검증 후 반영"| appdb
  input -->|"현재 권리"| gate
  worker -->|""| workerdb
```

## 2. 프론트엔드 구성도

기업·기간·시점 선택은 화면 이동과 URL·공용 상태, TanStack Query의 조회 조건, HTTP 요청으로 전달됩니다. 같은 조건의 캐시 자료가 차트·관계·근거 화면을 채웁니다. 근거 사진은 합성 재현 예시이고 일반 질문은 규칙 기반이며 사용자 GET은 worker를 실행하지 않습니다.

```mermaid
flowchart LR
  selection["기업·기간·시점 선택<br/>React · 실제 화면 일부"]
  routing["화면 이동·접근 확인<br/>"]
  condition["선택 조건 공유<br/>URL · 공용 상태"]
  cache["조회 결과 재사용<br/>TanStack Query"]
  request["서버 요청 통일<br/>fetch · cookie"]
  bff["화면용 서버<br/>FastAPI · /api"]
  chart["차트·사건 변화<br/>기존 게시본 · 인과관계 아님"]
  graph["관계 그래프<br/>Cytoscape · 같은 기업 예시"]
  evidence["근거·저장 문서 분석<br/>합성 재현 예시 · 생성 호출 없음"]
  question["일반 AI 질문<br/>규칙 기반"]
  selection -->|""| routing
  routing -->|""| condition
  condition -->|"조건"| cache
  cache -->|"조회 요청"| request
  request -->|"HTTP"| bff
  bff -->|"응답 자료"| cache
  cache -->|"시세·사건"| chart
  cache -->|""| graph
  cache -->|"저장 자료"| evidence
  condition -->|"근거 선택"| evidence
  graph -->|"사건·시점"| condition
  question -->|"질문"| bff
```

## 3. 백엔드 구성도

현재 FastAPI BFF는 세션·공개 기준을 확인해 고정 게시본과 앱 SQLite를 조회합니다. 관리자 PoC 원장·게시와 브리핑 회차는 별도 명령입니다. JSON CLI로 전달한 worker 작업은 자체 SQLite를 사용하며, 결과·영수증은 현재 권리와 문서 의미 또는 기존 outlook 참조 정책을 검증한 후 앱에 반영됩니다. DB 공유 쓰기는 없습니다.

```mermaid
flowchart LR
  entry["요청 입구<br/>/api"]
  guard["접근·자료 기준 확인<br/>"]
  read["게시 자료 조회<br/>"]
  snapshot["게시 그래프·근거<br/>고정 JSON"]
  appdb["앱 저장소<br/>세션 · 검수 · 회차"]
  admin["관리자 작업·게시<br/>"]
  ledger["관리자 원장·진단<br/>PostgreSQL / Neo4j"]
  round["브리핑 회차<br/>발행 후 고정"]
  transport["별도 작업 전달<br/>JSON CLI"]
  gate["권리·공개 검증<br/>문서: 별도 의미 검증"]
  worker["AI 생산 worker<br/>요약 / 기업별 판정 · outlook"]
  workerdb["worker 저장소<br/>SQLite · 영수증 · 불변 결과"]
  poc["뉴스 분석·검증<br/>PoC · 승인 후"]
  market["외부 시장 자료<br/>설정 시 연결"]
  grant["현재 권리<br/>서버 관리 목록"]
  entry -->|"요청·쿠키"| guard
  guard -->|"공개 범위"| read
  snapshot -->|""| read
  appdb -->|"세션·저장 결과"| guard
  guard -->|"관리자 권한"| admin
  ledger -->|""| admin
  admin -->|"검수 후 새 버전"| snapshot
  guard -->|"회차"| round
  appdb <-->|"회차 저장·조회"| round
  poc -.->|"승인 후 분석"| ledger
  market -.->|""| round
  admin -->|""| transport
  round -->|""| transport
  transport -->|"작업"| worker
  worker -->|"결과·영수증"| transport
  worker <-->|"자체 저장"| workerdb
  transport -->|"결과 확인"| gate
  grant -->|""| gate
  gate -->|"검증 후 반영"| appdb
```
