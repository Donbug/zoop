import PageSection from '@/components/common/PageSection';
import EmptyState from '@/components/common/EmptyState';

// A-ADM-01
// TODO: 공개 그래프 버전·작업·회차·회원 운영 요약을 연결한다.
export default function DashboardSummary() {
  return (
    <PageSection title="운영 현황">
      <EmptyState message="준비 중입니다." />
    </PageSection>
  );
}
