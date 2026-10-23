import { useEffect, useRef, useSyncExternalStore } from 'react';

const mobileSnapshot = () =>
  window.matchMedia?.('(max-width: 767px)').matches ?? false;
function subscribe(callback: () => void) {
  const media = window.matchMedia?.('(max-width: 767px)');
  media?.addEventListener('change', callback);
  return () => media?.removeEventListener('change', callback);
}

// M-GRP-01 · native disclosure keeps its trigger keyboard accessible.
export default function GraphMobileTools({
  flow,
  onFlowChange,
  focusActive,
}: {
  flow: boolean;
  onFlowChange?: (flow: boolean) => void;
  focusActive: boolean;
}) {
  const menu = useRef<HTMLDetailsElement>(null);
  const mobile = useSyncExternalStore(subscribe, mobileSnapshot, () => false);
  useEffect(() => {
    const close = (event: PointerEvent) => {
      if (
        event.target instanceof Node &&
        !menu.current?.contains(event.target) &&
        menu.current
      )
        menu.current.open = false;
    };
    document.addEventListener('pointerdown', close);
    return () => document.removeEventListener('pointerdown', close);
  }, []);
  if (!mobile) return null;
  return (
    <details
      ref={menu}
      className="relative hidden max-md:block"
      onKeyDown={(event) => {
        if (event.key === 'Escape' && menu.current?.open) {
          event.preventDefault();
          event.stopPropagation();
          menu.current.open = false;
          menu.current.querySelector('summary')?.focus();
        }
      }}
    >
      <summary
        aria-label="더보기: 지도 보기 방식"
        className="grid size-11 cursor-pointer list-none place-items-center rounded-full border border-zoop-line bg-zoop-paper text-lg font-bold text-zoop-ink shadow-sm marker:content-none focus-visible:outline-2 focus-visible:outline-offset-2"
      >
        <span aria-hidden="true">···</span>
      </summary>
      <div className="absolute right-14 bottom-0 w-56 rounded-lg border border-zoop-line bg-zoop-paper p-3 text-[13px] text-zoop-ink shadow-lg">
        {onFlowChange && (
          <button
            type="button"
            aria-pressed={flow}
            disabled={focusActive}
            className="block! h-auto! min-h-11! w-full! rounded border! border-zoop-line px-3! text-left! text-[13px]! whitespace-nowrap disabled:opacity-50"
            onClick={() => {
              onFlowChange(!flow);
              if (menu.current) menu.current.open = false;
            }}
          >
            흐름 순으로 정렬
          </button>
        )}
        {focusActive && (
          <p className="mt-2">전체 보기로 나온 뒤 정렬을 바꿀 수 있어요.</p>
        )}
        <p className="mt-2 leading-relaxed text-zoop-muted">
          빈 곳을 끌어 이동하고 두 손가락으로 확대·축소해요. 노드를 두 번 누르면
          이웃까지 보여요.
        </p>
      </div>
    </details>
  );
}
