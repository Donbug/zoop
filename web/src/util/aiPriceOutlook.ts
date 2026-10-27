import type { BriefingResponse } from '@/types/briefing';
import type { CompanyStatement } from '@/types/briefing/companyOutlook';
import { validPriceContext } from './briefingPriceContext';

/** D-BRF-01/02: a stale or foreign-company model result cannot replace the saved review. */
export function validAiPriceOutlooks(result: BriefingResponse) {
  try {
    const a = result.aiPriceOutlooks,
      r = result.editionReview,
      p = validPriceContext(result);
    if (
      !a ||
      !r ||
      !p ||
      a.schemaVersion !== 'zoop-ai-price-outlooks-v1' ||
      a.model !== 'gpt-6-luna' ||
      a.promptVersion !== 'company-outlook-v5' ||
      a.verificationMode !== 'independent_model' ||
      a.roundId !== result.id ||
      a.date !== r.date ||
      a.edition !== r.edition ||
      a.cutoff !== r.cutoff ||
      a.reviewVersion !== r.resultVersion ||
      a.priceContextVersion !== p.resultVersion
    )
      return null;
    if (a.status === 'WITHHELD') return a.companies.length === 0 ? a : null;
    if (
      a.status !== 'PASS' ||
      !/^[a-f0-9]{64}$/.test(a.projectionSha256 ?? '') ||
      !/^[a-f0-9]{64}$/.test(a.generationRequestDigest ?? '') ||
      !/^[a-f0-9]{64}$/.test(a.verificationRequestDigest ?? '') ||
      a.companies.length !== r.companies.length ||
      new Set(a.companies.map((c) => c.companyId)).size !== a.companies.length
    )
      return null;
    for (const c of a.companies) {
      const own = r.companies.find((x) => x.companyId === c.companyId);
      if (
        !own ||
        own.companyName !== c.companyName ||
        own.role !== c.role ||
        !['positive', 'negative', 'mixed', 'watch'].includes(c.assessment)
      )
        return null;
      const valid = (s: CompanyStatement) =>
        s.text.trim().length > 0 &&
        [...s.text].length <= 420 &&
        s.evidenceIds.length > 0 &&
        s.evidenceIds.length <= 6 &&
        new Set(s.evidenceIds).size === s.evidenceIds.length &&
        s.evidenceIds.every(
          (id) => own.sourceIds.includes(id) && r.sources[id],
        );
      if (
        ![c.impact, c.outlook, c.comparison, ...c.conditions, ...c.risks].every(
          valid,
        ) ||
        c.conditions.length < 1 ||
        c.conditions.length > 3 ||
        c.risks.length < 1 ||
        c.risks.length > 3 ||
        c.comparison.previousResultVersion !==
          (c.previous.resultVersion ?? null) ||
        c.comparison.status !==
          (c.previous.status === 'available'
            ? a.edition === 'morning'
              ? 'updated'
              : 'compared'
            : 'unavailable')
      )
        return null;
    }
    return a;
  } catch {
    return null;
  }
}
