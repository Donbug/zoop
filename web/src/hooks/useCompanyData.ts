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
  /** 도착한 응답부터 채운다. company·documents는 그래프 응답(각각 따로 도착), 나머지는 그 외 응답이다. */
  data: Partial<CompanyPanelData> | null;
  /** 그래프 응답 중 기업(관련 사건·관심)을 기다리는 중 */
  loading: boolean;
  /** 그래프 응답 중 뉴스·공시를 기다리는 중 */
  documentsLoading: boolean;
  /** 그 외 응답(시세·가격·지표·보유)을 기다리는 중 */
  marketLoading: boolean;
  errors: Errors;
  companyId?: string | null;
  contextKey?: string;
};

type Pending = 'loading' | 'documentsLoading' | 'marketLoading';

type Parts = {
  companyId: string | null;
  contextKey: string;
  data: Partial<CompanyPanelData>;
  errors: Errors;
} & Record<Pending, boolean>;

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
    documentsLoading: false,
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
        documentsLoading: true,
        marketLoading: true,
      });
      // 기업, 뉴스·공시, 그 외 응답은 각각 도착하는 대로 반영한다. 그래프 스냅샷 읽기가 느려도
      // 시세·지표·보유가 먼저 보이고, 뉴스·공시가 느려도 관련 사건·관심은 먼저 보인다.
      const settle = (
        tasks: Partial<Record<keyof CompanyPanelData, Promise<unknown>>>,
        done: Pending,
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
        { company: getCompany(companyId, { round, graphVersion, asOf }) },
        'loading',
      );
      settle(
        {
          documents: getCompanyDocuments(companyId, {
            round,
            graphVersion,
            asOf,
          }),
        },
        'documentsLoading',
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
      documentsLoading: false,
      marketLoading: false,
      errors: {},
      companyId: null,
    };
  if (state.companyId !== companyId || state.contextKey !== contextKey)
    return {
      data: null,
      loading: true,
      documentsLoading: true,
      marketLoading: true,
      errors: {},
      companyId,
    };
  return {
    data: state.data,
    loading: state.loading,
    documentsLoading: state.documentsLoading,
    marketLoading: state.marketLoading,
    errors: state.errors,
    companyId,
    contextKey,
  };
}
