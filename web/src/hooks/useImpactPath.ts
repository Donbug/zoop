import type { EventContext } from '@/types/map/event';
import { useEffect, useState } from 'react';
import { getCompanyIssueImpact } from '@/apis/graph/impact';
import type { Impact } from '@/types/company/detail';

export function useImpactPath(
  companyId: string | null,
  issueId: string | null,
  context: EventContext = {},
) {
  const { round, asOf, graphVersion } = context;
  const snapshotKey = JSON.stringify([round, asOf, graphVersion]);
  const key =
    companyId && issueId ? `${companyId}|${issueId}|${snapshotKey}` : '';
  const [attempt, setAttempt] = useState(0);
  const [state, setState] = useState<{
    key: string;
    data: Impact | null;
    loading: boolean;
    error: string | null;
  }>({ key: '', data: null, loading: false, error: null });

  useEffect(() => {
    if (!companyId || !issueId) return;
    let active = true;
    void Promise.resolve().then(async () => {
      if (!active) return;
      setState({ key, data: null, loading: true, error: null });
      try {
        const data = await getCompanyIssueImpact(companyId, issueId, {
          round,
          asOf,
          graphVersion,
        });
        if (active) setState({ key, data, loading: false, error: null });
      } catch (error) {
        if (active)
          setState({
            key,
            data: null,
            loading: false,
            error:
              error instanceof Error
                ? error.message
                : '영향 경로를 불러오지 못했습니다.',
          });
      }
    });
    return () => {
      active = false;
    };
  }, [attempt, companyId, issueId, key, round, asOf, graphVersion]);

  const current =
    state.key === key
      ? state
      : { key, data: null, loading: Boolean(key), error: null };
  return {
    ...current,
    retry: () => setAttempt((value) => value + 1),
  };
}
