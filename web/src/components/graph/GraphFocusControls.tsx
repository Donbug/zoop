import PageSection from '@/components/common/PageSection';
import EmptyState from '@/components/common/EmptyState';

// D-GRP-07b
// TODO: focus/hops URL을 사용한다. 패널 닫기와 포커스 해제를 구분한다.
export default function GraphFocusControls() {
  return (
    <PageSection title="기업 포커스">
      <EmptyState message="준비 중입니다." />
    </PageSection>
  );
}
