/** FS044 · D-GRP-03 / D-COM-03 / M-COM-01: carry the map's company context into detail. */
export function companyDetailRouteFromMap(
  companyId: string,
  mapSearch: string,
): string {
  const map = new URLSearchParams(mapSearch);
  const path = `/companies/${encodeURIComponent(companyId)}`;
  const returnTo = map.get('returnTo');
  if (returnTo?.split('?')[0] === path) return returnTo;

  const detail = new URLSearchParams();
  for (const key of [
    'period',
    'tab',
    'asOf',
    'graphVersion',
    'depth',
  ] as const) {
    const value = map.get(key);
    if (
      value &&
      (key !== 'graphVersion' || map.get('asOf')) &&
      (key !== 'depth' || value === '1' || value === '2')
    )
      detail.set(key, value);
  }
  return detail.size ? `${path}?${detail}` : path;
}
