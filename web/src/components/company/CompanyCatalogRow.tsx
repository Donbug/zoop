import { Link } from 'react-router-dom';
import { useCompanyResource } from '@/hooks/useCompanyResource';
import StockQuote from '@/components/stocks/StockQuote';
import type { Company } from '@/types/company/detail';

export type CatalogCompany = {
  id: string;
  name: string;
  ticker: string | null;
  logoUrl?: string | null;
};

export default function CompanyCatalogRow({
  id,
  company,
  selected,
  to,
  quote = true,
}: {
  id: string;
  company?: CatalogCompany;
  selected: boolean;
  to: string;
  quote?: boolean;
}) {
  const detail = useCompanyResource<Company>(
    company ? null : `/api/v1/companies/${encodeURIComponent(id)}`,
  );
  const row = company ?? detail.data;
  return (
    <Link
      to={to}
      aria-current={selected ? 'page' : undefined}
      className={`flex! min-w-0 items-center gap-2 rounded-[3px] border p-2! no-underline ${selected ? 'border-zoop-ink bg-white' : 'border-transparent hover:bg-white'}`}
    >
      <span className="grid size-7 shrink-0 place-items-center overflow-hidden rounded-full border border-zoop-muted bg-white text-[10px] font-bold">
        {company?.logoUrl ? (
          <img src={company.logoUrl} alt="" className="size-5 object-contain" />
        ) : (
          (row?.name ?? id).slice(0, 1)
        )}
      </span>
      <span className="min-w-0 flex-1">
        <strong className="block truncate text-[11px] font-semibold text-zoop-ink">
          {row?.name ?? id}
        </strong>
        {quote ? (
          <span className="block [&_span]:min-w-0 [&_span]:flex-row [&_span]:flex-wrap [&_span]:items-baseline [&_span]:justify-start [&_span]:gap-1 [&_strong]:text-[10px]">
            <StockQuote companyId={id} />
          </span>
        ) : (
          <small className="block text-[10px] text-zoop-muted">
            {row?.ticker ?? (detail.loading ? '확인 중…' : '코드 미제공')}
          </small>
        )}
        {detail.error && (
          <span className="text-[10px] text-zoop-muted">
            기업 정보 확인 실패
          </span>
        )}
      </span>
    </Link>
  );
}
