import PageShell from '@/components/common/PageShell';
import FeedbackReview from '@/components/admin/feedback/FeedbackReview';

export default function AdminFeedbackPage() {
  return (
    <PageShell title="선호도">
      <FeedbackReview />
    </PageShell>
  );
}
