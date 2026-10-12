import PageShell from '@/components/common/PageShell';
import WatchlistSelector from '@/components/onboarding/WatchlistSelector';

export default function WatchlistSetupPage() {
  return (
    <PageShell title="관심 종목 선택">
      <WatchlistSelector />
    </PageShell>
  );
}
