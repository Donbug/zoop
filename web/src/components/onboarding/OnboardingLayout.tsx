import { Outlet, useLocation } from 'react-router-dom';
import SlimHeader from '@/components/common/SlimHeader';
import {
  readSocialLinkResult,
  socialLinkMessage,
} from '@/components/common/socialLinkResult';

// Explicit back/continue actions in each step own the onboarding flow.
// A social-link result forwarded by MapEntryRoute (?social=) is announced here.
export default function OnboardingLayout() {
  const social = readSocialLinkResult(useLocation().search);
  return (
    <div className="service-surface">
      <SlimHeader />
      <main className="mx-auto min-h-[calc(100dvh-48px)] w-full max-w-[688px] px-6 py-4">
        {social && (
          <p
            role="status"
            className="mb-3 rounded-panel bg-zoop-soft px-3 py-2 text-caption"
          >
            {socialLinkMessage[social]}
          </p>
        )}
        <Outlet />
      </main>
    </div>
  );
}
