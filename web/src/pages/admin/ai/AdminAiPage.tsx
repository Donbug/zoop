import PageShell from '@/components/common/PageShell';
import AiUsageOverview from '@/components/admin/ai/AiUsageOverview';

export default function AdminAiPage() {
  return (
    <PageShell title="AI 운영">
      <AiUsageOverview />
    </PageShell>
  );
}
