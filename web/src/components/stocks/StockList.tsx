import { Link } from 'react-router-dom';
import GraphIcon from '@/components/graph/GraphIcon';
import StockQuote from '@/components/stocks/StockQuote';
import type { CompanyBrief } from '@/types/company';

type StockListProps = {
  rows: CompanyBrief[];
  heldIds: ReadonlySet<string>;
  watchedIds: ReadonlySet<string>;
  /** 저장 중인 관심 변경의 기업 id */
  pendingId: string | null;
  /** 저장 중에는 다른 관심 변경을 막는다. */
  watchDisabled: boolean;
  onToggleWatch: (row: CompanyBrief) => void;
};

// D-STK-01 종목 행: 머리글자·이름·티커·승인 사건 수·보유, 최신 시세, 상세(↗)·지도·관심(☆)
export default function StockList({
  rows,
  heldIds,
  watchedIds,
  pendingId,
  watchDisabled,
  onToggleWatch,
}: StockListProps) {
  return (
    <ul aria-label="종목 목록" className="stocks-list">
      {rows.map((row) => {
        const encoded = encodeURIComponent(row.id);
        const watched = watchedIds.has(row.id);
        return (
          <li key={row.id} className="stocks-row">
            <span className="stocks-mark" aria-hidden="true">
              {row.name.slice(0, 1)}
            </span>
            <div className="stocks-identity">
              <p className="stocks-name">{row.name}</p>
              <p className="stocks-meta">
                {[row.ticker, `승인 사건 ${row.issueCount}건`]
                  .filter(Boolean)
                  .join(' · ')}
                {pendingId === row.id && ' · 저장 중'}
              </p>
              {heldIds.has(row.id) && (
                <span className="stocks-held">
                  <GraphIcon name="holding" size={10} />
                  보유
                </span>
              )}
            </div>
            <StockQuote companyId={row.id} />
            <Link
              to={`/companies/${encoded}`}
              aria-label={`${row.name} 기업 상세`}
              className="stocks-action"
            >
              ↗
            </Link>
            <Link
              to={`/?select=node:${encoded}`}
              aria-label={`${row.name} 지도에서 보기`}
              className="stocks-action"
            >
              <GraphIcon name="map" size={15} />
            </Link>
            <button
              type="button"
              className="stocks-action"
              aria-pressed={watched}
              aria-label={`${row.name} 관심 종목`}
              disabled={watchDisabled}
              onClick={() => onToggleWatch(row)}
            >
              {watched ? '★' : '☆'}
            </button>
          </li>
        );
      })}
    </ul>
  );
}
