import { useEffect, useRef, type ReactNode } from 'react';

/** D-GRP-02/03/05: native replacement for prototype Radix explanations. */
export default function PanelDisclosure({
  label,
  trigger,
  children,
}: {
  label: string;
  trigger?: ReactNode;
  children: ReactNode;
}) {
  const ref = useRef<HTMLDetailsElement>(null);
  useEffect(() => {
    const onPointer = (event: PointerEvent) => {
      if (
        ref.current?.open &&
        event.target instanceof Node &&
        !ref.current.contains(event.target)
      ) {
        const returnFocus = ref.current.contains(document.activeElement);
        ref.current.open = false;
        if (returnFocus) ref.current.querySelector('summary')?.focus();
      }
    };
    document.addEventListener('pointerdown', onPointer);
    return () => document.removeEventListener('pointerdown', onPointer);
  }, []);
  return (
    <details
      ref={ref}
      className="text-zoop-muted"
      onKeyDown={(event) => {
        if (
          event.target === ref.current?.querySelector('summary') &&
          (event.key === 'Enter' || event.key === ' ')
        ) {
          event.preventDefault();
          if (ref.current) ref.current.open = !ref.current.open;
          return;
        }
        if (event.key === 'Escape' && ref.current?.open) {
          event.preventDefault();
          event.stopPropagation();
          ref.current.open = false;
          ref.current.querySelector('summary')?.focus();
        }
      }}
    >
      <summary
        aria-label={label}
        title={label}
        className="cursor-pointer list-none text-zoop-ink focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-zoop-ink [&::-webkit-details-marker]:hidden"
      >
        {trigger ?? label}
      </summary>
      <div className="mt-2 space-y-2 rounded border border-zoop-line bg-zoop-paper p-3">
        {children}
      </div>
    </details>
  );
}
