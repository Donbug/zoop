import type { BriefingResponse } from '@/types/briefing';

/** Keep original selection/versions together; never validate old prose against new items. */
export function preservedPublication(result: BriefingResponse) {
  const saved = result.preservedPublication;
  if (
    !saved ||
    !/^[a-f0-9]{64}$/.test(saved.sha256) ||
    saved.sha256 !== result.issueIntelligence?.baselineResponseSha256
  )
    return null;
  const original = saved.response;
  if (
    original.issueIntelligence ||
    original.id !== result.id ||
    original.date !== result.date ||
    original.edition !== result.edition ||
    original.dataAsOf !== result.dataAsOf
  )
    return null;
  return original;
}
