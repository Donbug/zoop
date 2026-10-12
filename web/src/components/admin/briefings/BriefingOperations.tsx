import PageSection from '@/components/common/PageSection';
import EmptyState from '@/components/common/EmptyState';

// A-ADM-04
// TODO: 회차 원본과 정정 이력을 구분한다. 스케줄러 실행은 별도 백엔드 작업이다.
export default function BriefingOperations() {
  return (
    <PageSection title="브리핑 회차·이력">
      <EmptyState message="준비 중입니다." />
    </PageSection>
  );
}
