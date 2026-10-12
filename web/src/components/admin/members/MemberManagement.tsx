import PageSection from '@/components/common/PageSection';
import EmptyState from '@/components/common/EmptyState';

// A-ADM-05
// TODO: 가명 ID·마스킹 이메일·정상/차단 필터와 접근 권한을 연결한다.
export default function MemberManagement() {
  return (
    <PageSection title="회원·접근 관리">
      <EmptyState message="준비 중입니다." />
    </PageSection>
  );
}
