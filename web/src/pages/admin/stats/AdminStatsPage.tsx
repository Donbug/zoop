import PageShell from '@/components/common/PageShell';
import UsageStatistics from '@/components/admin/stats/UsageStatistics';

export default function AdminStatsPage() {
  return (
    <PageShell title="이용 통계">
      <UsageStatistics />
    </PageShell>
  );
}
