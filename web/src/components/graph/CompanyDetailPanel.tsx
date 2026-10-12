import PageSection from '@/components/common/PageSection';
import EmptyState from '@/components/common/EmptyState';

// D-GRP-03
// TODO: 시세·1개월 추이·모의 보유·직접 이슈·기업 상세 이동을 연결한다.
export default function CompanyDetailPanel() {
  return (
    <PageSection title="기업 요약">
      <EmptyState message="준비 중입니다." />
    </PageSection>
  );
}
