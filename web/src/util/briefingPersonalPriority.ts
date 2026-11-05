import { prioritySourceAvailable } from './briefingSourceTime';
import { sameBriefingInstant } from './briefingTime';
import type { BriefingResponse } from '@/types/briefing';
import { safeArticleUrl } from '@/components/graph/event-format';

export type PersonalPriority = {
  schemaVersion: 'personal-relative-priority-view-v1';
  roundId: string;
  cutoff: string;
  resultVersion: string;
  companyIds: string[];
  candidateCount: number;
  minimumIssues?: number;
  status: 'available' | 'collection_insufficient' | 'no_companies';
  items: {
    issueId: string;
    kind: 'new_issue' | 'related_reference' | 'previous_issue';
    title: string;
    analysisOmittedReason?: string;
    topicTag?: string;
    aiAnalyses?: {
      companyId: string;
      companyName: string;
      roundId: string;
      cutoff: string;
      resultVersion: string;
      verificationMode: 'separate_request_same_model';
      direction: 'positive' | 'negative' | 'mixed' | 'watch';
      keyPoint: string;
      confirmedFact: string;
      businessImpact: string;
      forMyStocks: string;
      outlook: string;
      positive: string | null;
      negative: string | null;
      priceObservation: string | null;
      previousChange: { status: string; text: string };
      nextCheck: string;
      evidenceIds: string[];
      judgmentBasis?: {
        promptVersion:
          'personal-impact-relative-v3' | 'common-impact-relative-v1';
        directionReason: string;
        confidence: 'limited' | 'moderate' | 'high';
        effectSizeStatus: 'unquantified' | 'quantified';
      };
      comparison?: {
        status: 'same_issue_company' | 'newly_selected';
        baseline: null | {
          issueId: string;
          companyId: string;
          roundId: string;
          cutoff: string;
          resultVersion: string;
          direction: 'positive' | 'negative' | 'mixed' | 'watch';
          businessImpact: string;
          outlook: string;
        };
      };
      recordReview?: {
        type: 'local_record_review';
        sourceResultVersion: string;
        knownFactor: string;
        missingData: string;
        nextData: string;
        evidenceIds: string[];
        nonFactorFields?: ('positive' | 'negative')[];
      };
    }[];
    reason: string;
    originRoundId: string;
    originCutoff: string;
    connections: { companyId: string; name: string; reason: string }[];
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
    priorAnalysis: {
      companyName: string;
      takeaway: string;
      positive: string;
      negative: string;
      conditions: string[];
    }[];
    price: null | {
      companyName: string;
      baseline: string;
      latest: string;
      changeRate: string;
      currency: string;
      observedAt: string;
    };
  }[];
};

type PersonalAnalysis = NonNullable<
  PersonalPriority['items'][number]['aiAnalyses']
>[number];

export type BriefingBusinessAnalysis = Omit<
  PersonalAnalysis,
  'forMyStocks' | 'judgmentBasis'
> & {
  companyConnection?: string;
  judgmentBasis?: Omit<
    NonNullable<PersonalAnalysis['judgmentBasis']>,
    'promptVersion'
  > & { promptVersion: string };
};

function validV3Basis(
  analysis: PersonalAnalysis,
  issueId: string,
  roundId: string,
  cutoff: string,
): boolean {
  const basis = analysis.judgmentBasis;
  const comparison = analysis.comparison;
  if (!basis) return !comparison;
  if (
    !['personal-impact-relative-v3', 'common-impact-relative-v1'].includes(
      basis.promptVersion,
    ) ||
    typeof basis.directionReason !== 'string' ||
    !basis.directionReason ||
    !['limited', 'moderate', 'high'].includes(basis.confidence) ||
    !['unquantified', 'quantified'].includes(basis.effectSizeStatus) ||
    !comparison
  )
    return false;
  // The server can filter exact, independently checked COMMON prose to the
  // member's companies. Keep its real version; never relabel it as a new AI run.
  if (
    basis.promptVersion === 'common-impact-relative-v1' &&
    (!analysis.resultVersion.startsWith('common-impact-relative-v1-') ||
      comparison.status !== 'newly_selected')
  )
    return false;
  if (comparison.status === 'newly_selected')
    return comparison.baseline === null;
  const before = comparison.baseline;
  return (
    comparison.status === 'same_issue_company' &&
    !!before &&
    before.issueId === issueId &&
    before.companyId === analysis.companyId &&
    before.roundId === roundId &&
    sameBriefingInstant(before.cutoff, cutoff) &&
    typeof before.resultVersion === 'string' &&
    !!before.resultVersion &&
    before.resultVersion !== analysis.resultVersion &&
    typeof before.businessImpact === 'string' &&
    !!before.businessImpact &&
    typeof before.outlook === 'string' &&
    !!before.outlook &&
    ['positive', 'negative', 'mixed', 'watch'].includes(before.direction)
  );
}

export function personalPriorityOf(
  result: BriefingResponse,
): PersonalPriority | null {
  try {
    return validatePersonalPriority(result);
  } catch {
    return null;
  }
}

function validatePersonalPriority(
  result: BriefingResponse,
): PersonalPriority | null {
  const value = (
    result as BriefingResponse & { personalPriority?: PersonalPriority }
  ).personalPriority;
  if (
    !value ||
    value.schemaVersion !== 'personal-relative-priority-view-v1' ||
    value.roundId !== result.id ||
    !sameBriefingInstant(value.cutoff, result.dataAsOf) ||
    !value.resultVersion ||
    !Array.isArray(value.companyIds) ||
    !Array.isArray(value.items) ||
    value.items.length > 3 ||
    !['available', 'collection_insufficient', 'no_companies'].includes(
      value.status,
    )
  )
    return null;
  const cutoff = Date.parse(value.cutoff);
  const seen = new Set<string>();
  if (
    !Number.isFinite(cutoff) ||
    value.items.some((item) => {
      if (
        !item ||
        !item.issueId ||
        seen.has(item.issueId) ||
        !item.title ||
        !item.reason ||
        !['new_issue', 'related_reference', 'previous_issue'].includes(
          item.kind,
        ) ||
        !Number.isFinite(Date.parse(item.originCutoff)) ||
        Date.parse(item.originCutoff) > cutoff ||
        !Array.isArray(item.connections) ||
        !item.connections.length ||
        item.connections.some(
          (c) =>
            !c ||
            !value.companyIds.includes(c.companyId) ||
            !c.name ||
            !c.reason,
        ) ||
        !Array.isArray(item.sources) ||
        !item.sources.length ||
        item.sources.some(
          (s) =>
            !s ||
            !s.quote ||
            [s.title, s.publisher].some(
              (v) => v !== undefined && (typeof v !== 'string' || !v.trim()),
            ) ||
            !s.evidenceId ||
            !safeArticleUrl(s.url) ||
            !Number.isFinite(prioritySourceAvailable(s)) ||
            prioritySourceAvailable(s) > cutoff,
        ) ||
        !Array.isArray(item.priorAnalysis) ||
        item.priorAnalysis.some(
          (a) =>
            !a ||
            typeof a.takeaway !== 'string' ||
            !Array.isArray(a.conditions),
        ) ||
        (item.aiAnalyses &&
          (!Array.isArray(item.aiAnalyses) ||
            item.aiAnalyses.some(
              (analysis) =>
                !analysis ||
                analysis.roundId !== result.id ||
                !sameBriefingInstant(analysis.cutoff, result.dataAsOf) ||
                !validV3Basis(
                  analysis,
                  item.issueId,
                  value.roundId,
                  value.cutoff,
                ) ||
                analysis.verificationMode !== 'separate_request_same_model' ||
                !analysis.resultVersion ||
                !item.connections.some(
                  (c) => c.companyId === analysis.companyId,
                ) ||
                !['positive', 'negative', 'mixed', 'watch'].includes(
                  analysis.direction,
                ) ||
                [
                  analysis.keyPoint,
                  analysis.confirmedFact,
                  analysis.businessImpact,
                  analysis.forMyStocks,
                  analysis.outlook,
                  analysis.nextCheck,
                ].some((s) => typeof s !== 'string' || !s) ||
                [
                  analysis.positive,
                  analysis.negative,
                  analysis.priceObservation,
                ].some((s) => s !== null && typeof s !== 'string') ||
                !Array.isArray(analysis.evidenceIds) ||
                !analysis.evidenceIds.length ||
                analysis.evidenceIds.some(
                  (id) => !item.sources.some((s) => s.evidenceId === id),
                ) ||
                (analysis.recordReview &&
                  (analysis.recordReview.type !== 'local_record_review' ||
                    analysis.recordReview.sourceResultVersion !==
                      analysis.resultVersion ||
                    [
                      analysis.recordReview.knownFactor,
                      analysis.recordReview.missingData,
                      analysis.recordReview.nextData,
                    ].some((s) => typeof s !== 'string' || !s) ||
                    !Array.isArray(analysis.recordReview.evidenceIds) ||
                    !analysis.recordReview.evidenceIds.length ||
                    analysis.recordReview.evidenceIds.some(
                      (id) => !analysis.evidenceIds.includes(id),
                    ) ||
                    (analysis.recordReview.nonFactorFields &&
                      (!Array.isArray(analysis.recordReview.nonFactorFields) ||
                        analysis.recordReview.nonFactorFields.some(
                          (field) => !['positive', 'negative'].includes(field),
                        ))))) ||
                !analysis.previousChange ||
                typeof analysis.previousChange.text !== 'string' ||
                ![
                  'unavailable',
                  'maintained',
                  'strengthened',
                  'weakened',
                ].includes(analysis.previousChange.status),
            ))) ||
        (item.price &&
          (!Number.isFinite(Date.parse(item.price.observedAt)) ||
            Date.parse(item.price.observedAt) > cutoff))
      )
        return true;
      seen.add(item.issueId);
      return false;
    })
  )
    return null;
  return value;
}
