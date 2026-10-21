# 회차별 반복 사건 억제와 제한 복구

기본 `briefing_round_simulation.py`는 `novelty-recovery-v2` 정책을 사용한다. 기존 불변 실험을 재현하는 `--quality-policy legacy-v1`도 유지한다. 개발용 원발행 시각 시뮬레이션이며 운영 수집 권한·AWS·정시 발행을 승인하지 않는다.

## 반복 선정

1. 현재 회차 `(from,to]`의 확인된 원문만 후보로 만든다.
2. 이미 발행한 이전 `SELECTED/PASS` 이슈의 제목·문장·인용을 서버에서 구성한다. 미래·보류 회차는 이력에 넣지 않는다. 결과 SHA가 다르면 거절한다.
3. 최초 신규성 분류 뒤 별도 모델 호출이 핵심 법인·사건 대상·조치·시점을 재검토한다. 같은 산업·AI·실적이라는 이유로 다른 회사를 같은 사건에 연결하지 않는다. 최초 판단과 검증 응답을 모두 보존하고 최종 검증 결과로 통과·제외를 정한다.
4. 같은 본문 SHA는 재선정하지 않는다. 다른 매체·제목·표현으로 같은 사건을 다룬 경우 AI가 `REPEAT`로 판정해 제외한다.
5. `NEW_EVENT` 또는 구체적 추가 변화와 현재 원문 근거가 있는 `MATERIAL_UPDATE`만 최종 선정기로 전달한다. 변화가 불명확한 `UNCERTAIN`은 보류한다. 같은 회사의 다른 사건을 일괄 제외하지 않는다.
6. 반복 제외 후 나머지 중요도 2 이상 후보 중 최대 3개를 고른다. 수량을 채우기 위해 반복을 되살리지 않는다. 추가 변화의 인용이 선택 인용에 없으면 거절한다.

novelty 이력은 반복 방지를 위한 기억이다. 브리핑/전망 비교용 previous는 바로 직전 회차의 PASS만 사용하며, 직전 회차가 보류면 이전 성공본으로 대체하지 않는다. AI의 의미 비교는 독립적인 경제 사실·새로움 입증이 아니며 원문·시각·권한 가드는 별도로 유지한다.

## 인용·문장

선정 모델은 원문을 다시 작성하지 않고 서버의 `quoteCatalog.quoteId`를 고른다. 서버가 해당 documentId/body SHA/Unicode code-point 구간으로 정확 문자열을 복원한다. 다른 문서 ID·없는 ID·변조 구간은 거절한다.

작성은 원자적 사실/계획/조건을 각각의 claim으로 나눈다. 복합 문장이 필요한 경우 모든 절을 입증하는 인용을 연결한다. 각각/합계/최대·발표/확정·계획 상태를 보존한다. 보완은 같은 고정 인용에서 최대 1회이며 모든 제목/문장을 다시 검증한다. 실패 항목을 숨기고 나머지만 부분 발행하지 않는다.

## HTTP 복구

`briefing_http_recovery.py`는 실패 요청·원응답·receipt·예약의 SHA와 stage/model/usage를 대조한다. 명시된 500/502/503/504만 한 차례 복구 대상으로 인정한다. timeout 등 응답이 없는 pending, 200 불완전/거절, 인증·과금·권한 오류는 자동 재시도하지 않는다. 사용량 불명은 NULL 그대로 보존한다.

선정 요청의 복구는 원래 digest와 사용자 inbox를 새 요청 `recoveryAttempt`에 묶는다. 원래 실패를 성공으로 덮어쓰지 않는다. 출력 상위 `recovery-ledger`의 원 요청별 예약이 다른 replacement digest/출력에 재사용되면 거절한다. 같은 완료 replacement의 재사용은 새 유료 시도가 아니다.

## 특정 보류·반복 사례 재검증

`scripts/briefing_round_remediation.py`는 기본으로 10/3퇴근·10/5출근·10/6출근·10/8출근·10/8퇴근 5개 사례를 별도 private output에서 재검증한다. 원본 source/clock/round binding과 기존 importance 원응답·본문 SHA·전체 모집단을 확인한 뒤 평가 결과를 재사용한다. 최종 선정·작성·검증과 필요한 novelty 비교는 새로 수행하고 모든 실제 호출을 저장한다.

기본은 offline이며 `--execute-authorized-recheck`, 사용자 inbox, private key 파일, 명시적 호출 상한이 있어야 전송한다. 이 출력은 `zoop-briefing-quality-recheck-v1`이며 14회차의 새 발행 bundle이 아니다. 개별 사례에서 참조하는 이력은 원래 simulation 기준이고, 보완 결과를 기존 DB나 불변 발행본에 자동 덮어쓰지 않는다. 전체 새 운영/시뮬레이션 발행은 별도 run/output/DB로 검증한다.

인증값·실제 원문·실응답·DB는 Git에 올리지 않는다. CI는 합성 자료만 사용한다.

## 시험

- `python3 -m unittest discover -s scripts/tests`
- 신규성: `test_briefing_novelty.py`
- 인용ID/전체회차 통합: `test_briefing_quality_v2.py`
- HTTP 원장·복구: `test_briefing_http_recovery.py`

일시 오류 처리의 참고: [OpenAI 공식 오류 코드 안내](https://developers.openai.com/api/docs/guides/error-codes). 일반 재시도 권장과 별개로 이 재생 도구는 사용량 불명 원장의 자동 재전송을 하지 않는다.
