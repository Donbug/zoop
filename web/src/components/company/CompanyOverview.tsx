import PageSection from '@/components/common/PageSection';
import EmptyState from '@/components/common/EmptyState';

// D-COM-01
// TODO: 시세·지표·모의 보유를 독립적으로 조회하고 실패를 분리한다.
export default function CompanyOverview() {
  return (
    <PageSection title="기업 시세·보유">
      <EmptyState message="준비 중입니다." />
    </PageSection>
  );
}
