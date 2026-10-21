import type { ReactNode } from 'react';
import SlimHeader from '@/components/common/SlimHeader';

export default function AuthFrame({
  children,
  screen,
  aside,
}: {
  children: ReactNode;
  screen: string;
  /** 넓은 화면에서 폼 왼쪽에 두는 서비스 소개. 좁은 화면에서는 폼 위에 온다. */
  aside?: ReactNode;
}) {
  return (
    <div className="service-surface auth-surface" data-screen-id={screen}>
      <SlimHeader />
      {aside ? (
        <main className="mx-auto grid min-h-[calc(100dvh-48px)] w-full max-w-[1280px] items-center gap-10 px-6 py-12 lg:py-8 lg:grid-cols-[minmax(0,1fr)_400px] lg:gap-16 lg:px-10 xl:gap-[120px]">
          {aside}
          {children}
        </main>
      ) : (
        <main className="mx-auto flex min-h-[calc(100dvh-48px)] w-full max-w-[428px] flex-col gap-5 px-6 py-12">
          {children}
        </main>
      )}
    </div>
  );
}
