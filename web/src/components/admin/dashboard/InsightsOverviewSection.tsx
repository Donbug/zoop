import { getInsightsOverview } from '@/apis/admin/insights';
import {
  ErrorBox,
  Loading,
  Metric,
  Section,
} from '@/components/admin/common/AdminUi';
import { count, formatPercent } from '@/components/admin/common/adminStyles';
import {
  MetricBasis,
  MetricValue,
  unavailableLabel,
} from '@/components/admin/stats/insightsFormat';
import { useAsyncData } from '@/hooks/useAsyncData';

// A-ADM-01 이용·선호도(7일) (FS072, getInsightsOverview). 대시보드 조회와 따로 실패·재시도한다.
export default function InsightsOverviewSection() {
  const overview = useAsyncData(getInsightsOverview);
  const data = overview.data;

  return (
    <Section
      title="이용·선호도(7일)"
      link={[
        { to: '/admin/stats', label: '이용 통계' },
        { to: '/admin/feedback', label: '선호도' },
        { to: '/admin/members', label: '회원 관리' },
      ]}
    >
      {overview.status === 'loading' && (
        <Loading>이용 통계를 불러오고 있어요</Loading>
      )}
      {overview.status === 'error' && (
        <ErrorBox
          title="이용 통계를 불러오지 못했어요"
          error={overview.error}
          onRetry={overview.reload}
        />
      )}
      {data && (
        <dl className="grid grid-cols-2 gap-x-6 gap-y-5 py-2 md:grid-cols-3 lg:grid-cols-6">
          {data.metrics.map((metric) => (
            <Metric
              key={metric.key}
              label={metric.label}
              value={<MetricValue metric={metric} />}
              detail={
                metric.kind === 'ratio' ? (
                  <MetricBasis metric={metric} minSample={data.minSample} />
                ) : undefined
              }
            />
          ))}
          <Metric
            label="AI 좋아요 비율"
            value={
              data.feedback.availability === 'unavailable' ? (
                <span className="text-zoop-muted">
                  {unavailableLabel(data.feedback.unavailableReason)}
                </span>
              ) : data.feedback.rate === null ? (
                <span className="text-zoop-muted">표본 부족</span>
              ) : (
                formatPercent(data.feedback.rate)
              )
            }
            detail={
              data.feedback.availability === 'unavailable'
                ? '좋아요·싫어요 집계가 아직 연결되지 않았어요'
                : `좋아요 ${count(data.feedback.up)} · 싫어요 ${count(data.feedback.down)}`
            }
          />
          <Metric
            label="등록 회원"
            value={`${count(data.members.registered)}명`}
            detail={`차단 ${count(data.members.blocked)}명`}
          />
        </dl>
      )}
    </Section>
  );
}
