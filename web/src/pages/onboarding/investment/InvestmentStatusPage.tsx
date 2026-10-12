import PageShell from '@/components/common/PageShell';
import InvestmentChoice from '@/components/onboarding/InvestmentChoice';

export default function InvestmentStatusPage() {
  return (
    <PageShell title="투자 여부 선택">
      <InvestmentChoice />
    </PageShell>
  );
}
