import PageShell from '@/components/common/PageShell';
import DashboardSummary from '@/components/admin/dashboard/DashboardSummary';

export default function AdminDashboardPage() {
  return (
    <PageShell title="운영 대시보드">
      <DashboardSummary />
    </PageShell>
  );
}
