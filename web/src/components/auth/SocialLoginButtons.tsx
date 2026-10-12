import PageSection from '@/components/common/PageSection';
import EmptyState from '@/components/common/EmptyState';

// D-AUT-01
// TODO: Google·카카오 인증 공급자 연동이 확정되면 활성화한다.
export default function SocialLoginButtons() {
  return (
    <PageSection title="간편 로그인">
      <EmptyState message="준비 중입니다." />
    </PageSection>
  );
}
