# Figma ↔ 현재 화면 대응 · v2.1 · 10-08 정합화

기준은 우리 프로토타입과 기존 77쪽 화면계획서다. 새 Figma는 1:1 개선안이며 팀 최종 승인이나 구현 완료 증거가 아니다. 아래 대응은 원본 node를 보존하며 새 화면 ID와 기능을 추가하지 않는다.

## 근거와 결정 상태

- 정적 근거: [coverage.json](../evidence/raw/wireframe_2026-10-08/coverage.json)과 [wireframe delta](../evidence/wireframe-delta-2026-10-08.md) §프레임별 대응. 52개 프레임/그룹, 54개 앱 화면 ID 중 **47 정적 대응 / 2 상태 후보 / 5 독립 미수록**이다. 정적 대응 안에서도 AI 오류·모바일 전/후 등 상태는 일부 미확인이다.
- 동작 근거: `captures/<ID>.json`의 실제 클릭 결과와 `interaction-history.json`이다. Figma의 기능 동작은 전부 미확인이고, 앱의 기존 동작 관측을 Figma 검증으로 전환하지 않는다.
- FS0??는 **FS042 시점 기반 관계 그래프 조회**로 정리됐다. D-COM-04/05/06의 현재 동작 연결이며 기능 신설이 아니다. 새 명세의 요구 41 연결을 사용한다. **구 FS042 재무 정보와 같은 ID를 쓰는 의미 충돌은 미해결**이다.
- 사용자 결정: 이름은 긍정/부정이며 혼재·판단 보류를 삭제하지 않는다. API 공통 규칙은 잠정 채택이다. 판정 LLM 모델/추론 수준은 `.env`에서 관리하고 예산은 추후 결정한다. 설정값 조회와 모델 호출은 하지 않는다.
- FS074~081은 추가 제안·검토 전 / 우선순위 미정이다. WBS의 담당·기간·P1 표기를 승인된 신규 구현 행으로 승격하지 않는다. 남은 충돌은 작업자 가결정 → 시연 → 팀 최종 결정이다. [문서 delta §6](../evidence/doc-delta-2026-10-08.md#6-원본사용자-결정작업자-가결정-구분).

## 프레임별 연결

앱 동작 열은 앱 캡처 metadata의 증거 위치를 가리킨다. 새 Figma node를 직접 조작했다는 뜻이 아니다. 원문과 상태가 어긋난 행은 delta의 주의사항을 유지한다.

| raw node / PNG | 현재 화면 ID · 쪽 | Figma 정적 검토 | Figma 동작 | 앱 동작 증거 | 영향 |
|---|---|---|---|---|---|
| [619-1615](../evidence/raw/wireframe_2026-10-08/frame-619-1615.png) | D-WAT-01 · 21 | 확인됨 · 정적 배치만 확인 | 미확인 | [D-WAT-01](captures/D-WAT-01.json) | 스타일 제안; 신규 기능 증거 없음 |
| [619-1509](../evidence/raw/wireframe_2026-10-08/frame-619-1509.png) | D-ONB-02 · 20 | 확인됨 · 정적 배치만 확인 | 미확인 | [D-ONB-02](captures/D-ONB-02.json) | 스타일 제안; 신규 기능 증거 없음 |
| [619-1429](../evidence/raw/wireframe_2026-10-08/frame-619-1429.png) | D-ONB-01 · 19 | 확인됨 · 정적 배치만 확인 | 미확인 | [D-ONB-01](captures/D-ONB-01.json) | 스타일 제안; 신규 기능 증거 없음 |
| [619-1208](../evidence/raw/wireframe_2026-10-08/frame-619-1208.png) | D-AUT-02 · 17 | 확인됨 · 정적 배치만 확인 | 미확인 | [D-AUT-02](captures/D-AUT-02.json) | 스타일 제안; 신규 기능 증거 없음 |
| [619-1080](../evidence/raw/wireframe_2026-10-08/frame-619-1080.png) | D-AUT-01 · 16 | 확인됨 · 정적 배치만 확인 | 미확인 | [D-AUT-01](captures/D-AUT-01.json) | 실 Google/카카오 제공자는 별도 계약; 현재는 모의 제공자 |
| [619-5682](../evidence/raw/wireframe_2026-10-08/frame-619-5682.png) | D-GRP-T5 · 29 | 확인됨 · 정적 배치만 확인 | 미확인 | [D-GRP-T5](captures/D-GRP-T5.json) | 그래프 시각 문법은 별도 팀 결정; 라벨 가독성만 현재 수정 |
| [619-5095](../evidence/raw/wireframe_2026-10-08/frame-619-5095.png) | D-GRP-T4 · 28 | 확인됨 · 정적 배치만 확인 | 미확인 | [D-GRP-T4](captures/D-GRP-T4.json) | 그래프 시각 문법은 별도 팀 결정; 라벨 가독성만 현재 수정 |
| [619-4508](../evidence/raw/wireframe_2026-10-08/frame-619-4508.png) | D-GRP-T3 · 27 | 확인됨 · 정적 배치만 확인 | 미확인 | [D-GRP-T3](captures/D-GRP-T3.json) | 그래프 시각 문법은 별도 팀 결정; 라벨 가독성만 현재 수정 |
| [619-3920](../evidence/raw/wireframe_2026-10-08/frame-619-3920.png) | D-GRP-T2 · 26 | 확인됨 · 정적 배치만 확인 | 미확인 | [D-GRP-T2](captures/D-GRP-T2.json) | 그래프 시각 문법은 별도 팀 결정; 라벨 가독성만 현재 수정 |
| [619-3337](../evidence/raw/wireframe_2026-10-08/frame-619-3337.png) | D-GRP-T · 25 | 확인됨 · 정적 배치만 확인 | 미확인 | [D-GRP-T](captures/D-GRP-T.json) | 그래프 시각 문법은 별도 팀 결정; 라벨 가독성만 현재 수정 |
| [619-10871](../evidence/raw/wireframe_2026-10-08/frame-619-10871.png) | D-BRF-04 · 48 | 확인됨 · 정적 배치만 확인 | 미확인 | [D-BRF-04](captures/D-BRF-04.json) | 그래프 시각 문법은 별도 팀 결정; 라벨 가독성만 현재 수정 |
| [619-10306](../evidence/raw/wireframe_2026-10-08/frame-619-10306.png) | D-GRP-07b · 36 | 확인됨 · 정적 배치만 확인 | 미확인 | [D-GRP-07b](captures/D-GRP-07b.json) | 그래프 시각 문법은 별도 팀 결정; 라벨 가독성만 현재 수정 |
| [619-9575](../evidence/raw/wireframe_2026-10-08/frame-619-9575.png) | D-GRP-07 · 35 | 확인됨 · 정적 배치만 확인 | 미확인 | [D-GRP-07](captures/D-GRP-07.json) | 그래프 시각 문법은 별도 팀 결정; 라벨 가독성만 현재 수정 |
| [619-8880](../evidence/raw/wireframe_2026-10-08/frame-619-8880.png) | D-GRP-06 · 34 | 확인됨 · 정적 배치만 확인 | 미확인 | [D-GRP-06](captures/D-GRP-06.json) | 그래프 시각 문법은 별도 팀 결정; 라벨 가독성만 현재 수정 |
| [619-8225](../evidence/raw/wireframe_2026-10-08/frame-619-8225.png) | D-GRP-05 · 33 | 확인됨 · 정적 배치만 확인 | 미확인 | [D-GRP-05](captures/D-GRP-05.json) | 그래프 시각 문법은 별도 팀 결정; 라벨 가독성만 현재 수정 |
| [619-7557](../evidence/raw/wireframe_2026-10-08/frame-619-7557.png) | D-GRP-04 · 32 | 확인됨 · 정적 배치만 확인 | 미확인 | [D-GRP-04](captures/D-GRP-04.json) | 그래프 시각 문법은 별도 팀 결정; 라벨 가독성만 현재 수정 |
| [619-6729](../evidence/raw/wireframe_2026-10-08/frame-619-6729.png) | D-GRP-03 · 31 | 확인됨 · 정적 배치만 확인 | 미확인 | [D-GRP-03](captures/D-GRP-03.json) | 그래프 시각 문법은 별도 팀 결정; 라벨 가독성만 현재 수정 |
| [619-6269](../evidence/raw/wireframe_2026-10-08/frame-619-6269.png) | D-GRP-02 · 30 | 확인됨 · 정적 배치만 확인 | 미확인 | [D-GRP-02](captures/D-GRP-02.json) | 그래프 시각 문법은 별도 팀 결정; 라벨 가독성만 현재 수정 |
| [619-2769](../evidence/raw/wireframe_2026-10-08/frame-619-2769.png) | D-GRP-01 · 23 | 확인됨 · 정적 배치만 확인 | 미확인 | [D-GRP-01](captures/D-GRP-01.json) | 그래프 시각 문법은 별도 팀 결정; 라벨 가독성만 현재 수정 |
| [619-2374](../evidence/raw/wireframe_2026-10-08/frame-619-2374.png) | D-GRP-01b · 24 | 확인됨 · 정적 배치만 확인 | 미확인 | [D-GRP-01b](captures/D-GRP-01b.json) | 그래프 시각 문법은 별도 팀 결정; 라벨 가독성만 현재 수정 |
| [619-1819](../evidence/raw/wireframe_2026-10-08/frame-619-1819.png) | D-GRP-01 · 23 | 확인됨 · 정적 배치만 확인 | 미확인 | [D-GRP-01](captures/D-GRP-01.json) | 그래프 시각 문법은 별도 팀 결정; 라벨 가독성만 현재 수정 |
| [692-2](../evidence/raw/wireframe_2026-10-08/frame-692-2.png) | D-STK-01 · 37 | 확인됨 · 정적 배치만 확인 | 미확인 | [D-STK-01](captures/D-STK-01.json) | 기존 종목 메뉴 대응; 새 기능 아님 |
| [663-14180](../evidence/raw/wireframe_2026-10-08/frame-663-14180.png) | D-COM-02 · 40 | 확인됨 · 정적 배치만 확인 | 미확인 | [D-COM-02](captures/D-COM-02.json) | 기존 문서 탭의 실제 정적 상태; 새 기능 아님 |
| [663-13515](../evidence/raw/wireframe_2026-10-08/frame-663-13515.png) | D-COM-01 · 38 | 확인됨 · 정적 배치만 확인 | 미확인 | [D-COM-01](captures/D-COM-01.json) | 기업 정보 추가 필드·공급 계약 확인; Figma 값 하드코딩 금지 |
| [658-8442](../evidence/raw/wireframe_2026-10-08/frame-658-8442.png) | D-COM-05 · 43 / D-COM-06 · 44 | 확인됨 · 부분 확인 / 별도 상태 증거 필요 | 미확인 | [D-COM-05](captures/D-COM-05.json) / [D-COM-06](captures/D-COM-06.json) | 버킷/asOf 후보 또는 옛 문서탭 불일치; 선택 결과 미확인 |
| [658-7834](../evidence/raw/wireframe_2026-10-08/frame-658-7834.png) | D-COM-02 · 40 | 확인됨 · 부분 확인 / 별도 상태 증거 필요 | 미확인 | [D-COM-02](captures/D-COM-02.json) | 버킷/asOf 후보 또는 옛 문서탭 불일치; 선택 결과 미확인 |
| [637-6212](../evidence/raw/wireframe_2026-10-08/frame-637-6212.png) | D-COM-01b · 39 | 확인됨 · 정적 배치만 확인 | 미확인 | [D-COM-01b](captures/D-COM-01b.json) | 스타일 제안; 신규 기능 증거 없음 |
| [637-2222](../evidence/raw/wireframe_2026-10-08/frame-637-2222.png) | D-COM-01 · 38 | 확인됨 · 정적 배치만 확인 | 미확인 | [D-COM-01](captures/D-COM-01.json) | 스타일 제안; 신규 기능 증거 없음 |
| [730-278](../evidence/raw/wireframe_2026-10-08/frame-730-278.png) | D-BRF-04 · 48 | 확인됨 · 정적 배치만 확인 | 미확인 | [D-BRF-04](captures/D-BRF-04.json) | D-BRF-04 중복 후보; 새 ID 추가 없음 |
| [620-1278](../evidence/raw/wireframe_2026-10-08/frame-620-1278.png) | D-BRF-02 · 47 | 확인됨 · 정적 배치만 확인 | 미확인 | [D-BRF-02](captures/D-BRF-02.json) | 스타일 제안; 신규 기능 증거 없음 |
| [620-948](../evidence/raw/wireframe_2026-10-08/frame-620-948.png) | D-BRF-01 · 46 | 확인됨 · 정적 배치만 확인 | 미확인 | [D-BRF-01](captures/D-BRF-01.json) | 스타일 제안; 신규 기능 증거 없음 |
| [620-4859](../evidence/raw/wireframe_2026-10-08/frame-620-4859.png) | D-AI-02b · 52 | 확인됨 · 부분 확인 / 별도 상태 증거 필요 | 미확인 | [D-AI-02b](captures/D-AI-02b.json) | 이름과 정적 복구/오류 UI의 차이 유지 |
| [620-4314](../evidence/raw/wireframe_2026-10-08/frame-620-4314.png) | D-AI-02 · 51 | 확인됨 · 부분 확인 / 별도 상태 증거 필요 | 미확인 | [D-AI-02](captures/D-AI-02.json) | 이름과 정적 복구/오류 UI의 차이 유지 |
| [620-3770](../evidence/raw/wireframe_2026-10-08/frame-620-3770.png) | D-AI-01b · 50 | 확인됨 · 정적 배치만 확인 | 미확인 | [D-AI-01b](captures/D-AI-01b.json) | 스타일 제안; 신규 기능 증거 없음 |
| [620-1593](../evidence/raw/wireframe_2026-10-08/frame-620-1593.png) | D-AI-01 · 49 | 확인됨 · 정적 배치만 확인 | 미확인 | [D-AI-01](captures/D-AI-01.json) | 스타일 제안; 신규 기능 증거 없음 |
| [620-5691](../evidence/raw/wireframe_2026-10-08/frame-620-5691.png) | D-SEN-02 · 60 | 확인됨 · 정적 배치만 확인 | 미확인 | [D-SEN-02](captures/D-SEN-02.json) | 스타일 제안; 신규 기능 증거 없음 |
| [620-5405](../evidence/raw/wireframe_2026-10-08/frame-620-5405.png) | D-SEN-01 · 59 | 확인됨 · 정적 배치만 확인 | 미확인 | [D-SEN-01](captures/D-SEN-01.json) | 스타일 제안; 신규 기능 증거 없음 |
| [620-7653](../evidence/raw/wireframe_2026-10-08/frame-620-7653.png) | M-COM-02 · 58 | 확인됨 · 부분 확인 / 별도 상태 증거 필요 | 미확인 | [M-COM-02](captures/M-COM-02-before.json) | 현재 보이는 1상태만; 전/후·지도 노드 미확인 |
| [620-7454](../evidence/raw/wireframe_2026-10-08/frame-620-7454.png) | M-COM-01 · 57 | 확인됨 · 부분 확인 / 별도 상태 증거 필요 | 미확인 | [M-COM-01](captures/M-COM-01-before.json) | 현재 보이는 1상태만; 전/후·지도 노드 미확인 |
| [620-6944](../evidence/raw/wireframe_2026-10-08/frame-620-6944.png) | M-AI-01 · 56 | 확인됨 · 부분 확인 / 별도 상태 증거 필요 | 미확인 | [M-AI-01](captures/M-AI-01-before.json) | 현재 보이는 1상태만; 전/후·지도 노드 미확인 |
| [620-6670](../evidence/raw/wireframe_2026-10-08/frame-620-6670.png) | M-BRF-01 · 55 | 확인됨 · 부분 확인 / 별도 상태 증거 필요 | 미확인 | [M-BRF-01](captures/M-BRF-01-before.json) | 현재 보이는 1상태만; 전/후·지도 노드 미확인 |
| [620-6428](../evidence/raw/wireframe_2026-10-08/frame-620-6428.png) | M-STK-01 · 54 | 확인됨 · 부분 확인 / 별도 상태 증거 필요 | 미확인 | [M-STK-01](captures/M-STK-01-before.json) | 현재 보이는 1상태만; 전/후·지도 노드 미확인 |
| [620-5928](../evidence/raw/wireframe_2026-10-08/frame-620-5928.png) | M-GRP-01 · 53 | 확인됨 · 부분 확인 / 별도 상태 증거 필요 | 미확인 | [M-GRP-01](captures/M-GRP-01-before.json) | 현재 보이는 1상태만; 전/후·지도 노드 미확인 |
| [620-10924](../evidence/raw/wireframe_2026-10-08/frame-620-10924.png) | A-ADM-05b · 69 | 확인됨 · 정적 배치만 확인 | 미확인 | [A-ADM-05b](captures/A-ADM-05b.json) | 스타일 제안; 신규 기능 증거 없음 |
| [620-10650](../evidence/raw/wireframe_2026-10-08/frame-620-10650.png) | A-ADM-05 · 68 | 확인됨 · 정적 배치만 확인 | 미확인 | [A-ADM-05](captures/A-ADM-05.json) | 스타일 제안; 신규 기능 증거 없음 |
| [620-10181](../evidence/raw/wireframe_2026-10-08/frame-620-10181.png) | A-ADM-04b · 67 | 확인됨 · 정적 배치만 확인 | 미확인 | [A-ADM-04b](captures/A-ADM-04b.json) | 스타일 제안; 신규 기능 증거 없음 |
| [620-9769](../evidence/raw/wireframe_2026-10-08/frame-620-9769.png) | A-ADM-04 · 66 | 확인됨 · 정적 배치만 확인 | 미확인 | [A-ADM-04](captures/A-ADM-04.json) | 스타일 제안; 신규 기능 증거 없음 |
| [620-9307](../evidence/raw/wireframe_2026-10-08/frame-620-9307.png) | A-ADM-03 · 65 | 확인됨 · 정적 배치만 확인 | 미확인 | [A-ADM-03](captures/A-ADM-03.json) | 스타일 제안; 신규 기능 증거 없음 |
| [620-8960](../evidence/raw/wireframe_2026-10-08/frame-620-8960.png) | A-ADM-02b · 64 | 확인됨 · 정적 배치만 확인 | 미확인 | [A-ADM-02b](captures/A-ADM-02b.json) | 스타일 제안; 신규 기능 증거 없음 |
| [620-8616](../evidence/raw/wireframe_2026-10-08/frame-620-8616.png) | A-ADM-02 · 63 | 확인됨 · 정적 배치만 확인 | 미확인 | [A-ADM-02](captures/A-ADM-02.json) | 스타일 제안; 신규 기능 증거 없음 |
| [620-8166](../evidence/raw/wireframe_2026-10-08/frame-620-8166.png) | A-ADM-01 · 62 | 확인됨 · 정적 배치만 확인 | 미확인 | [A-ADM-01](captures/A-ADM-01.json) | 스타일 제안; 신규 기능 증거 없음 |
| [620-8120](../evidence/raw/wireframe_2026-10-08/frame-620-8120.png) | A-ADM-05c · 61 | 확인됨 · 정적 배치만 확인 | 미확인 | [A-ADM-05c](captures/A-ADM-05c.json) | 스타일 제안; 신규 기능 증거 없음 |

## 상태 후보·독립 미수록

| 화면 ID | 지위 | 유지한 한계 |
|---|---|---|
| D-COM-05 / D-COM-06 | 상태 후보 2 | node 658-8442는 선택 버킷/asOf 변경 결과를 입증하지 않는다. 앱의 기존 동작 미구현으로 오해하지 않는다. |
| D-AUT-03 | 독립 미수록 | 모의 provider 동의 화면이 없다. |
| D-WAT-01b | 독립 미수록 | 관심 4개 상태가 없다. |
| D-COM-03 | 독립 미수록 | 기업 전환 전/후 독립 상태가 없다. |
| D-COM-04 | 독립 미수록 | 관계 선택/확장 독립 상태가 없다. |
| D-MY-01 | 독립 미수록 | 내 종목 관리 독립 화면이 없다. |

## 그래프 캡처 범위와 원인

공유 GraphCanvas의 라벨 선별·호버 수정 완료 통지 후 그래프가 실제로 보이는 아래 **28묶음**을 최신본에 반영했다. Figma 전역 도형·예시 사건/수치·파라미터는 복사하지 않았다. 관리자 컨테이너와 관리자 화면은 사용하지 않았다.

- 시장/개인·튜토리얼/선택·근거·경로: D-GRP-01/01b/T/T2/T3/T4/T5/02/03/04/05/06/07/07b (14).
- 기업 상세 1·2단계 관계 표면: D-COM-01/01b/02/03/04/05/06 (7).
- 회차 그래프: D-BRF-04 (1).
- AI 창 배경 그래프: D-AI-01/01b/02/02b (4).
- 모바일 지도·AI 배경: M-GRP-01/M-AI-01 (2). 모바일은 누르기 전/후 2장씩이다.
- 초기 소비자 목록 31묶음으로 실행했으나 PDF 직접 검토에서 M-COM-01/M-COM-02/M-STK-01의 현재 캡처에는 그래프가 보이지 않음을 확인했다. 이 3묶음의 이미지·metadata·manifest는 작업 시작 전 sha256과 정확히 같은 원본으로 복원했다. 최종 재현 명령에서도 제외하며 변경되지 않은 모바일 bytes를 보존한다.

재현 명령과 최종 변경 ID/검토 결과는 [README](README.md), 실제 실행 결과는 `captures/targeted-capture.json` 및 `captures/verification.json`을 참조한다.
