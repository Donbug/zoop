import PageSection from '@/components/common/PageSection';
import EmptyState from '@/components/common/EmptyState';

// PDF 실제 4페이지
// TODO: 기업명·영문명·티커 검색을 연결한다.
export default function StockSearchForm() {
  return (
    <PageSection title="종목 검색">
      <EmptyState message="준비 중입니다." />
    </PageSection>
  );
}
