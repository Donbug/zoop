import PageShell from '@/components/common/PageShell';
import StockSearchForm from '@/components/stocks/StockSearchForm';
import StockList from '@/components/stocks/StockList';

export default function StocksPage() {
  return (
    <PageShell title="종목">
      <StockSearchForm />
      <StockList />
    </PageShell>
  );
}
