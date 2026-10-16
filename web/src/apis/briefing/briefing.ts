import { call } from '@/apis/auth/ApiService';
import type { BriefingEdition, BriefingResponse } from '@/types/briefing';

// D-BRF-01 / FS033: omitted date requests the latest selected edition.
export function getBriefing(date: string, edition: BriefingEdition) {
  const query = new URLSearchParams({ edition });
  if (date) query.set('date', date);
  return call<BriefingResponse>(
    `/api/v1/briefings?${query}`,
    'GET',
    undefined,
    { skipAuth: true },
  );
}
