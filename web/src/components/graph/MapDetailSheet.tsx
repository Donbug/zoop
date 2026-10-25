import {
  useContext,
  useEffect,
  useRef,
  useState,
  useSyncExternalStore,
  type ReactNode,
} from 'react';
import { createPortal } from 'react-dom';
import { GraphAppearanceContext } from './graph-appearance';
import { mapAppearanceStyles } from '@/components/common/map-appearance-styles';
function subscribe(callback: () => void) {
  const media = window.matchMedia?.('(max-width: 767px)');
  media?.addEventListener('change', callback);
  return () => media?.removeEventListener('change', callback);
}
const mobileSnapshot = () =>
  window.matchMedia?.('(max-width: 767px)').matches ?? false;
// M-GRP-01: prototype's 50%/90% snaps, drag/keyboard handle, modal focus and return.
export default function MapDetailSheet({
  open,
  children,
  onClose,
  suspended = false,
  tutorial,
  tutorialLocked = false,
}: {
  open: boolean;
  children: ReactNode;
  onClose: () => void;
  suspended?: boolean;
  tutorial?: ReactNode;
  tutorialLocked?: boolean;
}) {
  const appearance = useContext(GraphAppearanceContext);
  const mobile = useSyncExternalStore(subscribe, mobileSnapshot, () => false);
  const [full, setFull] = useState(false);
  const frame = useRef<HTMLDivElement>(null);
  const gesture = useRef<{ y: number; last: number } | null>(null);
  const dragged = useRef(false);
  useEffect(() => {
    // The sheet is portaled outside the canvas; its snap changes need an
    // explicit notification so an active whole-graph fit reserves its area.
    const tick = requestAnimationFrame(() =>
      window.dispatchEvent(new Event('zoop:graph-viewport-change')),
    );
    return () => cancelAnimationFrame(tick);
  }, [mobile, open, full, suspended]);
  useEffect(() => {
    if (!mobile || !open || suspended) return;
    const opener =
      document.activeElement instanceof HTMLElement
        ? document.activeElement
        : null;
    const siblings = Array.from(document.body.children)
      .filter(
        (element): element is HTMLElement =>
          element instanceof HTMLElement &&
          element !== frame.current?.parentElement,
      )
      .map((element) => ({ element, inert: element.inert }));
    siblings.forEach(({ element }) => {
      element.inert = true;
    });
    const tick = requestAnimationFrame(() => frame.current?.focus());
    return () => {
      cancelAnimationFrame(tick);
      siblings.forEach(({ element, inert }) => {
        element.inert = inert;
      });
      if (opener?.isConnected) opener.focus();
    };
  }, [mobile, open, suspended]);
  useEffect(() => {
    if (!open) void Promise.resolve().then(() => setFull(false));
  }, [open]);
  if (!open) return null;
  if (!mobile) return <>{children}</>;
  return createPortal(
    <div
      hidden={suspended}
      className={`${appearance ? mapAppearanceStyles(appearance) : ''} ${suspended ? 'hidden' : ''}`}
    >
      <div
        className="fixed inset-0 z-40 bg-black/35"
        aria-hidden="true"
        onClick={onClose}
      />
      <div
        ref={frame}
        tabIndex={-1}
        role="dialog"
        aria-modal="true"
        aria-label="지도 상세"
        data-screen-id="M-GRP-01"
        data-snap={full || tutorialLocked ? 'full' : 'half'}
        className={`fixed inset-x-0 bottom-0 z-50 flex flex-col overflow-hidden rounded-t-xl border border-panel-line bg-white font-panel text-panel-ink shadow-xl outline-none motion-reduce:transition-none [&>aside]:min-h-0! [&>aside]:w-full! [&>aside]:flex-1! ${full || tutorialLocked ? 'h-[90dvh]' : 'h-[50dvh]'}`}
        onKeyDown={(event) => {
          if (event.key === 'Escape') {
            event.stopPropagation();
            onClose();
            return;
          }
          if (event.key !== 'Tab') return;
          const items = frame.current?.querySelectorAll<HTMLElement>(
            'button:not(:disabled),a[href],input,textarea,select,summary,[tabindex="0"]',
          );
          if (!items?.length) return;
          const first = items[0],
            last = items[items.length - 1];
          if (
            event.shiftKey &&
            (document.activeElement === first ||
              document.activeElement === frame.current)
          ) {
            event.preventDefault();
            last.focus();
          } else if (!event.shiftKey && document.activeElement === last) {
            event.preventDefault();
            first.focus();
          }
        }}
      >
        <button
          type="button"
          aria-label={
            full || tutorialLocked ? '시트 작게 보기' : '시트 크게 보기'
          }
          className="flex min-h-8 shrink-0 touch-none items-center justify-center focus-visible:outline-2"
          onClick={() => {
            if (dragged.current) {
              dragged.current = false;
              return;
            }
            setFull(!full);
          }}
          onKeyDown={(event) => {
            if (event.key === 'ArrowUp') {
              event.preventDefault();
              setFull(true);
            }
            if (event.key === 'ArrowDown') {
              event.preventDefault();
              setFull(false);
            }
          }}
          onPointerDown={(event) => {
            event.currentTarget.setPointerCapture?.(event.pointerId);
            gesture.current = { y: event.clientY, last: event.clientY };
            dragged.current = false;
          }}
          onPointerMove={(event) => {
            if (gesture.current) gesture.current.last = event.clientY;
          }}
          onPointerUp={() => {
            if (!gesture.current) return;
            const dy = gesture.current.last - gesture.current.y;
            gesture.current = null;
            dragged.current = Math.abs(dy) > 4;
            if (dy <= -64) setFull(true);
            else if (dy >= 64) {
              if (full) setFull(false);
              else onClose();
            }
          }}
          onPointerCancel={() => {
            gesture.current = null;
            dragged.current = false;
          }}
        >
          <span className="h-1 w-9 rounded-full bg-zoop-muted" />
        </button>
        {/* 닫기는 안에 든 상세 패널의 ×와 Esc·바깥 누르기·아래로 끌기로 한다. 시트 자체 제목줄·닫기는 두지 않는다. */}
        {tutorial}
        {children}
      </div>
    </div>,
    document.body,
  );
}
