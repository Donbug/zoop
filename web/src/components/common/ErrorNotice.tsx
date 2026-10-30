import type { ErrorNoticeProps } from '@/types/common';

/** 조회·저장 실패 안내. 실패한 영역 안에 두고 그 영역만 다시 시도한다. */
export default function ErrorNotice({
  title,
  message,
  onRetry,
  retryLabel = '다시 시도',
  retryDisabled,
}: ErrorNoticeProps) {
  return (
    <div
      role="alert"
      className="flex flex-wrap items-center gap-3 rounded-xl border border-red-200 bg-red-50 px-4 py-3"
    >
      <div className="min-w-0 flex-1">
        <p className="text-sm font-semibold text-red-700">{title}</p>
        {message && <p className="mt-0.5 text-sm text-zoop-ink">{message}</p>}
      </div>
      {onRetry && (
        <button
          type="button"
          onClick={onRetry}
          disabled={retryDisabled}
          className="shrink-0 rounded-lg border border-gray-300 bg-white px-3 py-1.5 text-sm font-medium text-zoop-ink hover:bg-gray-50 disabled:cursor-not-allowed disabled:opacity-50"
        >
          {retryLabel}
        </button>
      )}
    </div>
  );
}
