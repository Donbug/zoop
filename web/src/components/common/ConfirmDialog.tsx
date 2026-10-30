import { useEffect, useId } from 'react';
import type { ConfirmDialogProps } from '@/types/common';

/** 되돌리기 어려운 행동을 한 번 더 확인하는 창. 처리 중에는 닫지 않는다. */
export default function ConfirmDialog({
  title,
  children,
  confirmLabel,
  cancelLabel = '닫기',
  pending = false,
  onConfirm,
  onCancel,
}: ConfirmDialogProps) {
  const titleId = useId();

  useEffect(() => {
    const onKeyDown = (event: KeyboardEvent) => {
      if (event.key === 'Escape' && !pending) onCancel();
    };
    window.addEventListener('keydown', onKeyDown);
    return () => window.removeEventListener('keydown', onKeyDown);
  }, [pending, onCancel]);

  return (
    <div className="fixed inset-0 z-[70] flex items-end justify-center bg-black/40 p-4 md:items-center">
      <div
        role="dialog"
        aria-modal="true"
        aria-labelledby={titleId}
        className="flex w-full max-w-md flex-col gap-4 rounded-xl bg-white p-5 shadow-lg"
      >
        <h2 id={titleId} className="text-lg font-semibold text-zoop-ink">
          {title}
        </h2>
        {children}
        <div className="flex justify-end gap-2">
          <button
            type="button"
            autoFocus
            disabled={pending}
            onClick={onCancel}
            className="rounded-lg border border-gray-300 px-4 py-2 text-sm font-medium text-zoop-ink hover:bg-gray-50 disabled:cursor-not-allowed disabled:opacity-50"
          >
            {cancelLabel}
          </button>
          <button
            type="button"
            disabled={pending}
            onClick={onConfirm}
            className="rounded-lg bg-gray-950 px-4 py-2 text-sm font-semibold text-white hover:bg-gray-800 disabled:cursor-not-allowed disabled:bg-gray-300"
          >
            {confirmLabel}
          </button>
        </div>
      </div>
    </div>
  );
}
