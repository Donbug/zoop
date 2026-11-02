import { companyUrl } from '@/apis/company/company';
import { timeRange } from '@/components/company/detail-model';
import type { Prices } from '@/types/company/detail';
import { useCompanyResource } from './useCompanyResource';

/** D-COM-01 D12: 기업·기준 시점별 두 짧은 기간만 확인하고 선택 시에도 재사용한다. */
export function useCompanyShortPrices(
  id: string,
  asOf: string | null,
  enabled: boolean,
) {
  const url = (period: '1d' | '1w') =>
    enabled && asOf
      ? companyUrl(id, '/prices', { period, ...timeRange(asOf, period) })
      : null;
  const day = useCompanyResource<Prices>(url('1d'));
  const week = useCompanyResource<Prices>(url('1w'));
  return { '1d': day, '1w': week };
}
