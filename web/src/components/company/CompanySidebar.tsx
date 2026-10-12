import PageSection from '@/components/common/PageSection';
import EmptyState from '@/components/common/EmptyState';

// D-COM-03 내부 요소
// TODO: 기업 전환 시 period/asOf/tab은 유지하고 사건·버킷 선택만 초기화한다.
export default function CompanySidebar() {
  return (
    <PageSection title="기업 선택">
      <EmptyState message="준비 중입니다." />
    </PageSection>
  );
}
