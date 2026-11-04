import { prioritySourceAvailable } from './briefingSourceTime';
import { sameBriefingInstant } from './briefingTime';
import type { BriefingResponse } from '@/types/briefing';
import { safeArticleUrl } from '@/components/graph/event-format';
import type { BriefingBusinessAnalysis } from './briefingPersonalPriority';

export type CommonPriority = {
  schemaVersion: 'common-relative-priority-view-v1';
  roundId: string;
  cutoff: string;
  resultVersion: string;
  generationVersion?: string;
  minimumIssues: number;
  minimumShortfall: number;
  candidateCount: number;
  legacyAnalysisScopeWarning?: boolean;
  status: 'available' | 'collection_insufficient';
  items: {
    issueId: string;
    kind: 'core' | 'relative_issue' | 'related_reference' | 'previous_issue';
    importance: number;
    title: string;
    topicTag?: string;
    analysisResultVersion?: string;
    aiAnalyses?: BriefingBusinessAnalysis[];
    analysisWithheldReason?: string;
    reason: string;
    whyNow: string;
    originRoundId: string;
    originCutoff: string;
    companies: { companyId: string; name: string; reason: string }[];
    sources: {
      evidenceId: string;
      quote: string;
      url: string;
      publishedAt: string | null;
      publishedDate?: string | null;
      availableAt?: string | null;
      eligibilityBasis?: string | null;
      title?: string;
      publisher?: string;
    }[];
    prices: {
      companyName: string;
      baseline: string;
      latest: string;
      changeRate: string;
      currency: string;
      observedAt: string;
    }[];
  }[];
};

export function commonPriorityOf(
  result: BriefingResponse,
): CommonPriority | null {
  try {
    return validateCommonPriority(result);
  } catch {
    return null;
  }
}

function validateCommonPriority(
  result: BriefingResponse,
): CommonPriority | null {
  const value = (
    result as BriefingResponse & { commonPriority?: CommonPriority }
  ).commonPriority;
  if (
    !value ||
    value.schemaVersion !== 'common-relative-priority-view-v1' ||
    value.roundId !== result.id ||
    !sameBriefingInstant(value.cutoff, result.dataAsOf) ||
    !value.resultVersion ||
    !Array.isArray(value.items) ||
    value.items.length > 3 ||
    !Number.isInteger(value.minimumIssues) ||
    value.minimumIssues < 1 ||
    value.minimumIssues > 3 ||
    value.minimumShortfall !==
      Math.max(0, value.minimumIssues - value.items.length) ||
    !['available', 'collection_insufficient'].includes(value.status)
  )
    return null;
  const cutoff = Date.parse(value.cutoff);
  if (!Number.isFinite(cutoff)) return null;
  const seen = new Set<string>();
  for (const item of value.items) {
    if (
      !item ||
      !item.issueId ||
      seen.has(item.issueId) ||
      !item.title ||
      !item.reason ||
      !item.whyNow ||
      ![
        'core',
        'relative_issue',
        'related_reference',
        'previous_issue',
      ].includes(item.kind) ||
      !Number.isInteger(item.importance) ||
      item.importance < 0 ||
      item.importance > 3 ||
      !item.originRoundId ||
      !Number.isFinite(Date.parse(item.originCutoff)) ||
      Date.parse(item.originCutoff) > cutoff ||
      !Array.isArray(item.companies) ||
      !item.companies.length ||
      item.companies.some((c) => !c.companyId || !c.name || !c.reason) ||
      !Array.isArray(item.sources) ||
      !item.sources.length ||
      item.sources.some(
        (s) =>
          !s.evidenceId ||
          !s.quote ||
          !safeArticleUrl(s.url) ||
          !Number.isFinite(prioritySourceAvailable(s)) ||
          prioritySourceAvailable(s) > cutoff ||
          (item.kind === 'previous_issue' &&
            prioritySourceAvailable(s) > Date.parse(item.originCutoff)),
      ) ||
      !Array.isArray(item.prices) ||
      item.prices.some(
        (p) =>
          !p.companyName ||
          !Number.isFinite(Date.parse(p.observedAt)) ||
          Date.parse(p.observedAt) > cutoff,
      )
    )
      return null;
    seen.add(item.issueId);
    if (item.aiAnalyses) {
      const companyIds = new Set<string>();
      if (!item.analysisResultVersion || !Array.isArray(item.aiAnalyses))
        return null;
      for (const a of item.aiAnalyses) {
        if (
          !a ||
          companyIds.has(a.companyId) ||
          !item.companies.some((c) => c.companyId === a.companyId) ||
          a.roundId !== value.roundId ||
          !sameBriefingInstant(a.cutoff, value.cutoff) ||
          a.resultVersion !== item.analysisResultVersion ||
          a.verificationMode !== 'separate_request_same_model' ||
          !['positive', 'negative', 'mixed', 'watch'].includes(a.direction) ||
          [
            a.companyName,
            a.keyPoint,
            a.confirmedFact,
            a.businessImpact,
            a.outlook,
            a.nextCheck,
            a.companyConnection,
          ].some((s) => typeof s !== 'string' || !s) ||
          !a.previousChange ||
          !['unavailable', 'maintained', 'strengthened', 'weakened'].includes(
            a.previousChange.status,
          ) ||
          !a.previousChange.text ||
          !a.judgmentBasis ||
          a.judgmentBasis.promptVersion !== 'common-impact-relative-v1' ||
          !a.judgmentBasis.directionReason ||
          !['limited', 'moderate', 'high'].includes(
            a.judgmentBasis.confidence,
          ) ||
          !['unquantified', 'quantified'].includes(
            a.judgmentBasis.effectSizeStatus,
          ) ||
          [a.positive, a.negative, a.priceObservation].some(
            (s) => s !== null && typeof s !== 'string',
          ) ||
          !Array.isArray(a.evidenceIds) ||
          !a.evidenceIds.length ||
          a.evidenceIds.some(
            (id) => !item.sources.some((s) => s.evidenceId === id),
          )
        )
          return null;
        companyIds.add(a.companyId);
      }
    }
  }
  return value;
}
