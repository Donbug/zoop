import { useEffect, useState } from 'react';
import { readCompanyResource } from '@/apis/company/company';
export type Resource<T> = {
  data: T | null;
  loading: boolean;
  error: string | null;
  retry: () => void;
};
export function useCompanyResource<T>(
  url: string | null,
  owner = '',
  paged = false,
): Resource<T> {
  const key = `${owner}|${url}`;
  const [attempt, setAttempt] = useState(0);
  const [state, setState] = useState({
    key: '',
    data: null as T | null,
    loading: true,
    error: null as string | null,
  });
  useEffect(() => {
    let active = true;
    void Promise.resolve().then(async () => {
      if (!active || !url) return;
      setState({ key, data: null, loading: true, error: null });
      try {
        const data = await readCompanyResource<T>(url, paged);
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
                : '자료를 불러오지 못했어요.',
          });
      }
    });
    return () => {
      active = false;
    };
  }, [key, url, attempt, paged]);
  const current =
    state.key === key ? state : { data: null, loading: !!url, error: null };
  return {
    ...current,
    loading: !!url && current.loading,
    data: url ? current.data : null,
    error: url ? current.error : null,
    retry: () => setAttempt((a) => a + 1),
  };
}
