import PageSection from '@/components/common/PageSection';
import EmptyState from '@/components/common/EmptyState';

// D-WAT-01
// TODO: 종목 검색·추가·제거와 저장을 연결한다. 0개 선택을 허용한다.
export default function WatchlistSelector() {
  return (
    <PageSection title="관심 종목 선택">
      <EmptyState message="준비 중입니다." />
    </PageSection>
  );
}
