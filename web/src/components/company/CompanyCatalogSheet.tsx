import {
  useEffect,
  useEffectEvent,
  useId,
  useRef,
  type ReactNode,
} from 'react';
import { createPortal } from 'react-dom';
import { useColorTheme } from '@/util/theme-color';

/** D-COM-01 D9: prototype company-switcher의 모바일 Sheet. */
export default function CompanyCatalogSheet({
  children,
  onClose,
}: {
  children: ReactNode;
  onClose: () => void;
}) {
  const dark = useColorTheme() === 'dark';
  const title = useId();
  const frame = useRef<HTMLDivElement>(null);
  const close = useEffectEvent(onClose);
  useEffect(() => {
    const opener =
      document.activeElement instanceof HTMLElement
        ? document.activeElement
        : null;
    const siblings = Array.from(document.body.children)
      .filter(
        (el): el is HTMLElement =>
          el instanceof HTMLElement && el !== frame.current?.parentElement,
      )
      .map((el) => ({ el, inert: el.inert }));
    siblings.forEach(({ el }) => {
      el.inert = true;
    });
    const wasLocked = document.body.classList.contains('overflow-hidden');
    document.body.classList.add('overflow-hidden');
    const tick = requestAnimationFrame(() => frame.current?.focus());
    function keys(event: KeyboardEvent) {
      if (event.key === 'Escape') {
        event.preventDefault();
        event.stopPropagation();
        close();
        return;
      }
      if (event.key !== 'Tab') return;
      const controls = Array.from(
        frame.current?.querySelectorAll<HTMLElement>(
          'a[href],button:not(:disabled),input:not(:disabled),select:not(:disabled),textarea:not(:disabled),[tabindex="0"]',
        ) ?? [],
      ).filter((el) => !el.closest('[hidden]'));
      const first = controls[0],
        last = controls.at(-1);
      if (!first) {
        event.preventDefault();
        frame.current?.focus();
        return;
      }
      if (
        event.shiftKey &&
        (document.activeElement === first ||
          document.activeElement === frame.current)
      ) {
        event.preventDefault();
        last?.focus();
      } else if (
        !event.shiftKey &&
        (document.activeElement === last ||
          document.activeElement === frame.current)
      ) {
        event.preventDefault();
        first.focus();
      }
    }
    function contain(event: FocusEvent) {
      if (
        event.target instanceof Node &&
        !frame.current?.contains(event.target)
      )
        frame.current?.focus();
    }
    document.addEventListener('keydown', keys);
    document.addEventListener('focusin', contain);
    return () => {
      cancelAnimationFrame(tick);
      document.removeEventListener('keydown', keys);
      document.removeEventListener('focusin', contain);
      siblings.forEach(({ el, inert }) => {
        el.inert = inert;
      });
      if (!wasLocked) document.body.classList.remove('overflow-hidden');
      if (opener?.isConnected) opener.focus();
    };
  }, []);
  return createPortal(
    <div>
      <div
        aria-hidden="true"
        className="fixed inset-0 z-[70] bg-black/40"
        onClick={onClose}
      />
      <div
        ref={frame}
        role="dialog"
        aria-modal="true"
        aria-labelledby={title}
        tabIndex={-1}
        className={`fixed inset-x-0 bottom-0 z-[71] flex max-h-[90dvh] flex-col rounded-t-xl border border-zoop-border font-panel text-zoop-ink shadow-xl outline-none ${dark ? 'bg-zoop-surface' : 'bg-white'}`}
      >
        <header className="flex items-center justify-between border-b border-zoop-border px-4 py-2">
          <h2 id={title} className="text-title-sm font-semibold">
            기업 전환
          </h2>
          <button
            type="button"
            aria-label="기업 전환 닫기"
            className="min-h-10 min-w-10 rounded-md border border-zoop-border focus-visible:outline-2 focus-visible:outline-offset-2"
            onClick={onClose}
          >
            ×
          </button>
        </header>
        <div
          className="min-h-0 overflow-y-auto"
          onClick={(e) => {
            if (e.target instanceof Element && e.target.closest('a[href]'))
              onClose();
          }}
        >
          {children}
        </div>
      </div>
    </div>,
    document.body,
  );
}
