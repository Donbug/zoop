const UNAVAILABLE_LABEL: Record<string, string> = {
  not_integrated: '미연동',
  source_unavailable: '조회 불가',
  insufficient_history: '이력 부족',
};
// 서버 단위 코드 중 화면에 그대로 보이면 안 되는 값. 나머지는 이미 한국어 단위다.
const UNIT_LABEL: Record<string, string> = { principal: '명' };
export const unitLabel = (unit: string) => UNIT_LABEL[unit] ?? unit;

/** 지표 원천이 없을 때의 짧은 표기. 0이나 '표본 부족'과 구분한다. */
export const unavailableLabel = (reason: string | null | undefined) =>
  (reason && UNAVAILABLE_LABEL[reason]) ?? '제공 안 됨';
