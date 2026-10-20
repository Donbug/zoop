import { useLocation } from 'react-router-dom';
import AuthFrame from '@/components/auth/AuthFrame';
import SignupForm from '@/components/auth/SignupForm';

// D-AUT-02 회원가입. 소셜 콜백이 신규 사용자를 /signup?social=pending으로 보내면 소셜 가입을 마친다.
export default function SignupPage() {
  const { search } = useLocation();
  const social = new URLSearchParams(search).get('social') === 'pending';
  return (
    <AuthFrame screen="D-AUT-02">
      <SignupForm key={social ? 'social' : 'email'} social={social} />
    </AuthFrame>
  );
}
