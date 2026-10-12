import PageSection from '@/components/common/PageSection';
import EmptyState from '@/components/common/EmptyState';

// D-GRP-T / T2 / T3 / T4 / T5
// TODO: 5개 안내 단계를 데이터로 구성하고 이전·다음·건너뛰기·완료를 연결한다.
export default function GraphTutorial() {
  return (
    <PageSection title="지도 사용 안내">
      <EmptyState message="준비 중입니다." />
    </PageSection>
  );
}
