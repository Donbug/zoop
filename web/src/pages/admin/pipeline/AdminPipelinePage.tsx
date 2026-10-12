import PageShell from '@/components/common/PageShell';
import PipelineReview from '@/components/admin/pipeline/PipelineReview';

export default function AdminPipelinePage() {
  return (
    <PageShell title="이슈 관제">
      <PipelineReview />
    </PageShell>
  );
}
