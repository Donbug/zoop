import type { BriefingResponse } from '@/types/briefing';
import type { IssueReading } from '@/types/briefing/issueReading';
import type { CompanyStatement } from '@/types/briefing/companyOutlook';
import { validIssueIntelligence } from './issueIntelligence';
import type { BriefingIssueView } from './briefingIssueView';

export function uniqueText(values: string[]) {
  return [
    ...new Map(
      values
        .filter((s) => s.trim())
        .map((s) => [s.replace(/\s+/g, ' ').trim(), s.trim()]),
    ).values(),
  ];
}
export function paragraphs(text: string) {
  return uniqueText(text.split(/\n+/));
}

/** Never infer an event merge just from company, document or similar wording. */
export function validIssueReading(
  result: BriefingResponse,
): IssueReading | null {
  try {
    const review = result.issueReading,
      model = validIssueIntelligence(result);
    if (
      !review ||
      !model ||
      review.schemaVersion !== 'issue-reading-review-v1' ||
      review.roundId !== result.id ||
      review.baseResultVersion !== model.resultVersion ||
      Date.parse(review.cutoff) !== Date.parse(model.cutoff)
    )
      return null;
    const owned = new Set<string>();
    for (const group of review.groups) {
      if (
        !group.id ||
        !group.title.trim() ||
        !group.reason.trim() ||
        group.issueIds.length < 2 ||
        new Set(group.issueIds).size !== group.issueIds.length ||
        !group.support.length
      )
        return null;
      for (const id of group.issueIds) {
        if (
          owned.has(id) ||
          !model.issues.some((i) => i.issueId === id) ||
          !group.support.some((s) => s.issueId === id)
        )
          return null;
        owned.add(id);
      }
      for (const s of group.support) {
        const original = model.issues.find((i) => i.issueId === s.issueId)
          ?.sources[s.evidenceId];
        if (
          !group.issueIds.includes(s.issueId) ||
          !original ||
          original.documentId !== s.documentId ||
          original.bodySha256 !== s.bodySha256 ||
          original.quote !== s.quote
        )
          return null;
      }
    }
    if (
      new Set(review.groups.map((g) => g.id)).size !== review.groups.length ||
      new Set(review.issues.map((i) => i.issueId)).size !== review.issues.length
    )
      return null;
    for (const entry of review.issues) {
      const issue = model.issues.find((i) => i.issueId === entry.issueId);
      if (!issue) return null;
      const supported = (s: CompanyStatement) =>
        s.text.trim() &&
        s.evidenceIds.length &&
        s.evidenceIds.every((id) => issue.sources[id]);
      if (
        !supported(entry.whyImportant) ||
        !supported(entry.whyNow) ||
        typeof entry.priceUsedForRanking !== 'boolean' ||
        new Set(entry.connections.map((c) => c.companyId)).size !==
          entry.connections.length
      )
        return null;
      for (const c of entry.connections) {
        const owner = issue.companies.find((x) => x.companyId === c.companyId);
        if (
          !owner ||
          !['primary', 'related', 'unconfirmed'].includes(c.position) ||
          !supported(c.basis) ||
          !c.basis.evidenceIds.every((id) => owner.sourceIds.includes(id))
        )
          return null;
      }
    }
    return review;
  } catch {
    return null;
  }
}

export function readingGroups(
  result: BriefingResponse,
  views: BriefingIssueView[],
  consolidate = true,
) {
  const review = validIssueReading(result);
  const used = new Set<string>();
  return views.flatMap((view) => {
    if (used.has(view.item.eventId)) return [];
    const group = consolidate
      ? review?.groups.find(
          (g) =>
            g.issueIds.includes(view.item.eventId) &&
            g.issueIds.every((id) => views.some((v) => v.item.eventId === id)),
        )
      : undefined;
    const members = group
      ? group.issueIds.map((id) => views.find((v) => v.item.eventId === id)!)
      : [view];
    members.forEach((v) => used.add(v.item.eventId));
    return [
      {
        id: group?.id ?? view.item.eventId,
        title: group?.title ?? view.item.title,
        reason: group?.reason,
        members,
        selections: members.flatMap(
          (v) =>
            review?.issues.filter((i) => i.issueId === v.item.eventId) ?? [],
        ),
      },
    ];
  });
}

type CompanyView = BriefingIssueView['companies'][number];
export function groupCompanies(
  group: ReturnType<typeof readingGroups>[number],
) {
  const rows = group.members.flatMap((v) => v.companies);
  const ids = [...new Set(rows.map((c) => c.company.id))];
  const statement = (values: (CompanyStatement | undefined)[]) => {
    const present = values.filter((v): v is CompanyStatement => Boolean(v));
    return present.length
      ? {
          text: uniqueText(present.flatMap((v) => paragraphs(v.text))).join(
            '\n',
          ),
          evidenceIds: [...new Set(present.flatMap((v) => v.evidenceIds))],
        }
      : undefined;
  };
  const many = (values: CompanyStatement[]) => [
    ...new Map(values.map((v) => [v.text.trim(), v])).values(),
  ];
  return ids
    .map((id) => {
      const values = rows.filter((v) => v.company.id === id),
        first = values[0];
      const connections = group.selections.flatMap((s) =>
        s.connections.filter((c) => c.companyId === id),
      );
      const positions = connections.map((c) => c.position);
      const position = positions.includes('primary')
        ? 'primary'
        : positions.includes('related')
          ? 'related'
          : 'unconfirmed';
      const assessments = [
        ...new Set(values.map((v) => v.assessment).filter(Boolean)),
      ];
      const view: CompanyView = {
        ...first,
        // Different original verdicts are not averaged into a new model verdict.
        assessment: assessments.length === 1 ? assessments[0] : undefined,
        conclusion: statement(values.map((v) => v.conclusion)),
        impact: statement(values.map((v) => v.impact)),
        outlook: statement(values.map((v) => v.outlook)),
        positive: statement(values.map((v) => v.positive)),
        negative: statement(values.map((v) => v.negative)),
        fact: statement(values.map((v) => v.fact)),
        nextChecks: many(values.flatMap((v) => v.nextChecks)),
        conditions: many(values.flatMap((v) => v.conditions)),
        risks: many(values.flatMap((v) => v.risks)),
        refs: [
          ...new Map(
            values
              .flatMap<CompanyView['refs'][number]>((v) => v.refs)
              .map((r) => [r.id, r]),
          ).values(),
        ],
        news: [
          ...new Map(
            values.flatMap((v) => v.news).map((n) => [n.evidenceId, n]),
          ).values(),
        ],
        // Comparison keeps its original event identity; rendered separately per original issue.
        comparison: values.length === 1 ? first.comparison : undefined,
        previous: values.length === 1 ? first.previous : undefined,
      };
      return {
        view,
        position,
        connection: uniqueText(connections.map((c) => c.basis.text)).join('\n'),
      };
    })
    .sort(
      (a, b) =>
        ['primary', 'related', 'unconfirmed'].indexOf(a.position) -
        ['primary', 'related', 'unconfirmed'].indexOf(b.position),
    );
}
