type LoadingSize = 'sm' | 'md' | 'lg';

const sizes: Record<LoadingSize, string> = {
  sm: 'size-4 border-[1.5px]',
  md: 'size-5 border-2',
  lg: 'size-6 border-2',
};

export function LoadingSpinner({ size = 'md' }: { size?: LoadingSize }) {
  return (
    <span
      aria-hidden="true"
      className={`inline-block shrink-0 rounded-full border-zoop-line border-t-zoop-ink motion-safe:animate-spin ${sizes[size]}`}
    />
  );
}

/** Shared API loading state: visible motion with an accessible, visually hidden label. */
export default function LoadingIndicator({
  label,
  size = 'md',
  className = '',
}: {
  label: string;
  size?: LoadingSize;
  className?: string;
}) {
  return (
    <span
      role="status"
      aria-live="polite"
      aria-busy="true"
      className={`inline-flex items-center justify-center ${className}`}
    >
      <LoadingSpinner size={size} />
      <span className="sr-only">{label}</span>
    </span>
  );
}
