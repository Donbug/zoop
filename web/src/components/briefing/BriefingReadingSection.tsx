import type { ReactNode } from 'react';
import { FOCUS_RING, SECTION } from './briefingStyles';

/** D-BRF-01·02: 간단히 보기에서만 접는다. 전체 보기의 원문은 그대로 유지한다. */
export default function BriefingReadingSection({
  compact,
  title,
  children,
}: {
  compact: boolean;
  title: string;
  children: ReactNode;
}) {
  if (!compact) return <>{children}</>;
  return (
    <details className={SECTION}>
      <summary
        className={`min-h-11 cursor-pointer content-center text-body font-semibold ${FOCUS_RING}`}
      >
        {title}
      </summary>
      <div className="mt-3">{children}</div>
    </details>
  );
}
