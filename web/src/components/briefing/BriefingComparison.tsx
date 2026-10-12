import PageSection from '@/components/common/PageSection';
import EmptyState from '@/components/common/EmptyState';

// D-BRF-02
// TODO: 동일 날짜 출근 회차 대비 신규·이어짐·빠짐을 비교한다.
export default function BriefingComparison() {
  return (
    <PageSection title="아침 대비 변화">
      <EmptyState message="준비 중입니다." />
    </PageSection>
  );
}
