import PageSection from '@/components/common/PageSection';
import EmptyState from '@/components/common/EmptyState';

// PDF 실제 4페이지
// TODO: 목록 결과와 기업 상세·지도 이동을 연결한다.
export default function StockList() {
  return (
    <PageSection title="종목 목록">
      <EmptyState message="준비 중입니다." />
    </PageSection>
  );
}
