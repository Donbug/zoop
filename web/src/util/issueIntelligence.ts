import type { BriefingResponse } from '@/types/briefing';
import type { CompanyStatement } from '@/types/briefing/companyOutlook';
import type { IssueIntelligence } from '@/types/briefing/issueIntelligence';

/** D-BRF-01/02: a malformed new revision must not fall back to a different event's old copy. */
export function validIssueIntelligence(
  result: BriefingResponse,
): IssueIntelligence | null {
  try {
    const value = result.issueIntelligence;
    if (
      !value ||
      value.schemaVersion !== 'issue-intelligence-v1' ||
      value.policyVersion !== 'issue-selection-policy-v2' ||
      value.verificationMode !== 'separate_model_request' ||
      value.model !== 'gpt-6-luna' ||
      value.roundId !== result.id ||
      value.date !== result.date ||
      value.edition !== result.edition ||
      Date.parse(value.cutoff) !== Date.parse(result.dataAsOf ?? '') ||
      !Number.isFinite(Date.parse(value.cutoff)) ||
      !value.resultVersion ||
      value.issues.length > 3 ||
      value.issues.length !== result.items.length ||
      new Set(value.issues.map((i) => i.issueId)).size !== value.issues.length
    )
      return null;
    for (const issue of value.issues) {
      const item = result.items.find((i) => i.eventId === issue.issueId);
      if (
        !item ||
        issue.status !== 'PASS' ||
        !issue.resultVersion ||
        issue.companies.length !== item.companies.length ||
        new Set(issue.companies.map((c) => c.companyId)).size !==
          issue.companies.length
      )
        return null;
      const supported = (s: CompanyStatement, ids: string[]) =>
        Boolean(
          s?.text.trim() &&
          s.evidenceIds.length &&
          new Set(s.evidenceIds).size === s.evidenceIds.length &&
          s.evidenceIds.every(
            (id) =>
              ids.includes(id) &&
              item.evidenceIds.includes(id) &&
              issue.sources[id]?.evidenceId === id &&
              issue.sources[id].quote.trim() &&
              /^[a-f0-9]{64}$/.test(issue.sources[id].bodySha256) &&
              Date.parse(issue.sources[id].publishedAt) <=
                Date.parse(value.cutoff),
          ),
        );
      if (!supported(issue.headline, item.evidenceIds)) return null;
      for (const c of issue.companies) {
        if (
          !item.companies.some((x) => x.id === c.companyId) ||
          !['positive', 'negative', 'mixed', 'watch'].includes(c.assessment) ||
          ![
            c.takeaway,
            c.positive,
            c.negative,
            c.newInformation,
            c.impact,
            c.outlook,
            c.comparison,
            ...c.conditions,
            ...c.risks,
          ].every((s) => supported(s, c.sourceIds))
        )
          return null;
        const p = c.previous;
        if (p.status === 'unavailable') {
          if (
            c.comparison.status !== 'unavailable' ||
            c.comparison.previousResultVersion !== null
          )
            return null;
        } else if (
          p.status !== 'available' ||
          p.issueId !== issue.issueId ||
          p.companyId !== c.companyId ||
          !p.judgment.outlook.text.trim() ||
          p.roundId === result.id ||
          !p.resultVersion ||
          c.comparison.previousResultVersion !== p.resultVersion ||
          !(Date.parse(p.cutoff) < Date.parse(value.cutoff)) ||
          (result.edition === 'evening'
            ? p.date !== result.date ||
              p.edition !== 'morning' ||
              c.comparison.status !== 'compared'
            : p.date >= result.date ||
              p.edition !== 'evening' ||
              c.comparison.status !== 'updated')
        )
          return null;
      }
    }
    return value;
  } catch {
    return null;
  }
}
