import type { PageSectionProps } from '@/types/common';

export default function PageSection({ title, children }: PageSectionProps) {
  return (
    <section className="rounded-xl border border-gray-200 bg-white p-5">
      <h2 className="mb-3 text-title-sm font-semibold">{title}</h2>
      {children}
    </section>
  );
}
