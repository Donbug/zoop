import { companyUrl } from '@/apis/company/company';
import { timeRange } from '@/components/company/detail-model';
import type { Prices } from '@/types/company/detail';
import { useCompanyResource } from './useCompanyResource';
import { useState } from 'react';

/** D-COM-01 D12: 기업·기준 시점별 두 짧은 기간만 확인하고 선택 시에도 재사용한다. */
export function useCompanyShortPrices(
  id: string,
  asOf: string | null,
  enabled: boolean,
) {
  const key = `${id}|${asOf ?? ''}`;
  const [started, setStarted] = useState<string | null>(null);
  if (enabled && asOf && started !== key) setStarted(key);
  // 공개 시세는 회원·폼 상태와 무관하다. 일시적인 parent gate 변경으로 같은 조회를 반복하지 않는다.
  const active = enabled || started === key;
  const url = (period: '1d' | '1w') =>
    active && asOf
      ? companyUrl(id, '/prices', { period, ...timeRange(asOf, period) })
      : null;
  const day = useCompanyResource<Prices>(url('1d'));
  const week = useCompanyResource<Prices>(url('1w'));
  const hidden = {
    data: null,
    loading: false,
    error: null,
    errorCode: null,
    errorStatus: null,
    errorRetryable: null,
  };
  return enabled
    ? { '1d': day, '1w': week }
    : { '1d': { ...day, ...hidden }, '1w': { ...week, ...hidden } };
}
