# 새 회차의 기업별 사업 분석 생산자

이 변경은 #553의 읽기 계약으로 **앞으로 생성하는 회차**를 저장한다. 기존 완성 결과의 반입, 과거 발행본 수정, 배포 활성화는 수행하지 않는다. #553(표시 계약)과 #541(서버 입력·사용량·fenced publication 런타임)이 함께 필요하다. #541 없이 실행하면 모델 호출 전에 import 단계에서 중단한다.

## 실행·저장 흐름

1. 기존 `CommonBriefingScheduler`가 09:20/17:30 KST 슬롯을 중복 없이 큐에 기록한다. `briefing_common_schedule_worker.py`의 private `producerCommand`를 새 `briefing_priority_server.py`로 지정한다.
2. #541의 Java `prepare/check`가 현재 발행 그래프·문서 버전·인용·회차 마감·명시적 모델 전송 범위를 고정한다. 매 전송과 발행 직전에 다시 검사한다. 기존 그래프를 교체하거나 입력 자료를 수집하는 기능은 이 변경에 없다.
3. 기존 선정·S3 분석 검증에 더해 `priority-common/check`, `priority-personal/check`, `priority-summary/check`를 각각 별도 요청으로 실행한다. 성공 경로는 10회이며 기존 S3 보완·다른 작업 소비량을 포함한 회차 16회·USD1, 하루 USD2 상한을 그대로 적용한다. 불확실한 전송은 자동 재전송하지 않는다.
4. 검증된 `common-impact-relative-v1`, `personal-impact-relative-v3`만 #553의 읽기 형식으로 투영한다. 모델·프롬프트·schema·입력·응답 영수증과 결과 digest를 대조한다. 스키마 일치만으로 사실 검증을 대신하지 않는다.
5. 기존 Java publisher가 `briefing_rounds`의 payload와 `public_snapshot.commonPriority/prioritySummary`, complete `briefing_personal_pools`를 원자적으로 저장한다. 이미 발행된 슬롯·이력은 덮어쓰지 않는다.

핵심 선정의 중요도 기준은 2 이상이다. 상대 우선순위 카드만 1 이상 후보를 허용하며 실제 점수를 올리지 않는다. 사건·인용 중복 제거, 이전 사건의 새 근거 검사와 가격 비교 조건은 기존 정책을 공유한다. 빈 후보·검증 실패·입력 부족은 구별한다. 선택한 분석이 실패하면 빈 뉴스 회차로 발행하지 않는다.

게시 시각이 날짜 단위뿐인 자료는 이 표시 계약에 필요한 실제 `publishedAt`이 없으므로 `prepare` 실패 기록 후 보류한다. `availableAt`을 게시 시각으로 만들어 넣지 않는다. 새 문안의 가나/연속 한자 혼입을 거절하며, 저장된 원문 인용·기존 결과는 번역하거나 수정하지 않는다. 현재 요약 입력에는 시장 관측·직전 종합 요약이 없으므로 선정 기업의 사업 관점과 확인 조건만 요약한다. 시장 전체 변곡점이나 전망 적중률을 만들어내지 않는다.

## 개인화 저장과 추가 분석

- pool의 `priorityContract=priority-business-producer-v1`이 있는 새 회차만 새 경로를 쓴다. 기존 pool/발행본의 읽기와 선정은 그대로다.
- 개인화는 실제 회원의 고정된 `choice.companyIds`로 complete pool을 선정하고 공유 공개 분석을 필터링한다. 회원 ID·계좌·보유 수량·전체 선택 목록을 모델에 보내지 않는다. 원래 핵심 목록은 따로 유지한다.
- 공통 생산자가 분석한 후보는 새 호출 없이 재사용한다. 다른 선택 후보는 별도 SHA의 `priorityAnalysisInput`으로 `briefing_selected_generation_jobs`에 저장한다. 기존 S3 캐시를 새 v3 분석으로 재분류하지 않는다.
- selected worker도 S3와 새 personal 생성·독립 검증을 모두 통과해야 `briefing_shared_issue_analyses`에 INSERT한다. 기존 `provider_proof`는 S3 영수증 2개를 유지하고 새 private view의 `priorityRecord/priorityProof/priorityProviderReceipts`에 별도 증거를 보존한다. 공개 presentation은 이 원장을 복사하지 않는다.
- `PersonalBriefingPreferences`의 기존 정식/시연 발행 절차가 결과를 `briefing_personal_deliveries.result_snapshot`에 한 번 저장한다. 회차·후보 풀·설정 리비전·선정 버전을 유지하고 완료 후 과거 결과를 다시 조립해 덮어쓰지 않는다.

selected 서버 모드는 private authorization에 `scope=priority-selected-server-v1`, 정확한 DSN의 SHA-256과 공통 생산자와 같은 `serverBudgetWork`를 명시해야 한다. config에는 `priorityContract`, `serverLedgerCommand`가 필요하다. 이 경우 #541의 round/day budget과 `briefing_attempts`/`ai_executions` 원장을 함께 쓴다. 이 정보 없는 종전 worker는 localhost replay DB 제한을 유지한다. 실제 비밀·DSN·권한 파일은 저장소에 넣지 않는다. 새 migration은 selected 호출 단계 제약에 2개 값을 추가하며 기존 값을 바꾸지 않는다.

## 운영 설정 예시 — 비활성 상태

공통 큐 worker의 `producerCommand` 예시(운영 경로는 담당자가 고정):

```json
{
  "enabled": false,
  "producerCommand": [
    "python3", "/srv/zoop/scripts/briefing_priority_server.py",
    "--config", "/private/briefing/priority-producer.json",
    "--round-id", "{roundId}", "--date", "{date}", "--edition", "{edition}",
    "--cutoff", "{cutoff}", "--window-from", "{windowFrom}"
  ]
}
```

생산자 config는 기존 #541의 `work/keyFile/serverCommand/ledgerCommand/authorizationRef`와 `enabled`, `priorityContract`를 갖는다. 같은 큐를 소비하는 종전 runtime과 새 큐 worker를 동시에 켜지 않는다. Secret 등록·스케줄러 enable·서버 실행·병합은 별도 검토 후 수행한다.

## 검증

합성 응답 테스트는 실제 모델을 부르지 않는다.

```sh
PYTHONPATH=scripts:scripts/tests python3 -m unittest test_briefing_priority_generation test_briefing_selected_generation
```

`tests/fixtures/briefing_priority_server_smoke.py`는 #541의 disposable PostgreSQL 통합 세계에서 실제 Java publisher/사용량 원장과 Python 생산자를 연결하기 위한 driver다. 모델 transport만 합성 응답으로 대체한다. 운영 데이터나 모델 영수증을 fixture로 보관하지 않는다.

엄격한 구조화 응답은 [OpenAI Structured Outputs](https://developers.openai.com/api/docs/guides/structured-outputs?api-mode=responses)를 따른다. 별도 요청 검증과 로컬 인용·회차·영수증 검사를 함께 유지한다.
