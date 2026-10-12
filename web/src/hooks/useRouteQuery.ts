import { useSearchParams } from 'react-router-dom';
import type { QueryChanges, QueryUpdateOptions } from '@/types/common';

export function useRouteQuery() {
  const [params, setParams] = useSearchParams();

  function updateQuery(
    changes: QueryChanges,
    options: QueryUpdateOptions = {},
  ) {
    setParams((previous) => {
      const next = new URLSearchParams(previous);
      Object.entries(changes).forEach(([key, value]) => {
        if (value === null || value === '') next.delete(key);
        else next.set(key, value);
      });
      return next;
    }, options);
  }

  return { params, updateQuery };
}
