import PageSection from '@/components/common/PageSection';
import EmptyState from '@/components/common/EmptyState';

// D-GRP-02
// TODO: 사건·직접 관련 기업·근거와 AI 진입 동작을 연결한다.
export default function EventDetailPanel() {
  return (
    <PageSection title="사건 상세">
      <EmptyState message="준비 중입니다." />
    </PageSection>
  );
}
