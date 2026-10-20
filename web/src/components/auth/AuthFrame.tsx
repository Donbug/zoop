import type { ReactNode } from 'react';
import SlimHeader from '@/components/common/SlimHeader';

export default function AuthFrame({
  children,
  screen,
}: {
  children: ReactNode;
  screen: string;
}) {
  return (
    <div className="service-surface auth-surface" data-screen-id={screen}>
      <SlimHeader />
      <main className="mx-auto flex min-h-[calc(100dvh-48px)] w-full max-w-[428px] flex-col gap-5 px-6 py-12">
        {children}
      </main>
    </div>
  );
}
