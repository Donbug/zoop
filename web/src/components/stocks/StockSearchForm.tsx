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
      className="stocks-search"
      onSubmit={(event) => {
        event.preventDefault();
        onSearch(draft.trim());
      }}
    >
      <label htmlFor="stock-search">기업명·영문명·티커 검색</label>
      <div className="stocks-search-row">
        <div className="stocks-search-field">
          <GraphIcon name="search" size={15} />
          <input
            ref={input}
            id="stock-search"
            type="search"
            value={draft}
            disabled={disabled}
            placeholder="예: 삼성, NVIDIA, 005930"
            onChange={(event) => onDraftChange(event.target.value)}
          />
          {draft && (
            <button
              type="button"
              className="stocks-search-clear"
              aria-label="검색어 지우기"
              disabled={disabled}
              onClick={() => {
                onDraftChange('');
                input.current?.focus();
              }}
            >
              ×
            </button>
          )}
        </div>
        <button
          type="submit"
          className="stocks-search-button"
          disabled={disabled}
        >
          <GraphIcon name="search" size={14} />
          검색
        </button>
      </div>
    </form>
  );
}
