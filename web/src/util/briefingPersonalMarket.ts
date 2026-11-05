import type { BriefingResponse } from '@/types/briefing';
import { sameBriefingInstant } from './briefingTime';

/** D-BRF-01/02. A read projection only; neither frozen delivery is mutated. */
export function withRoundMarket(
  personal: BriefingResponse,
  common: BriefingResponse,
): BriefingResponse {
  if (
    personal.marketVariables?.status === 'available' ||
    common.status !== 'published' ||
    !common.publishedAt ||
    personal.status !== 'published' ||
    personal.id !== common.id ||
    personal.date !== common.date ||
    personal.edition !== common.edition ||
    !sameBriefingInstant(personal.dataAsOf, common.dataAsOf) ||
    !sameBriefingInstant(personal.scheduledAt, common.scheduledAt) ||
    common.marketVariables?.status !== 'available' ||
    !sameBriefingInstant(common.marketVariables.referenceAt, common.dataAsOf) ||
    common.corrections.length !== 0
  )
    return personal;
  return { ...personal, marketVariables: common.marketVariables };
}
