import { Outlet } from 'react-router-dom';
import SlimHeader from '@/components/common/SlimHeader';

// Explicit back/continue actions in each step own the onboarding flow.
export default function OnboardingLayout() {
  return (
    <div className="service-surface">
      <SlimHeader />
      <main className="mx-auto min-h-[calc(100dvh-48px)] w-full max-w-[688px] px-6 py-4">
        <Outlet />
      </main>
    </div>
  );
}
