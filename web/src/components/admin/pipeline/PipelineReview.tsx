import PageSection from '@/components/common/PageSection';
import EmptyState from '@/components/common/EmptyState';

// A-ADM-03
// TODO: 후보·공개 버전·작업 상태를 연결한다. 검수 권한과 R1 정책은 확정 필요하다.
export default function PipelineReview() {
  return (
    <PageSection title="그래프 관제·검수">
      <EmptyState message="준비 중입니다." />
    </PageSection>
  );
}
