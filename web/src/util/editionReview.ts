import type { BriefingResponse, MarketIndicator } from '@/types/briefing';
import type {
  EditionReview,
  EditionCompanyReview,
} from '@/types/briefing/editionReview';
import type { CompanyStatement } from '@/types/briefing/companyOutlook';

function stable(value: unknown): unknown {
  if (Array.isArray(value)) return value.map(stable);
  if (value && typeof value === 'object')
    return Object.fromEntries(
      Object.entries(value)
        .sort(([a], [b]) => a.localeCompare(b))
        .map(([key, v]) => [key, stable(v)]),
    );
  return value;
}

export function validEditionReview(
  result: BriefingResponse,
): EditionReview | null {
  const r = result.editionReview;
  if (
    !r ||
    r.schemaVersion !== 'zoop-edition-review-v1' ||
    r.status !== 'REVIEWED' ||
    r.verificationMode !== 'editorial_source_review' ||
    r.roundId !== result.id ||
    r.date !== result.date ||
    r.edition !== result.edition ||
    Date.parse(r.cutoff) !== Date.parse(result.dataAsOf ?? '') ||
    r.analysisVersion !== result.companyOutlooks?.resultVersion ||
    !r.headline.trim()
  )
    return null;
  const all = Object.keys(r.sources);
  const supported = (s: CompanyStatement, ids: string[], required: boolean) =>
    !!s?.text?.trim() &&
    (!required || s.evidenceIds.length > 0) &&
    s.evidenceIds.length <= 6 &&
    new Set(s.evidenceIds).size === s.evidenceIds.length &&
    s.evidenceIds.every(
      (id) =>
        ids.includes(id) &&
        !!r.sources[id] &&
        /^https?:\/\//.test(r.sources[id].url) &&
        Date.parse(r.sources[id].publishedAt) <= Date.parse(r.cutoff),
    );
  if (
    ![r.summary, r.marketInterpretation, r.comparison, r.nextSession].every(
      (s) => supported(s, all, false),
    )
  )
    return null;
  const selected = new Set(
    result.items.flatMap((i) => i.companies.map((c) => c.id)),
  );
  const actual = r.companies.filter((c) => c.role === 'selected');
  if (
    actual.length !== selected.size ||
    actual.some((c) => !selected.has(c.companyId)) ||
    new Set(r.companies.map((c) => c.companyId)).size !== r.companies.length
  )
    return null;
  if (
    r.previousReview &&
    !(Date.parse(r.previousReview.cutoff) < Date.parse(r.cutoff))
  )
    return null;
  for (const c of r.companies) {
    if (
      !['selected', 'tracked'].includes(c.role) ||
      !['priority_watch', 'watch', 'cautious_watch', 'deferred'].includes(
        c.stance,
      ) ||
      ![
        c.title,
        c.takeaway,
        c.newInformation,
        c.judgment,
        c.positive,
        c.negative,
        ...c.watch,
      ].every((s) => supported(s, c.sourceIds, true)) ||
      c.price.companyId !== c.companyId ||
      Date.parse(c.price.cutoff) !== Date.parse(r.cutoff) ||
      (c.price.latest &&
        Date.parse(c.price.latest.observedAt) > Date.parse(r.cutoff))
    )
      return null;
    const before =
      r.previousReview?.draft.companies.find(
        (p) => p.companyId === c.companyId,
      ) ?? null;
    if (
      (c.role === 'tracked' && !before) ||
      JSON.stringify(stable(c.previous)) !== JSON.stringify(stable(before))
    )
      return null;
    if (
      c.checks.length !== (before?.watch.length ?? 0) ||
      c.checks.some(
        (check, i) =>
          check.condition !== before?.watch[i]?.text ||
          (check.status === 'not_observed' &&
            !c.watch.some((w) => w.text === check.condition)) ||
          !['confirmed', 'contradicted', 'not_observed'].includes(
            check.status,
          ) ||
          !supported(
            check.observation,
            c.sourceIds,
            check.status !== 'not_observed',
          ) ||
          (check.status !== 'not_observed' &&
            !check.observation.evidenceIds.some(
              (id) =>
                Date.parse(r.sources[id].publishedAt) >
                Date.parse(r.previousReview!.cutoff),
            )),
      )
    )
      return null;
  }
  if (
    r.previousReview?.draft.companies.some(
      (p) => !r.companies.some((c) => c.companyId === p.companyId),
    )
  )
    return null;
  return r;
}

export function businessResult(c: EditionCompanyReview) {
  if (!c.previous || !c.checks.length) return '이전 판단 없음';
  const confirmed = c.checks.filter((s) => s.status === 'confirmed').length;
  const contradicted = c.checks.filter(
    (s) => s.status === 'contradicted',
  ).length;
  if (confirmed && contradicted) return '확인·반대 근거 혼재';
  if (contradicted) return '반대 근거 확인';
  if (confirmed)
    return confirmed === c.checks.length ? '확인 조건 관측' : '일부 조건 관측';
  return '조건 미관측 · 평가 유보';
}
export function marketCoverage(r: EditionReview) {
  const items =
    r.marketVariables.status === 'available'
      ? r.marketVariables.indicators
      : [];
  const indices = ['kospi', 'kosdaq']
    .map((id) => items.find((i) => i.id === id))
    .filter(
      (i): i is MarketIndicator =>
        !!i && i.value !== null && ['ok', 'delayed'].includes(i.status),
    );
  const todayClose =
    r.edition === 'evening' &&
    indices.length === 2 &&
    indices.every((i) => i.valueKind === 'close' && i.observedDate === r.date);
  const dayBefore = new Date(`${r.date}T00:00:00Z`);
  dayBefore.setUTCDate(dayBefore.getUTCDate() - 1);
  const dailyComparable =
    todayClose &&
    indices.every(
      (i) => i.baseline?.date === dayBefore.toISOString().slice(0, 10),
    );
  return {
    indices,
    todayClose,
    dailyComparable,
    label:
      r.edition === 'morning'
        ? '최근 지수 기준 · 장초반 자료 없음'
        : todayClose
          ? dailyComparable
            ? '종가 기준 평가 · 장중 흐름 미확인'
            : '오늘 종가 확인 · 하루 등락 기준 부족'
          : '오늘 장 자료 부족 · 이전 지수와 구분',
  };
}
