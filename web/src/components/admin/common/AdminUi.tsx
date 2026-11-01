import type { ReactNode } from 'react';
import { Link } from 'react-router-dom';
import LoadingIndicator, {
  LoadingSpinner,
} from '@/components/common/LoadingIndicator';
import { adminErrorMessage, BUTTON, FOCUS_RING } from './adminStyles';

// 관리자 화면이 함께 쓰는 표시 부품. 모두 Tailwind 유틸리티와 zoop 토큰만 쓴다(#169 시각 기준).
// 클래스 묶음·숫자 표기·오류 문구는 adminStyles.ts에 둔다.

export function PageHeader({
  title,
  actions,
}: {
  title: string;
  actions?: ReactNode;
}) {
  return (
    <header className="flex flex-wrap items-center justify-between gap-3">
      <h1 className="text-title font-[750] tracking-[-0.035em]">{title}</h1>
      {actions && <div className="flex items-center gap-3">{actions}</div>}
    </header>
  );
}

export function Loading({ children }: { children: ReactNode }) {
  return (
    <LoadingIndicator
      label={String(children)}
      className="flex min-h-10 w-full py-2"
    />
  );
}

export function ErrorBox({
  title,
  error,
  onRetry,
}: {
  title: string;
  error: Error;
  onRetry?: () => void;
}) {
  return (
    <div
      role="alert"
      className="flex flex-wrap items-center gap-3 rounded-2xl bg-zoop-soft px-4 py-3"
    >
      <div className="min-w-0 flex-1">
        <p className="text-caption font-semibold">{title}</p>
        <p className="mt-0.5 text-caption text-zoop-muted">
          {adminErrorMessage(error)}
        </p>
      </div>
      {onRetry && (
        <button type="button" onClick={onRetry} className={BUTTON}>
          다시 시도
        </button>
      )}
    </div>
  );
}

export function Empty({ children }: { children: ReactNode }) {
  return (
    <p className="rounded-2xl bg-zoop-soft px-4 py-4 text-caption text-zoop-muted">
      {children}
    </p>
  );
}

/** 표 위 보조 설명(집계 시각·기준 등) */
export function Note({ children }: { children: ReactNode }) {
  return (
    <p className="text-caption leading-relaxed text-zoop-muted">{children}</p>
  );
}

export function Metric({
  label,
  value,
  detail,
}: {
  label: string;
  value: ReactNode;
  detail?: ReactNode;
}) {
  return (
    <div className="flex min-w-0 flex-col gap-1">
      <dt className="text-caption text-zoop-muted">{label}</dt>
      <dd className="text-title font-[750] tracking-[-0.03em] tabular-nums">
        {value}
      </dd>
      {detail && (
        <dd className="text-caption leading-relaxed text-zoop-faint tabular-nums">
          {detail}
        </dd>
      )}
    </div>
  );
}

export function Section({
  title,
  link,
  children,
}: {
  title: string;
  /** 제목 오른쪽의 관리 화면 바로 가기 */
  link?: { to: string; label: string }[];
  children: ReactNode;
}) {
  return (
    <section className="flex min-w-0 flex-col gap-2" aria-label={title}>
      <div className="flex items-center justify-between gap-2">
        <h2 className="text-body font-bold">{title}</h2>
        {link && (
          <div className="flex items-center gap-3">
            {link.map((item) => (
              <Link
                key={item.to}
                to={item.to}
                className={`text-caption text-zoop-muted hover:text-zoop-ink ${FOCUS_RING}`}
              >
                {item.label} →
              </Link>
            ))}
          </div>
        )}
      </div>
      {children}
    </section>
  );
}

/** 가로로 넘치면 표만 스크롤한다. */
export function Table({
  caption,
  children,
}: {
  caption: string;
  children: ReactNode;
}) {
  return (
    <div className="overflow-x-auto">
      <table className="w-full border-collapse">
        <caption className="sr-only">{caption}</caption>
        {children}
      </table>
    </div>
  );
}

/** 집계 기간·보기 전환 같은 단일 선택. 선택한 버튼은 aria-pressed */
export function Segmented<T extends string>({
  label,
  value,
  options,
  onChange,
}: {
  label: string;
  value: T;
  options: { value: T; label: string }[];
  onChange: (value: T) => void;
}) {
  return (
    <div
      role="group"
      aria-label={label}
      className="inline-flex rounded-full bg-zoop-soft p-1"
    >
      {options.map((option) => (
        <button
          key={option.value}
          type="button"
          aria-pressed={option.value === value}
          onClick={() => onChange(option.value)}
          className={`min-h-8 rounded-full px-4 text-caption text-zoop-muted transition-colors aria-pressed:bg-zoop-ink aria-pressed:font-semibold aria-pressed:text-zoop-paper ${FOCUS_RING}`}
        >
          {option.label}
        </button>
      ))}
    </div>
  );
}

/** 화면 안 탭. 선택한 탭은 aria-selected다. line은 A-ADM-03처럼 폭을 나눠 쓰고 아래 선으로 표시한다. */
export function Tabs<T extends string>({
  label,
  value,
  options,
  onChange,
  variant = 'pill',
}: {
  label: string;
  value: T;
  options: { value: T; label: string; icon?: ReactNode }[];
  onChange: (value: T) => void;
  variant?: 'pill' | 'line';
}) {
  if (variant === 'line')
    return (
      <div
        role="tablist"
        aria-label={label}
        className="flex w-full overflow-x-auto border-b-[0.667px] border-zoop-line"
      >
        {options.map((option) => (
          <button
            key={option.value}
            type="button"
            role="tab"
            aria-selected={option.value === value}
            onClick={() => onChange(option.value)}
            className={`-mb-px inline-flex min-h-11 flex-1 shrink-0 items-center justify-center gap-1.5 border-b-2 border-transparent px-4 text-body text-zoop-muted transition-colors hover:text-zoop-ink aria-selected:border-zoop-ink aria-selected:font-bold aria-selected:text-zoop-ink ${FOCUS_RING}`}
          >
            {option.icon}
            {option.label}
          </button>
        ))}
      </div>
    );
  return (
    <div
      role="tablist"
      aria-label={label}
      className="inline-flex max-w-full overflow-x-auto rounded-full bg-zoop-soft p-1"
    >
      {options.map((option) => (
        <button
          key={option.value}
          type="button"
          role="tab"
          aria-selected={option.value === value}
          onClick={() => onChange(option.value)}
          className={`min-h-9 shrink-0 rounded-full px-4 text-caption text-zoop-muted transition-colors aria-selected:bg-zoop-ink aria-selected:font-bold aria-selected:text-zoop-paper ${FOCUS_RING}`}
        >
          {option.label}
        </button>
      ))}
    </div>
  );
}

export function MoreButton({
  loading,
  error,
  onClick,
}: {
  loading: boolean;
  error: Error | null;
  onClick: () => void;
}) {
  return (
    <div className="flex flex-wrap items-center gap-3">
      <button
        type="button"
        onClick={onClick}
        disabled={loading}
        className={BUTTON}
      >
        {loading ? (
          <>
            <LoadingSpinner size="sm" />
            <span className="sr-only">다음 항목을 불러오는 중</span>
          </>
        ) : (
          '더 보기'
        )}
      </button>
      {error && (
        <p role="alert" className="text-caption text-zoop-alert">
          다음 목록을 불러오지 못했어요. {adminErrorMessage(error)}
        </p>
      )}
    </div>
  );
}
