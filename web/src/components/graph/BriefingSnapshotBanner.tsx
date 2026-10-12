import PageSection from '@/components/common/PageSection';
import EmptyState from '@/components/common/EmptyState';

// D-BRF-04
// TODO: round 식별자로 고정 스냅샷을 조회하고 원래 브리핑으로 돌아간다.
export default function BriefingSnapshotBanner() {
  return (
    <PageSection title="회차 기준 지도">
      <EmptyState message="준비 중입니다." />
    </PageSection>
  );
}
