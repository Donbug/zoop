import { useRouteQuery } from './useRouteQuery';
import type { GraphTarget, MapMode, PersonalScope } from '@/types/map';

export function useGraphQuery() {
  const { params, updateQuery } = useRouteQuery();
  const mode: MapMode = params.get('mode') === 'personal' ? 'personal' : 'all';
  const rawScope = params.get('scope');
  const scope: PersonalScope =
    rawScope === 'holdings' || rawScope === 'watchlist' ? rawScope : 'all';
  const select = params.get('select');
  const id = params.get('id');
  const target: GraphTarget | null =
    id && (select === 'company' || select === 'issue' || select === 'edge')
      ? { kind: select, id }
      : null;
  return {
    params,
    updateQuery,
    mode,
    scope,
    target,
    roundId: params.get('round'),
    focusId: params.get('focus'),
    hops: params.get('hops') === '2' ? 2 : 1,
  };
}
