import PageShell from '@/components/common/PageShell';
import BriefingOperations from '@/components/admin/briefings/BriefingOperations';

export default function AdminBriefingsPage() {
  return (
    <PageShell title="브리핑 운영">
      <BriefingOperations />
    </PageShell>
  );
}
