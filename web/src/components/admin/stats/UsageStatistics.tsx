import PageSection from '@/components/common/PageSection';
import EmptyState from '@/components/common/EmptyState';

// A-ADM-02
// TODO: 기간별 통계와 표본 부족을 구분한다.
export default function UsageStatistics() {
  return (
    <PageSection title="이용·AI 품질 통계">
      <EmptyState message="준비 중입니다." />
    </PageSection>
  );
}
