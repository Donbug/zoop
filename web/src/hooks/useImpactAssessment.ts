import { useEffect, useState } from 'react';
import { ApiError } from '@/apis/auth/ApiService';
import { getCompanyIssueImpactAssessment } from '@/apis/graph/impact-assessment';
import type { EventContext } from '@/types/map/event';
import type { CompanyIssueImpactAssessment } from '@/types/map/impact-assessment';

export function useImpactAssessment(
  companyId: string | null,
  issueId: string | null,
  enabled: boolean,
  context: EventContext = {},
) {
  const { round, graphVersion, asOf } = context;
  const key = JSON.stringify([
    companyId,
    issueId,
    enabled,
    round,
    graphVersion,
    asOf,
  ]);
  const [attempt, setAttempt] = useState(0);
  const [state, setState] = useState<{
    key: string;
    data: CompanyIssueImpactAssessment | null;
    loading: boolean;
    error: string | null;
    retryable: boolean;
  }>({ key: '', data: null, loading: false, error: null, retryable: false });

  useEffect(() => {
    if (!enabled || !companyId || !issueId) return;
    let active = true;
    void Promise.resolve().then(async () => {
      if (!active) return;
      setState({
        key,
        data: null,
        loading: true,
        error: null,
        retryable: false,
      });
      try {
        const data = await getCompanyIssueImpactAssessment(companyId, issueId, {
          round,
          graphVersion,
          asOf,
        });
        if (active)
          setState({
            key,
            data,
            loading: false,
            error: null,
            retryable: false,
          });
      } catch (error) {
        if (!active) return;
        const apiError = error instanceof ApiError ? error : null;
        setState({
          key,
          data: null,
          loading: false,
          error:
            error instanceof Error
              ? error.message
              : '영향 평가를 불러오지 못했습니다.',
          retryable: apiError
            ? apiError.status === 503 ||
              (apiError.retryable ?? apiError.status >= 500)
            : true,
        });
      }
    });
    return () => {
      active = false;
    };
  }, [attempt, companyId, issueId, enabled, key, round, graphVersion, asOf]);

  const current =
    state.key === key
      ? state
      : {
          key,
          data: null,
          loading: Boolean(enabled && companyId && issueId),
          error: null,
          retryable: false,
        };
  return { ...current, retry: () => setAttempt((value) => value + 1) };
}
