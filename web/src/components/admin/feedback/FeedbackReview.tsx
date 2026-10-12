import PageSection from '@/components/common/PageSection';
import EmptyState from '@/components/common/EmptyState';

// A-ADM-02b
// TODO: 유효 평가·사유·마스킹된 대화록을 연결한다.
export default function FeedbackReview() {
  return (
    <PageSection title="선호도·대화록">
      <EmptyState message="준비 중입니다." />
    </PageSection>
  );
}
