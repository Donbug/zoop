import type { BriefingResponse } from '@/types/briefing';
import type { CompanyStatement } from '@/types/briefing/companyOutlook';
import type { JudgmentUpdate as Update } from '@/types/briefing/judgmentUpdate';

/** D-BRF-01/02: an industry interpretation never impersonates a same-company prior judgment. */
export function validJudgment(result: BriefingResponse): Update | null {
  const u = result.judgmentUpdate;
  if (
    !u ||
    u.status !== 'PASS' ||
    u.schemaVersion !== 'zoop-judgment-update-v1' ||
    u.roundId !== result.id ||
    u.edition !== result.edition ||
    u.companyResultVersion !== result.companyOutlooks?.resultVersion ||
    Date.parse(u.cutoff) !== Date.parse(result.dataAsOf ?? '') ||
    !(Date.parse(u.previousCutoff) < Date.parse(u.cutoff)) ||
    !u.companies?.length ||
    !u.sources ||
    !u.conclusion ||
    !u.industryChange ||
    !u.limits
  )
    return null;
  const sources = u.sources;
  const supported = (s: CompanyStatement | undefined, allowed: string[]) =>
    !!s?.text?.trim() &&
    !!s.evidenceIds.length &&
    new Set(s.evidenceIds).size === s.evidenceIds.length &&
    s.evidenceIds.every(
      (id) =>
        allowed.includes(id) &&
        !!sources[id] &&
        Date.parse(sources[id].publishedAt) <= Date.parse(u.cutoff) &&
        /^https?:\/\//.test(sources[id].url),
    );
  if (
    ![u.conclusion, u.industryChange, u.limits].every((s) =>
      supported(s, Object.keys(sources)),
    )
  )
    return null;
  const selected = new Set(
    result.items.flatMap((i) => i.companies.map((c) => c.id)),
  );
  const actual = u.companies
    .filter((c) => c.role === 'selected')
    .map((c) => c.companyId);
  if (
    new Set(actual).size !== actual.length ||
    actual.length !== selected.size ||
    actual.some((id) => !selected.has(id)) ||
    new Set(u.companies.map((c) => c.companyId)).size !== u.companies.length
  )
    return null;
  for (const c of u.companies) {
    if (
      !['selected', 'watch'].includes(c.role) ||
      ![
        'initial',
        'maintained',
        'strengthened',
        'weakened',
        'unassessable',
      ].includes(c.decision) ||
      (!c.previousJudgment &&
        !['initial', 'unassessable'].includes(c.decision)) ||
      (c.role === 'watch' &&
        (!c.previousJudgment ||
          !['maintained', 'unassessable'].includes(c.decision))) ||
      [
        c.newEvidence,
        c.reason,
        c.strengthenIf,
        c.weakenIf,
        c.topic,
        c.title,
        c.description,
      ].some((s) => !supported(s, c.sourceIds)) ||
      c.topic.text.length > 12 ||
      c.title.text.length > 32 ||
      c.description.text.length > 64
    )
      return null;
  }
  return u;
}
