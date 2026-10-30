import type { StatsMetric } from '@/types/admin/insights';
import { count, formatPercent } from '@/components/admin/common/adminStyles';

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

// 통계·선호도 화면이 함께 쓰는 지표 표기. 표본이 작으면 비율 대신 건수만 보여 준다.
// 모르는 값(null)은 0이 아니라 '–'로 보여 준다.

const countOrDash = count;

/** 지표 값: 건수는 단위와 함께, 비율은 분모가 기준 이상일 때만 퍼센트 */
export function MetricValue({ metric }: { metric: StatsMetric }) {
  if (metric.availability === 'unavailable')
    return (
      <span className="font-semibold whitespace-nowrap text-zoop-muted">
        {unavailableLabel(metric.unavailableReason)}
      </span>
    );
  if (metric.kind === 'count')
    return (
      <span className="font-semibold whitespace-nowrap tabular-nums">
        {countOrDash(metric.count)}
        <span className="ml-1 text-[11px] font-normal text-zoop-muted">
          {unitLabel(metric.unit)}
        </span>
      </span>
    );
  if (metric.rate === null)
    return (
      <span className="font-semibold whitespace-nowrap text-zoop-muted">
        표본 부족
      </span>
    );
  return (
    <span className="font-semibold tabular-nums">
      {formatPercent(metric.rate)}
    </span>
  );
}

/** 산식: '15 / 37노출'. 비율을 숨겼으면 기준을 함께 적는다. */
export function MetricBasis({ metric }: { metric: StatsMetric }) {
  if (metric.kind === 'count' || metric.availability === 'unavailable')
    return <span className="text-zoop-faint">–</span>;
  return (
    <span className="whitespace-nowrap tabular-nums">
      {countOrDash(metric.numerator)} / {countOrDash(metric.denominator)}
      {unitLabel(metric.unit)}
      {metric.sampleHidden && ' (표본 부족)'}
    </span>
  );
}
