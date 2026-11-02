import type { BriefingResponse } from '@/types/briefing';
import type { FollowUpReviewEntry } from '@/types/briefing/issueFollowUpReview';
import { validIssueFollowUps } from './issueFollowUps';

export function followUpKey(ref: FollowUpReviewEntry['ref']) {
  return JSON.stringify([
    ref.issueId,
    ref.companyId,
    ref.origin.roundId,
    ref.origin.resultVersion,
    ref.condition.text,
    ref.condition.evidenceIds,
  ]);
}

/** Structural defence only. Saved body/receipt checks happen in projection. */
export function validIssueFollowUpReview(result: BriefingResponse) {
  try {
    const base = validIssueFollowUps(result);
    const review = result.issueFollowUpReview;
    if (
      !base ||
      !review ||
      review.schemaVersion !== 'issue-followup-review-v1' ||
      review.method !== 'recorded_editorial_review' ||
      review.roundId !== base.roundId ||
      review.baseResultVersion !== base.baseResultVersion ||
      Date.parse(review.cutoff) !== Date.parse(base.cutoff) ||
      !Number.isFinite(Date.parse(review.reviewedAt)) ||
      review.entries.length !== base.entries.length
    )
      return null;
    const expected = new Map(base.entries.map((e) => [followUpKey(e), e]));
    const seen = new Set<string>();
    for (const e of review.entries) {
      const key = followUpKey(e.ref);
      const original = expected.get(key);
      if (
        !original ||
        seen.has(key) ||
        !e.summary.trim() ||
        !e.requirements.length ||
        !Object.entries(original.origin).every(
          ([k, v]) => e.ref.origin[k as keyof typeof original.origin] === v,
        )
      )
        return null;
      seen.add(key);
      const sources = new Map(e.sources.map((s) => [s.id, s]));
      if (sources.size !== e.sources.length) return null;
      for (const s of sources.values()) {
        const time = Date.parse(s.publishedAt);
        if (
          !s.id ||
          !s.documentId ||
          !s.quote.trim() ||
          !s.title.trim() ||
          !/^[a-f0-9]{64}$/.test(s.bodySha256) ||
          !Number.isFinite(time) ||
          time > Date.parse(base.cutoff) ||
          !Number.isInteger(s.start) ||
          !Number.isInteger(s.end) ||
          s.start < 0 ||
          s.end <= s.start ||
          !['same_event', 'related_event'].includes(s.relation) ||
          !['plan', 'completed_action', 'background'].includes(s.kind) ||
          s.period !==
            (time > Date.parse(e.ref.origin.cutoff)
              ? 'after_condition'
              : 'prior_background')
        )
          return null;
      }
      if (
        !e.facts.every(
          (f) =>
            f.text.trim() &&
            f.sourceIds.length &&
            f.sourceIds.every((id) => sources.has(id)),
        )
      )
        return null;
      for (const r of e.requirements) {
        if (
          !r.text.trim() ||
          !['completed', 'unverified'].includes(r.observation) ||
          !r.sourceIds.every((id) => sources.has(id))
        )
          return null;
        if (
          r.observation === 'completed' &&
          (!r.sourceIds.length ||
            !r.sourceIds.every((id) => {
              const s = sources.get(id)!;
              return (
                s.kind === 'completed_action' &&
                s.relation === 'same_event' &&
                s.period === 'after_condition'
              );
            }))
        )
          return null;
      }
      const status = e.requirements.every((r) => r.observation === 'completed')
        ? 'fulfilled'
        : 'insufficient_evidence';
      if (e.status !== status) return null;
    }
    return review;
  } catch {
    return null;
  }
}
