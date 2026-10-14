import { NavLink, Outlet } from 'react-router-dom';
import { useOnboardingStore } from '@/stores/useOnboardingStore';
import ServiceHeader from '@/components/common/ServiceHeader';

export default function OnboardingLayout() {
  const saving = useOnboardingStore((s) => s.savingWatchlist);
  const steps = [
    { to: '/onboarding', label: '투자 여부' },
    { to: '/onboarding/account', label: '가상 계좌' },
    { to: '/onboarding/watchlist', label: '관심 종목' },
  ];
  return (
    <div className="service-surface onboarding-surface">
      <ServiceHeader />
      <main className="mx-auto min-h-[calc(100dvh-48px)] w-full max-w-[800px] px-6 py-10 md:px-10">
        <div className="flex items-end justify-between gap-4 border-b border-[#d6d6d2] pb-4">
          <div>
            <p className="text-[11px] font-medium tracking-[0.14em] text-[#94948f]">
              INITIAL SETUP
            </p>
            <p className="mt-1 text-xl font-bold tracking-[-0.03em]">
              줍 시작하기
            </p>
          </div>
          <nav
            aria-label="초기 설정 단계"
            className="flex items-center gap-1 rounded bg-[#f2f2f0] p-1 text-[11px] font-semibold text-[#5f5f5b]"
          >
            {steps.map((step, index) =>
              saving ? (
                <span
                  key={step.to}
                  aria-disabled="true"
                  className="px-2 py-1.5 opacity-50"
                >
                  {index + 1}. {step.label}
                </span>
              ) : (
                <NavLink
                  key={step.to}
                  to={step.to}
                  end={step.to === '/onboarding'}
                  className={({ isActive }) =>
                    `rounded px-2 py-1.5 ${isActive ? 'bg-white text-[#1a1a1a] shadow-[0_0_0_0.5px_#1a1a1a14]' : ''}`
                  }
                >
                  {index + 1}. {step.label}
                </NavLink>
              ),
            )}
          </nav>
        </div>
        <Outlet />
      </main>
    </div>
  );
}
