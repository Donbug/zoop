import { useNavigate } from 'react-router-dom';
import { clearAuthentication } from '@/apis/auth/auth';

export default function MyPage() {
  const navigate = useNavigate();

  function handleLogout() {
    clearAuthentication();
    navigate('/login', { replace: true });
  }

  return (
    <section className="py-8 md:py-12">
      <h1 className="text-3xl font-bold text-gray-950">마이페이지</h1>
      <p className="mt-3 text-gray-600">
        관심 종목과 개인 설정을 관리하는 페이지입니다.
      </p>
      <button
        type="button"
        onClick={handleLogout}
        className="mt-8 rounded-xl border border-gray-300 bg-white px-5 py-3 font-semibold text-gray-700 hover:bg-gray-100"
      >
        로그아웃
      </button>
    </section>
  );
}
