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

type Errors = Partial<Record<keyof CompanyPanelData, string>>;

export type CompanyDataState = {
  data: CompanyPanelData | null;
  /** 그래프 응답(기업·뉴스·공시)을 기다리는 중 */
  loading: boolean;
  /** 그 외 응답(시세·가격·지표·보유)을 기다리는 중 */
  marketLoading: boolean;
  errors: Errors;
  companyId?: string | null;
  contextKey?: string;
};

type Parts = {
  companyId: string | null;
  contextKey: string;
  data: Partial<CompanyPanelData>;
  errors: Errors;
  loading: boolean;
  marketLoading: boolean;
};

export function useCompanyData(
  companyId: string | null,
  token: string | null,
  retry = 0,
  context: EventContext = {},
): CompanyDataState {
  const { round, graphVersion, asOf } = context;
  const contextKey = JSON.stringify([round, graphVersion, asOf, token]);
  const [state, setState] = useState<Parts>({
    companyId: null,
    contextKey: '',
    data: {},
    errors: {},
    loading: false,
    marketLoading: false,
  });

  useEffect(() => {
    if (!companyId) return;
    let current = true;
    void Promise.resolve().then(() => {
      if (!current) return;
      setState({
        companyId,
        contextKey,
        data: {},
        errors: {},
        loading: true,
        marketLoading: true,
      });
      // 두 묶음은 따로 도착한다. 그래프 응답이 오면 패널을 먼저 그리고, 시세 공급자를 기다리지 않는다.
      const settle = (
        tasks: Partial<Record<keyof CompanyPanelData, Promise<unknown>>>,
        done: 'loading' | 'marketLoading',
      ) => {
        const keys = Object.keys(tasks) as (keyof CompanyPanelData)[];
        void Promise.allSettled(Object.values(tasks)).then((results) => {
          if (!current) return;
          const data: Partial<CompanyPanelData> = {};
          const errors: Errors = {};
          results.forEach((result, index) => {
            const key = keys[index];
            if (result.status === 'fulfilled') {
              data[key] = result.value as never;
            } else
              errors[key] =
                result.reason instanceof Error
                  ? result.reason.message
                  : '조회하지 못했습니다.';
          });
          setState((old) => ({
            ...old,
            data: { ...old.data, ...data },
            errors: { ...old.errors, ...errors },
            [done]: false,
          }));
        });
      };
      settle(
        {
          company: getCompany(companyId, { round, graphVersion, asOf }),
          documents: getCompanyDocuments(companyId, {
            round,
            graphVersion,
            asOf,
          }),
        },
        'loading',
      );
      settle(
        {
          quote: getCompanyQuote(companyId),
          metrics: getCompanyMetrics(companyId),
          prices: getCompanyPrices(companyId),
          holding: token
            ? getPortfolio().then((portfolio) =>
                portfolio.connected
                  ? (portfolio.holdings.find(
                      (item) => item.companyId === companyId,
                    ) ?? null)
                  : null,
              )
            : Promise.resolve(null),
        },
        'marketLoading',
      );
    });
    return () => {
      current = false;
    };
  }, [companyId, token, retry, round, graphVersion, asOf, contextKey]);

  if (!companyId)
    return {
      data: null,
      loading: false,
      marketLoading: false,
      errors: {},
      companyId: null,
    };
  if (state.companyId !== companyId || state.contextKey !== contextKey)
    return {
      data: null,
      loading: true,
      marketLoading: true,
      errors: {},
      companyId,
    };
  return {
    data:
      !state.loading && state.data.company
        ? (state.data as CompanyPanelData)
        : null,
    loading: state.loading,
    marketLoading: state.marketLoading,
    errors: state.errors,
    companyId,
    contextKey,
  };
}
