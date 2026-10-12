import PageSection from '@/components/common/PageSection';
import EmptyState from '@/components/common/EmptyState';

// A-ADM-05b
// TODO: 기존 감사 기록의 동작·대상·사유·행위자를 조회한다.
export default function AuditLogTable() {
  return (
    <PageSection title="관리자 감사 로그">
      <EmptyState message="준비 중입니다." />
    </PageSection>
  );
}
