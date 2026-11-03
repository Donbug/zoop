# AI 영업일 달력 profile

회차 수집·신규 계획에는 운영자가 명시한 `zoop-ai-round-profile-2`의 eligibility 정책을 적용합니다. 앱의 매일 회차·freeze 시각과 공개 활성화 절차는 그대로 유지합니다. 이 설정을 준비한 뒤 실제 writer를 시작하는 것은 별도 운영 승인 절차입니다.

## Profile과 불변 식별자

profile-2의 최상위 키는 profile-1과 같습니다. `selection`은 다음 둘 중 하나이며, 나머지 키를 함께 넣으면 거부합니다.

```json
{"cadenceMinutes":30,"limit":8,"eligibility":{"kind":"elapsed-age-1","maxAgeSeconds":291600}}
```

달력 정책은 `eligibility.kind`를 `through-next-business-day-close-1`로 지정하고, `calendar:{path,sha256}`와 양의 정수 `inventoryMaxAgeSeconds`를 명시합니다. `path`는 실제 달력 JSON의 절대 경로이고 `sha256`은 그 파일의 정확한 UTF-8 바이트 SHA-256입니다. 기존 `fixtureManifest`는 검증용 authored 공급에 사용하며, 실제 관측 공급의 구현·권한은 별도로 준비합니다.

profile-1은 기존 바이트·binding·selection-v2의 경과시간 의미를 유지합니다. profile-2는 정책을 binding에 추가하고 selection-v3에 고정하므로 계획·job 식별자도 분리됩니다. 기존 상태에 다른 profile을 넣으면 시작을 거부합니다. 운영 전환 시에는 기존 요청·영구 claim·HOLD·unknown 이력을 원래 binding으로 보존하고 승인된 전환 절차를 준비해야 합니다. 새 빈 상태로 기존 claim을 우회하면 안 됩니다.

## AI가 소유하는 닫힌 달력 형식

`zoop_ai_pipeline.round_calendar.Calendar`가 유일한 달력 형식을 검증합니다. 다음 키를 모두 명시하며 추가 키는 거부합니다.

| 객체 | 필수 키 |
|---|---|
| 달력 | `schemaVersion:1`, `timezone:"Asia/Seoul"`, `calendarKind:"KR_CIVIL_WEEKDAY_PUBLIC_HOLIDAYS"`, `coverage`, `evidenceCutoff`, `dates`, `sources`, `operationalApproval` |
| coverage | `startDate`, `endDate`, `lookaheadEndDate` |
| dates 각 항목 | `date`, `isBusinessDay`, `holidayNames`, `sourceIds` |
| sources 각 항목 | `id`, `url`, `sha256`, `retrievedAt` |

날짜는 ISO 날짜이며 `startDate <= endDate < lookaheadEndDate`입니다. `dates`는 start부터 lookahead 끝까지 모든 날짜를 순서대로 한 번씩 담습니다. 영업일은 월~금 중 `holidayNames`가 비어 있는 날입니다. 모든 날짜에는 sources의 ID가 필요합니다. `retrievedAt`은 실제 증빙 정밀도에 따라 ISO 날짜 또는 시간대가 있는 시각을 보존합니다. 출처 URL은 HTTPS이고 SHA는 출처 증빙 파일을 고정합니다. 증빙이 원문 전체인지 발췌인지도 운영 검토에서 확인해야 합니다.

`operationalApproval:false`인 검토용 달력도 계산·합성 시험 입력으로 읽을 수 있습니다. 이 플래그는 실행 권한을 부여하지 않으며, 서비스는 명시된 profile과 기존 실행 정책·현재 원천 권한을 따릅니다. 달력 원본은 최대 1,500,000바이트, 날짜는 최대 36,600개이며 native 명령·selection JSON의 기존 2,000,000바이트 한도도 적용됩니다.

## 기한과 조회 상한

원점은 기존 수집 원장의 `checkedWindow.through`입니다. 유한 수집의 `window:null`에는 원점을 만들지 않습니다. 원점은 검토 범위 안의 영업일 정규 슬롯 09:05~17:35여야 합니다. 원점 날짜보다 엄격히 뒤인 다음 영업일 18:05까지, 실제 실행 시각으로 고정한 `asOf`에서 자동 선택할 수 있습니다. 기한 후에는 관측을 보존하고 자동 선택에서 제외합니다. 이미 접수된 작업·claim·freeze 결과의 수명은 이 규칙과 별개입니다.

달력의 `startDate..endDate`는 원점·새 실행을 판단할 수 있는 유한 범위입니다. lookahead는 마지막 원점의 다음 영업일을 찾는 증명에 사용합니다. 실행 시각이 endDate를 넘으면 검토한 새 달력이 필요합니다. 누락 날짜·범위 밖 원점·다음 영업일 부재·SHA 불일치는 거부하며 평일 추정으로 이어 가지 않습니다.

조회 상한은 각 영업일의 09:05 원점부터 다음 영업일 18:05까지의 최대 실제 경과 초로 계산합니다. 같은 날짜의 나머지 17개 원점은 더 늦으므로 이 값이 18개 정규 슬롯 모두를 덮습니다. `inventoryMaxAgeSeconds`가 이 계산값보다 작으면 `calendar_inventory_bound_insufficient`로 거부합니다. 고정된 11일 가정은 사용하지 않습니다.

서비스 preflight의 native `round-calendar`, inventory-v2, planner·verify-plan이 같은 달력과 상한을 검증합니다. inventory의 `maxAgeSeconds`는 이 모드에서 조회용 상한이며 eligibility의 값과 같아야 합니다. SQL 조회 뒤 달력 기한으로 거르므로 별도 경과시간 만료 정책을 적용하지 않습니다. 페이지 cursor는 source·scope·asOf·정책·checkpoint revision 해시에 묶입니다. 계획은 달력 원본 JSON 문자열과 SHA를 함께 보관하므로 나중 파일 변경이 과거 계획의 의미를 바꾸지 않습니다.

## HTTP와 운영 경계

유효한 정규 슬롯 또는 실제 실행일이 비영업일이면 기존 응답 `state:no_new_material, code:non_business_day`를 반환합니다. 이 경로는 수집 tick·계획·모델 분석을 시작하지 않습니다. 동일 본문 재전송은 저장된 결과를 먼저 반환하므로 재시작이나 시계 변경으로 재접수하지 않습니다.

이미 접수된 S2·S3 작업은 기존 실행·복구 규칙을 따르므로 휴일에도 실행될 수 있습니다. 비영업일 응답은 새 회차의 수집·분석 접수만 차단하며, 이전 접수에서 발생하는 전체 공급자 트래픽의 중단을 약속하지 않습니다.

계획 없는 handoff는 휴일에도 원장을 다시 읽어 freeze합니다. 전달할 결과가 있으면 ready이고, 실제 `window_empty`일 때만 `no_public_material`입니다. 앱은 ready 결과를 비활성 수입하고 빈 결과를 skipped로 처리합니다. run-v1 응답 형태·ingestionRoundId 구분·원래 관측의 이월 원점은 유지합니다.

현재 authored 공급은 이 정책을 검증하는 입력입니다. 실제 BIS 관측 feed, 새로운 origin/receipt 형식, Java scheduler, 운영 writer와 공개 활성화는 각각 별도 통합·승인 범위입니다.
