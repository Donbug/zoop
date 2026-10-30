import { Link } from 'react-router-dom';
import CompanyMark from '@/components/stocks/CompanyMark';
import type { StockRowProps } from '@/types/my';

/** 내 종목 행: 누르면 그 기업을 고른 내 종목 지도, ↗는 기업 상세 */
export default function StockRow({
  id,
  name,
  logoUrl,
  description,
  trailing,
  action,
}: StockRowProps) {
  const encoded = encodeURIComponent(id);
  return (
    <li className="flex items-center gap-2 py-3">
      <Link
        to={`/?mode=personal&select=node:${encoded}`}
        aria-label={`${name}, 지도에서 보기`}
        className="flex min-w-0 flex-1 items-center gap-3 rounded-lg hover:bg-gray-50"
      >
        <CompanyMark name={name} logoUrl={logoUrl} />
        <span className="min-w-0 flex-1">
          <span className="block truncate font-medium text-zoop-ink">
            {name}
          </span>
          {description && (
            <span className="block text-body text-zoop-ink">{description}</span>
          )}
        </span>
        {trailing && (
          <span className="shrink-0 text-body text-zoop-ink tabular-nums">
            {trailing}
          </span>
        )}
      </Link>
      <Link
        to={`/companies/${encoded}`}
        aria-label={`${name} 기업 상세`}
        className="flex size-9 shrink-0 items-center justify-center rounded-lg text-zoop-ink hover:bg-gray-100 hover:text-zoop-ink"
      >
        ↗
      </Link>
      {action}
    </li>
  );
}
