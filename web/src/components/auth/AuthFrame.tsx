import type { ReactNode } from 'react';

export default function AuthFrame({
  children,
  screen,
}: {
  children: ReactNode;
  screen: string;
}) {
  return (
    <div
      className="min-h-dvh bg-[#f5f5f5] text-gray-950"
      data-screen-id={screen}
    >
      <header className="flex h-12 items-center border-b border-gray-200 bg-white px-6">
        <span className="text-xl font-extrabold">
          줍{' '}
          <small className="ml-1 text-xs font-normal text-gray-500">Zoop</small>
        </span>
      </header>
      <main className="mx-auto flex w-full max-w-md flex-col gap-5 px-4 pt-10 pb-8">
        {children}
      </main>
    </div>
  );
}
