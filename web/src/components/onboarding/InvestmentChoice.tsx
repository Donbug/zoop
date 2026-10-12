import PageSection from '@/components/common/PageSection';
import EmptyState from '@/components/common/EmptyState';

// D-ONB-01
// TODO: 투자 중/미투자 선택을 온보딩 초안에 반영한다.
export default function InvestmentChoice() {
  return (
    <PageSection title="투자 여부">
      <EmptyState message="준비 중입니다." />
    </PageSection>
  );
}
