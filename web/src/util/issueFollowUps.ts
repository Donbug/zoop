import type { BriefingResponse } from '@/types/briefing';
import { validIssueIntelligence } from './issueIntelligence';

/** Validate response bindings; model receipt authentication happens in projection. */
export function validIssueFollowUps(result: BriefingResponse) {
  try {
    const value = result.issueFollowUps;
    const model = validIssueIntelligence(result);
    if (
      !value ||
      !model ||
      value.schemaVersion !== 'issue-followups-v1' ||
      value.scope !== 'provided_verified_rounds' ||
      value.roundId !== result.id ||
      value.baseResultVersion !== model.resultVersion ||
      Date.parse(value.cutoff) !== Date.parse(model.cutoff)
    )
      return null;
    const rounds = new Map(value.reviewedRounds.map((r) => [r.roundId, r]));
    if (rounds.size !== value.reviewedRounds.length) return null;
    const cutoffs = new Set<number>();
    for (const r of rounds.values()) {
      const time = Date.parse(r.cutoff);
      if (
        r.roundId === result.id ||
        !r.roundId ||
        !r.resultVersion ||
        !['morning', 'evening'].includes(r.edition) ||
        !/^\d{4}-\d{2}-\d{2}$/.test(r.date) ||
        !Number.isFinite(time) ||
        time >= Date.parse(model.cutoff) ||
        cutoffs.has(time)
      )
        return null;
      cutoffs.add(time);
    }
    const pairs = new Set(
      model.issues.flatMap((i) =>
        i.companies.map((c) => JSON.stringify([i.issueId, c.companyId])),
      ),
    );
    const seen = new Set<string>();
    for (const e of value.entries) {
      const prior = rounds.get(e.origin.roundId);
      const key = JSON.stringify([
        e.issueId,
        e.companyId,
        e.condition.text.trim(),
      ]);
      if (
        !prior ||
        !Object.entries(prior).every(
          ([k, v]) => e.origin[k as keyof typeof prior] === v,
        ) ||
        !e.issueId ||
        !e.companyId ||
        !e.title.trim() ||
        !e.companyName.trim() ||
        e.status !== 'outcome_unverified' ||
        seen.has(key) ||
        pairs.has(JSON.stringify([e.issueId, e.companyId])) ||
        !e.condition.text.trim() ||
        !e.condition.evidenceIds.length ||
        new Set(e.condition.evidenceIds).size !==
          e.condition.evidenceIds.length ||
        e.sources.length !== e.condition.evidenceIds.length ||
        new Set(e.sources.map((s) => s.evidenceId)).size !== e.sources.length ||
        !e.sources.every(
          (s) =>
            e.condition.evidenceIds.includes(s.evidenceId) &&
            s.documentId &&
            s.quote.trim() &&
            /^[a-f0-9]{64}$/.test(s.bodySha256) &&
            Date.parse(s.publishedAt) <= Date.parse(prior.cutoff),
        )
      )
        return null;
      seen.add(key);
    }
    return value;
  } catch {
    return null;
  }
}
