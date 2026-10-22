import { useEffect } from 'react';

/** Keep the real UI, but expose only the current tutorial action to input. */
export function useTutorialInteractionLock(
  step: number | null,
  zoomReady: boolean,
) {
  useEffect(() => {
    if (!step || step >= 5) return;
    const actions = new Set(['skip', 'retry']);
    if (step === 1) {
      actions.add('move');
      if (zoomReady) actions.add('zoom');
    }
    if (step === 2) {
      actions.add('move');
      actions.add('zoom');
    }
    if (step === 2 || step === 3) actions.add('node');
    if (step === 3) actions.add('issue');
    if (step === 4) actions.add('evidence');
    const allowed = (element: Element) =>
      actions.has(
        element
          .closest('[data-tutorial-action]')
          ?.getAttribute('data-tutorial-action') ?? '',
      );
    const saved = new Map<
      HTMLElement,
      { disabled: boolean | null; aria: string | null; tab: string | null }
    >();
    function apply() {
      document
        .querySelectorAll<HTMLElement>(
          'button,a[href],input,select,textarea,summary,[tabindex="0"]',
        )
        .forEach((element) => {
          if (allowed(element) || saved.has(element)) return;
          const native =
            'disabled' in element &&
            !element.hasAttribute('data-tutorial-managed-disabled');
          saved.set(element, {
            disabled: native
              ? Boolean((element as HTMLButtonElement).disabled)
              : null,
            aria: element.getAttribute('aria-disabled'),
            tab: element.getAttribute('tabindex'),
          });
          if (native) (element as HTMLButtonElement).disabled = true;
          element.setAttribute('aria-disabled', 'true');
          element.setAttribute('tabindex', '-1');
        });
    }
    function block(event: Event) {
      if (event instanceof KeyboardEvent && event.key === 'Tab') return;
      const target = event.target;
      if (!(target instanceof Element)) return;
      if (
        event.type === 'pointerdown' &&
        !target.closest(
          'button,a[href],input,select,textarea,summary,[tabindex]',
        )
      )
        return;
      if (
        event instanceof KeyboardEvent &&
        ![
          'Escape',
          'Enter',
          ' ',
          'ArrowUp',
          'ArrowDown',
          'ArrowLeft',
          'ArrowRight',
        ].includes(event.key)
      )
        return;
      if (
        (event instanceof KeyboardEvent && event.key === 'Escape') ||
        !allowed(target)
      ) {
        event.preventDefault();
        event.stopImmediatePropagation();
      }
    }
    apply();
    const observer = new MutationObserver(apply);
    observer.observe(document.body, { subtree: true, childList: true });
    const events = ['click', 'pointerdown', 'keydown'] as const;
    events.forEach((name) => document.addEventListener(name, block, true));
    return () => {
      observer.disconnect();
      events.forEach((name) => document.removeEventListener(name, block, true));
      saved.forEach((value, element) => {
        if (value.disabled !== null)
          (element as HTMLButtonElement).disabled = value.disabled;
        if (value.aria === null) element.removeAttribute('aria-disabled');
        else element.setAttribute('aria-disabled', value.aria);
        if (value.tab === null) element.removeAttribute('tabindex');
        else element.setAttribute('tabindex', value.tab);
      });
    };
  }, [step, zoomReady]);
}
