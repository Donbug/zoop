import PageSection from '@/components/common/PageSection';
import EmptyState from '@/components/common/EmptyState';

// D-ONB-02
// TODO: 모의 계좌 목록과 연결·건너뛰기를 제공한다. 실제 증권 계좌가 아니다.
export default function VirtualAccountSelector() {
  return (
    <PageSection title="가상 계좌">
      <EmptyState message="준비 중입니다." />
    </PageSection>
  );
}
