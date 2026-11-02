import { useRef } from 'react';
import GraphIcon from '@/components/graph/GraphIcon';

type StockSearchFormProps = {
  draft: string;
  onDraftChange: (value: string) => void;
  /** [검색]·Enter로만 검색한다(입력만으로는 조회하지 않음). */
  onSearch: (query: string) => void;
  disabled?: boolean;
};

// D-STK-01 검색: 기업명·영문명·티커. 빈 검색어로 검색하면 전체 목록으로 돌아간다.
export default function StockSearchForm({
  draft,
  onDraftChange,
  onSearch,
  disabled,
}: StockSearchFormProps) {
  const input = useRef<HTMLInputElement>(null);

  return (
    <form
      role="search"
      aria-label="종목 검색"
      className="mt-5"
      onSubmit={(event) => {
        event.preventDefault();
        onSearch(draft.trim());
      }}
    >
      <label
        htmlFor="stock-search"
        className="mb-2 block text-caption font-semibold text-zoop-ink"
      >
        기업명·영문명·티커 검색
      </label>
      <div className="flex gap-2">
        <div className="relative min-w-0 flex-1">
          <span className="pointer-events-none absolute top-1/2 left-3 -translate-y-1/2">
            <GraphIcon name="search" size={15} />
          </span>
          <input
            ref={input}
            id="stock-search"
            type="search"
            value={draft}
            disabled={disabled}
            placeholder="예: 삼성, NVIDIA, 005930"
            onChange={(event) => onDraftChange(event.target.value)}
            className="h-[46px] w-full rounded-[3px] border border-zoop-line bg-zoop-paper pr-[38px] pl-[34px] text-body text-zoop-ink outline-none transition-colors focus-visible:border-zoop-ink focus-visible:ring-1 focus-visible:ring-zoop-ink disabled:opacity-50 [&::-webkit-search-cancel-button]:hidden"
          />
          {draft && (
            <button
              type="button"
              aria-label="검색어 지우기"
              disabled={disabled}
              onClick={() => {
                onDraftChange('');
                input.current?.focus();
              }}
              className="absolute top-1/2 right-1.5 size-7 -translate-y-1/2 rounded-full text-lead text-zoop-muted hover:bg-zoop-soft"
            >
              ×
            </button>
          )}
        </div>
        <button
          type="submit"
          disabled={disabled}
          className="flex h-[46px] shrink-0 items-center gap-1.5 rounded-[3px] bg-zoop-ink px-4 text-body font-bold text-zoop-paper transition-opacity hover:opacity-85 disabled:opacity-50"
        >
          <GraphIcon name="search" size={14} />
          검색
        </button>
      </div>
    </form>
  );
}
