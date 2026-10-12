import PageSection from '@/components/common/PageSection';
import EmptyState from '@/components/common/EmptyState';

// D-BRF-01 / 02
// TODO: 핵심 이슈·선정 이유·근거·회차 지도·피드백을 연결한다.
export default function BriefingIssueList() {
  return (
    <PageSection title="핵심 이슈">
      <EmptyState message="준비 중입니다." />
    </PageSection>
  );
}
