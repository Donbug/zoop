/**
 * Invisible 44px hit area for small controls (WCAG 2.5.5 / Impeccable touch target).
 * The control keeps its visible size; a centered ::after box takes taps around it.
 * Do not use on an element with overflow hidden (the box would be clipped) or
 * where the box would cover a neighbouring control.
 */
export const touchTarget =
  "relative after:absolute after:top-1/2 after:left-1/2 after:h-[max(100%,2.75rem)] after:w-[max(100%,2.75rem)] after:-translate-1/2 after:content-['']";
