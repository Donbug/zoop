import type { ReactNode } from 'react';
import ServiceHeader from '@/components/common/ServiceHeader';

export default function AuthFrame({
  children,
  screen,
}: {
  children: ReactNode;
  screen: string;
}) {
  return (
    <div className="service-surface auth-surface" data-screen-id={screen}>
      <ServiceHeader />
      <main className="mx-auto flex min-h-[calc(100dvh-48px)] w-full max-w-[448px] flex-col justify-center gap-5 px-6 py-12">
        {children}
      </main>
    </div>
  );
}
