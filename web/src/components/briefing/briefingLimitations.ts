import type { BriefingResponse } from '@/types/briefing';

// 조회 장애와 구분하는 081 저장 자료의 확인 한계. 다른 section/code는 실패 안내를 유지한다.
const knownLimitations = new Set([
  'dataWindow:RETROSPECTIVE_BODY',
  'graphVersion:SOURCE_UNAVAILABLE',
  'items:ITEMS_WITHHELD',
  'marketVariables:RETROSPECTIVE_DAILY_SNAPSHOT',
]);

export function hasOnlyKnownLimitations(
  failures: BriefingResponse['metadata']['failures'],
) {
  return (
    failures.length > 0 &&
    failures.every(
      (failure) =>
        !failure.retryable &&
        knownLimitations.has(`${failure.section}:${failure.code}`),
    )
  );
}
