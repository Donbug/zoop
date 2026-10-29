import type { BriefingItem, BriefingResponse } from '@/types/briefing';
import type { CompanyStatement } from '@/types/briefing/companyOutlook';
import { validEditionReview } from './editionReview';
import { validAiPriceOutlooks } from './aiPriceOutlook';

/** A historical company judgment is not evidence of continuity between events. */
export function issuePrevious(
  current: BriefingResponse,
  previous: BriefingResponse | undefined,
  item: BriefingItem,
  companyId: string,
) {
  const ref = validEditionReview(current)?.previousReview;
  if (
    !ref ||
    !previous ||
    previous.id !== ref.roundId ||
    previous.status !== 'published'
  )
    return undefined;
  const review = validEditionReview(previous);
  if (
    !review ||
    review.resultVersion !== ref.resultVersion ||
    review.cutoff !== ref.cutoff ||
    !(Date.parse(review.cutoff) < Date.parse(current.dataAsOf ?? '')) ||
    (current.edition === 'evening'
      ? previous.date !== current.date || previous.edition !== 'morning'
      : previous.date >= current.date || previous.edition !== 'evening')
  )
    return undefined;
  const before = previous.items.find(
    (i) =>
      i.eventId === item.eventId && i.companies.some((c) => c.id === companyId),
  );
  const company = review.companies.find((c) => c.companyId === companyId);
  if (!before || !company) return undefined;
  const unique = before.evidenceIds.filter(
    (id) =>
      !previous.items.some(
        (i) => i.eventId !== before.eventId && i.evidenceIds.includes(id),
      ),
  );
  const foreign = new Set(
    previous.items
      .filter((i) => i.eventId !== before.eventId)
      .flatMap((i) => i.evidenceIds)
      .filter((id) => !before.evidenceIds.includes(id)),
  );
  const anchored = (s?: CompanyStatement): s is CompanyStatement =>
    Boolean(
      s?.text.trim() &&
      s.evidenceIds.some((id) => unique.includes(id)) &&
      s.evidenceIds.every(
        (id) =>
          company.sourceIds.includes(id) &&
          review.sources[id] &&
          !foreign.has(id),
      ),
    );
  const ai = validAiPriceOutlooks(previous);
  const generated =
    ai?.status === 'PASS'
      ? ai.companies.find((c) => c.companyId === companyId)
      : undefined;
  if (anchored(generated?.outlook))
    return {
      judgment: generated.outlook,
      resultVersion: ai!.resultVersion,
      roundId: previous.id,
      kind: 'verified_ai_price_outlook',
    };
  if (anchored(company.judgment))
    return {
      judgment: company.judgment,
      resultVersion: review.resultVersion,
      roundId: previous.id,
      kind: 'preserved_editorial_review',
    };
  return undefined;
}
