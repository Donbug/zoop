import PageShell from '@/components/common/PageShell';
import VirtualAccountSelector from '@/components/onboarding/VirtualAccountSelector';

export default function VirtualAccountPage() {
  return (
    <PageShell title="가상 계좌 연결">
      <VirtualAccountSelector />
    </PageShell>
  );
}
