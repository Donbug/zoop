import PageSection from '@/components/common/PageSection';
import EmptyState from '@/components/common/EmptyState';

// D-GRP-01 / 01b
// TODO: 시장·개인·회차 지도와 확대 상태를 하나의 캔버스로 처리한다. 그래프 엔진은 추후 연결한다.
export default function GraphCanvas() {
  return (
    <PageSection title="관계 지도">
      <EmptyState message="준비 중입니다." />
    </PageSection>
  );
}
