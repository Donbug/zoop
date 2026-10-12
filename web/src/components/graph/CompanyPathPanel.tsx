import PageSection from '@/components/common/PageSection';
import EmptyState from '@/components/common/EmptyState';

// D-GRP-07
// TODO: 두 번째 기업 선택·최단 무방향 경로·경로 없음을 구분한다.
export default function CompanyPathPanel() {
  return (
    <PageSection title="두 기업 사이 경로">
      <EmptyState message="준비 중입니다." />
    </PageSection>
  );
}
