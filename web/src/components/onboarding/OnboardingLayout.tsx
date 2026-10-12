import { NavLink, Outlet } from 'react-router-dom';

export default function OnboardingLayout() {
  return (
    <main className="mx-auto min-h-dvh max-w-3xl px-4 py-8">
      <p className="text-xl font-bold">줍 시작하기</p>
      <nav aria-label="초기 설정 단계" className="mt-6 flex flex-wrap gap-4">
        <NavLink to="/onboarding" end>
          투자 여부
        </NavLink>
        <NavLink to="/onboarding/account">가상 계좌</NavLink>
        <NavLink to="/onboarding/watchlist">관심 종목</NavLink>
      </nav>
      <Outlet />
    </main>
  );
}
