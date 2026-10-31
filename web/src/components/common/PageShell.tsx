import type { PageShellProps } from '@/types/common';

export default function PageShell({ title, children }: PageShellProps) {
  return (
    <section className="space-y-6 py-8">
      <h1 className="text-display font-bold">{title}</h1>
      {children}
    </section>
  );
}
