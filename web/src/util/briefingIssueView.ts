import type { BriefingItem, BriefingResponse } from '@/types/briefing';
import type { CompanyStatement } from '@/types/briefing/companyOutlook';
import { validAiPriceOutlooks } from './aiPriceOutlook';
import { validEditionReview } from './editionReview';
import { validPriceContext } from './briefingPriceContext';

/** A company is never the selection key. Each statement must actually cite this issue.
 * A company-wide judgment citing another selected issue cannot be cloned across cards.
 * Nonselected background sources remain identified as context, not S3 impact verdicts.
 */
export function briefingIssueViews(
  result: BriefingResponse,
  items = result.items,
) {
  const review = validEditionReview(result);
  const prices = validPriceContext(result);
  const ai = validAiPriceOutlooks(result);
  const owners = new Map<string, Set<string>>();
  for (const issue of result.items)
    for (const id of issue.evidenceIds) {
      if (!owners.has(id)) owners.set(id, new Set());
      owners.get(id)!.add(issue.eventId);
    }
  return [...items]
    .sort((a, b) => a.rank - b.rank)
    .slice(0, 3)
    .map((item) => {
      const own = new Set(item.evidenceIds);
      const other = new Set(
        result.items
          .filter((x) => x.eventId !== item.eventId)
          .flatMap((x) => x.evidenceIds)
          .filter((id) => !own.has(id)),
      );
      return {
        item,
        companies: item.companies.map((company) => {
          const original = review?.companies.find(
            (c) => c.companyId === company.id,
          );
          const generated =
            ai?.status === 'PASS'
              ? ai.companies.find((c) => c.companyId === company.id)
              : undefined;
          const anchored = (s?: CompanyStatement): s is CompanyStatement =>
            Boolean(
              original &&
              s?.text.trim() &&
              s.evidenceIds.length &&
              new Set(s.evidenceIds).size === s.evidenceIds.length &&
              s.evidenceIds.some(
                (id) => own.has(id) && owners.get(id)?.size === 1,
              ) &&
              s.evidenceIds.every(
                (id) =>
                  original.sourceIds.includes(id) &&
                  review?.sources[id] &&
                  !other.has(id),
              ),
            );
          const impact = anchored(generated?.impact)
            ? generated!.impact
            : undefined;
          const outlook = anchored(generated?.outlook)
            ? generated!.outlook
            : undefined;
          const comparison = anchored(generated?.comparison)
            ? generated!.comparison
            : undefined;
          const conditions =
            generated?.conditions.filter(anchored) ??
            original?.watch.filter(anchored) ??
            [];
          const risks = generated?.risks.filter(anchored) ?? [];
          const refs = [
            ...new Set(
              [impact, outlook, comparison, ...conditions, ...risks].flatMap(
                (s) => s?.evidenceIds ?? [],
              ),
            ),
          ].flatMap((id) =>
            review?.sources[id] ? [{ id, ...review.sources[id] }] : [],
          );
          const price = prices?.companies.find(
            (c) => c.companyId === company.id,
          );
          return {
            company,
            impact,
            outlook,
            comparison,
            conditions,
            risks,
            refs,
            // This is an existing source-bound company judgment, never an invented
            // per-issue S3 verifier verdict or share-price probability.
            assessment: impact ? generated?.assessment : undefined,
            price,
            news:
              price?.status === 'available'
                ? price.news.filter((n) => own.has(n.evidenceId))
                : [],
          };
        }),
      };
    });
}

export type BriefingIssueView = ReturnType<typeof briefingIssueViews>[number];
export function issueAnchor(item: Pick<BriefingItem, 'eventId'>) {
  return 'briefing-issue-' + encodeURIComponent(item.eventId);
}
