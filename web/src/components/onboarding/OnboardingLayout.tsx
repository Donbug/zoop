import { NavLink, Outlet } from 'react-router-dom';
import { useOnboardingStore } from '@/stores/useOnboardingStore';

export default function OnboardingLayout() {
  const saving = useOnboardingStore((s) => s.savingWatchlist);
  const steps = [
    { to: '/onboarding', label: '투자 여부' },
    { to: '/onboarding/account', label: '가상 계좌' },
    { to: '/onboarding/watchlist', label: '관심 종목' },
  ];
  return (
    <main className="mx-auto min-h-dvh max-w-3xl px-4 py-8">
      <p className="text-xl font-bold">줍 시작하기</p>
      <nav aria-label="초기 설정 단계" className="mt-6 flex flex-wrap gap-4">
        {steps.map((step) =>
          saving ? (
            <span key={step.to} aria-disabled="true">
              {step.label}
            </span>
          ) : (
            <NavLink key={step.to} to={step.to} end={step.to === '/onboarding'}>
              {step.label}
            </NavLink>
          ),
        )}
      </nav>
      <Outlet />
    </main>
  );
}
