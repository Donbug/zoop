import type { StatsMetric } from '@/types/admin/insights';
import { count, formatPercent } from '@/components/admin/common/adminStyles';

// 통계·선호도 화면이 함께 쓰는 지표 표기. 표본이 작으면 비율 대신 건수만 보여 준다.
// 모르는 값(null)은 0이 아니라 '–'로 보여 준다.

const countOrDash = (value: number | null) =>
  value === null ? '–' : count(value);

/** 지표 값: 건수는 단위와 함께, 비율은 분모가 기준 이상일 때만 퍼센트 */
export function MetricValue({ metric }: { metric: StatsMetric }) {
  if (metric.kind === 'count')
    return (
      <span className="font-semibold whitespace-nowrap tabular-nums">
        {countOrDash(metric.count)}
        <span className="ml-1 text-[10px] font-normal text-zoop-muted">
          {metric.unit}
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
export function MetricBasis({
  metric,
  minSample,
}: {
  metric: StatsMetric;
  minSample: number;
}) {
  if (metric.kind === 'count')
    return <span className="text-zoop-faint">–</span>;
  return (
    <span className="whitespace-nowrap tabular-nums">
      {countOrDash(metric.numerator)} / {countOrDash(metric.denominator)}
      {metric.unit}
      {metric.sampleHidden && ` (분모 ${minSample} 미만이라 비율 숨김)`}
    </span>
  );
}
