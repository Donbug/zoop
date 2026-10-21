import type { ReactNode } from 'react';
import SlimHeader from '@/components/common/SlimHeader';
import './login-surface.css';

/** D-AUT-01만 사용하는 장식 배경. 로그인 정보와 조작은 모두 실제 HTML이다. */
export default function LoginFrame({ children }: { children: ReactNode }) {
  return (
    <div
      className="service-surface auth-surface login-surface"
      data-screen-id="D-AUT-01"
    >
      <SlimHeader themeSwitch />
      <main className="relative isolate flex min-h-[calc(100dvh-48px)] flex-col items-center justify-center overflow-hidden bg-zoop-paper px-6 py-12 sm:py-16">
        <img
          src="/auth/login-news-background.webp"
          alt=""
          aria-hidden="true"
          width={1672}
          height={941}
          fetchPriority="high"
          draggable={false}
          className="login-background pointer-events-none absolute top-1/2 left-0 -z-10 hidden h-auto w-full -translate-y-1/2 mask-[linear-gradient(to_bottom,transparent,black_12%,black_88%,transparent)] mix-blend-multiply md:block"
        />
        {children}
      </main>
    </div>
  );
}
