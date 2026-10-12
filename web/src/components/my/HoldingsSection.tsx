import PageSection from '@/components/common/PageSection';
import EmptyState from '@/components/common/EmptyState';

// D-MY-01 참조만 존재
// TODO: 내 종목 화면은 독립 프레임이 없어 세부 UI 확정이 필요하다.
export default function HoldingsSection() {
  return (
    <PageSection title="보유 종목">
      <EmptyState message="준비 중입니다." />
    </PageSection>
  );
}
