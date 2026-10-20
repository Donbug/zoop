import { Link } from 'react-router-dom';
import GraphIcon from '@/components/graph/GraphIcon';
import StockQuote from '@/components/stocks/StockQuote';
import CompanyLogo from '@/components/common/CompanyLogo';
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

const action =
  'grid size-8 shrink-0 place-items-center rounded-[3px] text-sm text-zoop-muted no-underline hover:bg-zoop-soft hover:text-zoop-ink disabled:cursor-default disabled:opacity-45 aria-pressed:border-[0.667px] aria-pressed:border-zoop-ink aria-pressed:text-zoop-ink';

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
    <ul aria-label="종목 목록" className="border-t-[0.667px] border-zoop-line">
      {rows.map((row) => {
        const encoded = encodeURIComponent(row.id);
        const watched = watchedIds.has(row.id);
        return (
          <li
            key={row.id}
            className="flex items-center gap-3 border-b-[0.667px] border-zoop-line px-2 py-3.5 max-md:flex-wrap max-md:gap-2.5 max-md:px-0 max-md:py-3"
          >
            <CompanyLogo
              name={row.name}
              logoUrl={row.logoUrl}
              className="size-8 rounded-full bg-zoop-ink text-xs font-bold text-zoop-paper"
            />
            <div className="min-w-0 flex-1">
              <p className="truncate text-[13px] font-bold text-zoop-ink">
                {row.name}
              </p>
              <p className="mt-[3px] font-inter text-[11px] text-zoop-muted">
                {[
                  row.ticker,
                  row.issueCount === null
                    ? '사건 수 미제공'
                    : `승인 사건 ${row.issueCount}건`,
                ]
                  .filter(Boolean)
                  .join(' · ')}
                {pendingId === row.id && ' · 저장 중'}
              </p>
              {heldIds.has(row.id) && (
                <span className="mt-1 inline-flex items-center gap-1 text-[10px] font-semibold text-zoop-muted">
                  <GraphIcon name="holding" size={10} />
                  보유
                </span>
              )}
            </div>
            <StockQuote companyId={row.id} />
            <Link
              to={`/companies/${encoded}`}
              aria-label={`${row.name} 기업 상세`}
              className={action}
            >
              ↗
            </Link>
            <Link
              to={`/?select=node:${encoded}`}
              aria-label={`${row.name} 지도에서 보기`}
              className={action}
            >
              <GraphIcon name="map" size={15} />
            </Link>
            <button
              type="button"
              aria-pressed={watched}
              aria-label={`${row.name} 관심 종목`}
              disabled={watchDisabled}
              onClick={() => onToggleWatch(row)}
              className={action}
            >
              {watched ? '★' : '☆'}
            </button>
          </li>
        );
      })}
    </ul>
  );
}
