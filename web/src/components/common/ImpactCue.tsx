import type { ReactNode } from 'react';

type Tone =
  | 'positive'
  | 'negative'
  | 'mixed'
  | 'neutral'
  | 'uncertain'
  | 'undetermined'
  | 'watch';
type Symbol = 'up' | 'warning' | 'balance' | 'question' | 'check' | 'calendar';
const tones = {
  positive: 'text-zoop-positive border-zoop-positive/25 bg-zoop-positive/8',
  negative: 'text-zoop-alert border-zoop-alert/25 bg-zoop-alert/8',
  mixed: 'text-zoop-mixed border-zoop-mixed/25 bg-zoop-mixed/8',
  neutral: 'text-zoop-muted border-zoop-line bg-zoop-soft',
  uncertain: 'text-zoop-muted border-zoop-line bg-zoop-soft',
  undetermined: 'text-zoop-muted border-zoop-line bg-zoop-soft',
  watch: 'text-zoop-muted border-zoop-line bg-zoop-soft',
};
const symbols: Record<Tone, Symbol> = {
  positive: 'up',
  negative: 'warning',
  mixed: 'balance',
  neutral: 'balance',
  uncertain: 'question',
  undetermined: 'question',
  watch: 'question',
};
const paths: Record<Symbol, ReactNode> = {
  up: <path d="m3 17 6-6 4 4 8-10m-6 0h6v6" />,
  warning: (
    <>
      <path d="m12 3 10 18H2L12 3Z" />
      <path d="M12 9v5m0 3v.1" />
    </>
  ),
  balance: (
    <>
      <path d="M12 3v18M5 7h14M4 7l-3 7h6L4 7Zm16 0-3 7h6l-3-7ZM8 21h8" />
    </>
  ),
  question: (
    <>
      <circle cx="12" cy="12" r="9" />
      <path d="M9 9a3 3 0 0 1 6 0c0 2-3 2-3 5m0 3v.1" />
    </>
  ),
  check: (
    <>
      <circle cx="12" cy="12" r="9" />
      <path d="m7 12 3 3 7-7" />
    </>
  ),
  calendar: (
    <>
      <rect x="3" y="5" width="18" height="16" rx="2" />
      <path d="M7 3v4m10-4v4M3 10h18m-14 5h3m4 0h3" />
    </>
  ),
};

/** Business impact only: its green/red cues are independent of quote rise/fall colors. */
export default function ImpactCue({
  tone,
  children,
  badge = false,
  icon,
}: {
  tone: Tone;
  children: ReactNode;
  badge?: boolean;
  icon?: Symbol;
}) {
  return (
    <span
      className={`inline-flex items-center gap-2 ${badge ? `rounded-full border px-2.5 py-1 ${tones[tone]}` : tones[tone].split(' ')[0]}`}
    >
      <svg
        width="18"
        height="18"
        viewBox="0 0 24 24"
        fill="none"
        stroke="currentColor"
        strokeWidth="1.8"
        strokeLinecap="round"
        strokeLinejoin="round"
        aria-hidden="true"
        focusable="false"
        className="shrink-0"
      >
        {paths[icon ?? symbols[tone]]}
      </svg>
      <span>{children}</span>
    </span>
  );
}
