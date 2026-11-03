import { useEffect, useState } from 'react';
import { useLocation } from 'react-router-dom';

function mapUrl(value: unknown): string | null {
  if (
    typeof value !== 'string' ||
    !(value === '/' || value.startsWith('/?') || value.startsWith('/#'))
  )
    return null;
  try {
    const url = new URL(value, 'https://zoop.invalid');
    return url.origin === 'https://zoop.invalid' && url.pathname === '/'
      ? value
      : null;
  } catch {
    return null;
  }
}

/** D-COM-01 D7: 진입 지도만 이력·회원·기업에 묶어 기억한다. */
export function useCompanyMapEntry(scope: string) {
  const location = useLocation();
  const key = `zoop.company.map-entry:${scope}:${location.key}`;
  let stored: { url: string | null } | null = null;
  try {
    const value = sessionStorage.getItem(key);
    if (value !== null) stored = { url: mapUrl(JSON.parse(value)) };
  } catch {
    /* storage unavailable: current navigation still works */
  }
  const from: unknown = location.state?.from;
  const [entryOwner] = useState(scope);
  const entered =
    entryOwner === scope
      ? mapUrl(
          typeof from === 'object' &&
            from !== null &&
            'pathname' in from &&
            from.pathname === '/' &&
            'search' in from &&
            typeof from.search === 'string' &&
            (!from.search || from.search.startsWith('?'))
            ? `/${from.search}`
            : from,
        )
      : null;
  const [remembered, setRemembered] = useState({
    scope,
    url: entered ?? stored?.url ?? null,
  });
  const url =
    entered ??
    (stored ? stored.url : remembered.scope === scope ? remembered.url : null);
  if (remembered.scope !== scope || remembered.url !== url)
    setRemembered({ scope, url });
  useEffect(() => {
    try {
      sessionStorage.setItem(key, JSON.stringify(url));
    } catch {
      /* optional persistence */
    }
  }, [key, url]);
  return url;
}
