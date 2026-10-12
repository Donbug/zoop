import PageSection from '@/components/common/PageSection';
import EmptyState from '@/components/common/EmptyState';

// A-ADM-04b
// TODO: 실제 모델 호출·재생을 구분하고 비용 미제공은 0원과 구분한다.
export default function AiUsageOverview() {
  return (
    <PageSection title="AI 사용량·오류">
      <EmptyState message="준비 중입니다." />
    </PageSection>
  );
}
