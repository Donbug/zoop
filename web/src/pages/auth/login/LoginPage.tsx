import type { FormEvent } from 'react';
import { Link, useLocation, useNavigate } from 'react-router-dom';
import { setAccessToken } from '@/apis/auth/auth';
import type { LoginLocationState } from '@/types/auth';

export default function LoginPage() {
  const navigate = useNavigate();
  const location = useLocation();

  function handleSubmit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (!import.meta.env.DEV) return;
    setAccessToken('development-access-token');

    const state = location.state as LoginLocationState | null;
    const from = state?.from;
    navigate(
      from
        ? `${from.pathname ?? '/'}${from.search ?? ''}${from.hash ?? ''}`
        : '/',
      { replace: true },
    );
  }

  return (
    <main className="flex min-h-dvh items-center justify-center bg-gray-950 px-4">
      <section className="w-full max-w-md rounded-3xl bg-white p-8 shadow-2xl">
        <p className="text-sm font-semibold tracking-widest text-emerald-600">
          ZOOP
        </p>
        <h1 className="mt-3 text-3xl font-bold text-gray-950">
          다시 오신 것을 환영해요
        </h1>
        <p className="mt-3 text-sm leading-6 text-gray-500">
          실제 인증 API가 연결되기 전까지 개발용 로그인으로 보호 라우트를 확인할
          수 있습니다.
        </p>
        {import.meta.env.DEV && (
          <form className="mt-8" onSubmit={handleSubmit}>
            <button
              type="submit"
              className="w-full rounded-xl bg-gray-950 px-4 py-3 font-semibold text-white transition hover:bg-gray-800"
            >
              개발용으로 시작하기
            </button>
          </form>
        )}
        <div className="mt-6 flex flex-col gap-3">
          <Link to="/signup" className="text-emerald-700 underline">
            이메일로 회원가입
          </Link>
          <Link to="/?mode=all" className="text-emerald-700 underline">
            로그인 없이 둘러보기
          </Link>
        </div>
      </section>
    </main>
  );
}
