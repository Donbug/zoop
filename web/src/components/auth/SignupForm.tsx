import PageSection from '@/components/common/PageSection';
import EmptyState from '@/components/common/EmptyState';

// D-AUT-02
// TODO: 이메일·비밀번호·표시 이름·필수 약관 입력과 가입 API를 연결한다.
export default function SignupForm() {
  return (
    <PageSection title="회원가입">
      <EmptyState message="준비 중입니다." />
    </PageSection>
  );
}
