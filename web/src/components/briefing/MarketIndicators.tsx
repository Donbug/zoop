import PageSection from '@/components/common/PageSection';
import EmptyState from '@/components/common/EmptyState';

// D-BRF-01 / 02
// TODO: 회차 시각과 지표 관측 시각을 구분하고 정상·지연·사용 불가·실패를 분리한다.
export default function MarketIndicators() {
  return (
    <PageSection title="주요 시장 지표">
      <EmptyState message="준비 중입니다." />
    </PageSection>
  );
}
