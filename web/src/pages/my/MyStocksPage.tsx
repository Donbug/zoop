import PageShell from '@/components/common/PageShell';
import HoldingsSection from '@/components/my/HoldingsSection';
import WatchlistSection from '@/components/my/WatchlistSection';
import { useAuth } from '@/hooks/useAuth';

export default function MyStocksPage() {
  const { logout } = useAuth();
  return (
    <PageShell title="내 종목">
      <HoldingsSection />
      <WatchlistSection />
      <button type="button" onClick={logout} className="underline">
        로그아웃
      </button>
    </PageShell>
  );
}
