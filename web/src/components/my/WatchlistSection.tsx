import PageSection from '@/components/common/PageSection';
import EmptyState from '@/components/common/EmptyState';

// D-MY-01 참조만 존재
// TODO: 서버에 저장된 관심 종목을 조회한다. 온보딩 초안과 구분한다.
export default function WatchlistSection() {
  return (
    <PageSection title="관심 종목">
      <EmptyState message="준비 중입니다." />
    </PageSection>
  );
}
