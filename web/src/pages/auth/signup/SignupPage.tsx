import PageShell from '@/components/common/PageShell';
import SignupForm from '@/components/auth/SignupForm';
import { Link } from 'react-router-dom';

export default function SignupPage() {
  return (
    <PageShell title="회원가입">
      <SignupForm />

      <Link to="/login" className="text-emerald-700 underline">
        로그인으로
      </Link>
    </PageShell>
  );
}
