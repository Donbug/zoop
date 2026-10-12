import PageSection from '@/components/common/PageSection';
import EmptyState from '@/components/common/EmptyState';

// D-COM-04 내부 요소
// TODO: 기업 상세와 같은 asOf를 사용하고 전체 지도 진입을 연결한다.
export default function CompanyRelationGraph() {
  return (
    <PageSection title="기업 관계 그래프">
      <EmptyState message="준비 중입니다." />
    </PageSection>
  );
}
