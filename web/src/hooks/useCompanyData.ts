import type { EventContext } from '@/types/map/event';
import { useEffect, useState } from 'react';
import {
  getCompany,
  getCompanyMetrics,
  getCompanyDocuments,
  getCompanyPrices,
  getCompanyQuote,
  getPortfolio,
} from '@/apis/graph/companies';
import type { CompanyPanelData } from '@/types/map/company';

export type CompanyDataState = {
  data: CompanyPanelData | null;
  loading: boolean;
  errors: Partial<Record<keyof CompanyPanelData, string>>;
  companyId?: string | null;
  contextKey?: string;
};

export function useCompanyData(
  companyId: string | null,
  token: string | null,
  retry = 0,
  context: EventContext = {},
): CompanyDataState {
  const { round, graphVersion, asOf } = context;
  const contextKey = JSON.stringify([round, graphVersion, asOf, token]);
  const [state, setState] = useState<CompanyDataState>({
    data: null,
    loading: false,
    errors: {},
  });

  useEffect(() => {
    if (!companyId) return;
    let current = true;
    void Promise.resolve().then(async () => {
      if (!current) return;
      setState({
        data: null,
        loading: true,
        errors: {},
        companyId,
        contextKey,
      });
      const tasks = {
        company: getCompany(companyId, { round, graphVersion, asOf }),
        quote: getCompanyQuote(companyId),
        metrics: getCompanyMetrics(companyId),
        prices: getCompanyPrices(companyId),
        documents: getCompanyDocuments(companyId, {
          round,
          graphVersion,
          asOf,
        }),
        holding: token
          ? getPortfolio().then(
              (portfolio) =>
                portfolio.holdings.find(
                  (item) => item.companyId === companyId,
                ) ?? null,
            )
          : Promise.resolve(null),
      };
      const results = await Promise.allSettled(Object.values(tasks));
      if (!current) return;
      const keys = Object.keys(tasks) as (keyof CompanyPanelData)[];
      const data = {} as Partial<CompanyPanelData>;
      const errors: CompanyDataState['errors'] = {};
      results.forEach((result, index) => {
        const key = keys[index];
        if (result.status === 'fulfilled') data[key] = result.value as never;
        else
          errors[key] =
            result.reason instanceof Error
              ? result.reason.message
              : '조회하지 못했습니다.';
      });
      setState({
        data: data.company ? (data as CompanyPanelData) : null,
        loading: false,
        errors,
        companyId,
        contextKey,
      });
    });
    return () => {
      current = false;
    };
  }, [companyId, token, retry, round, graphVersion, asOf, contextKey]);

  if (!companyId)
    return { data: null, loading: false, errors: {}, companyId: null };
  return state.companyId === companyId && state.contextKey === contextKey
    ? state
    : { data: null, loading: true, errors: {}, companyId };
}
