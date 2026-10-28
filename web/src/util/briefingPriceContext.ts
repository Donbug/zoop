import type { BriefingResponse } from '@/types/briefing';
import type {
  BriefingPriceContext,
  PricePoint,
} from '@/types/briefing/priceContext';

export function validPriceContext(
  result: BriefingResponse,
): BriefingPriceContext | null {
  try {
    const p = result.companyPriceContext;
    const r = result.editionReview;
    if (
      !p ||
      !r ||
      p.schemaVersion !== 'zoop-company-price-context-v1' ||
      p.status !== 'derived' ||
      p.authorship !== 'deterministic_price_observation' ||
      p.roundId !== result.id ||
      p.roundId !== r.roundId ||
      p.edition !== r.edition ||
      p.date !== r.date ||
      p.cutoff !== r.cutoff ||
      p.reviewVersion !== r.resultVersion ||
      p.companies.length !== r.companies.length
    )
      return null;
    const cutoff = Date.parse(p.cutoff);
    const positive = (s: string) =>
      /^\d+(?:\.\d+)?$/.test(s) && Number(s) > 0 && Number.isFinite(Number(s));
    const point = (v: PricePoint) =>
      positive(v.value) &&
      Number.isFinite(Date.parse(v.observedAt)) &&
      Date.parse(v.observedAt) <= cutoff;
    if (
      !Number.isFinite(cutoff) ||
      new Set(p.companies.map((c) => c.companyId)).size !== p.companies.length
    )
      return null;
    for (const c of p.companies) {
      const business = r.companies.find((x) => x.companyId === c.companyId);
      if (
        !business ||
        c.provider !== 'toss' ||
        c.currency !== (c.companyId.startsWith('KRX:') ? 'KRW' : 'USD') ||
        Date.parse(c.cutoff) !== cutoff
      )
        return null;
      if (p.outlookIntegrationVersion) {
        const o = c.outlook;
        if (
          p.outlookIntegrationVersion !== 'zoop-company-price-outlook-v1' ||
          !o ||
          o.schemaVersion !== p.outlookIntegrationVersion ||
          o.authorship !== 'source_bound_composition' ||
          o.stance !== business.stance ||
          o.businessJudgment.text !== business.judgment.text ||
          JSON.stringify(o.businessJudgment.evidenceIds) !==
            JSON.stringify(business.judgment.evidenceIds) ||
          !o.evidenceIds.every(
            (id) => business.sourceIds.includes(id) && !!r.sources[id],
          ) ||
          o.text !==
            `${o.businessJudgment.text} 가격 측면에서는 ${o.priceObservation} ${o.nextCheck}` ||
          !o.takeaway.startsWith(business.takeaway.text + ' ')
        )
          return null;
      } else if (c.outlook) return null;
      if (c.status === 'unavailable') continue;
      if (
        c.status !== 'available' ||
        !point(c.latest) ||
        !positive(c.day.open) ||
        !positive(c.day.high) ||
        !positive(c.day.low) ||
        !positive(c.day.closeOrLast) ||
        c.barCount < 1 ||
        Number(c.day.low) > Number(c.day.high) ||
        !Number.isFinite(Date.parse(c.day.to)) ||
        !Number.isFinite(Date.parse(c.day.from)) ||
        Date.parse(c.day.from) > Date.parse(c.day.to) ||
        Date.parse(c.day.to) !== Date.parse(c.latest.observedAt) ||
        Date.parse(c.day.to) > cutoff
      )
        return null;
      for (const n of c.news) {
        if (
          !business.newInformation.evidenceIds.includes(n.evidenceId) ||
          !r.sources[n.evidenceId] ||
          Date.parse(n.publishedAt) !==
            Date.parse(r.sources[n.evidenceId].publishedAt) ||
          Date.parse(n.publishedAt) > cutoff ||
          !Number.isInteger(n.postNewsBars) ||
          n.postNewsBars < 0
        )
          return null;
        if (
          n.before &&
          (!point(n.before) ||
            Date.parse(n.before.observedAt) > Date.parse(n.publishedAt))
        )
          return null;
        if (
          n.status === 'observed' &&
          (!n.before || n.postNewsBars < 1 || n.changeRatePercent === null)
        )
          return null;
        if (n.status !== 'observed' && n.changeRatePercent !== null)
          return null;
        if (
          n.postNewsBars > c.barCount ||
          ![
            'observed',
            'no_post_news_trade',
            'event_window_unavailable',
          ].includes(n.status) ||
          (n.status === 'no_post_news_trade' && n.postNewsBars !== 0) ||
          (n.changeRatePercent !== null &&
            !/^-?\d+(?:\.\d+)?$/.test(n.changeRatePercent))
        )
          return null;
      }
    }
    if (p.outlookIntegrationVersion) {
      const m = p.marketReference;
      if (
        !m ||
        !['available', 'unavailable'].includes(m.status) ||
        (m.status === 'available') !== m.indicators.length > 0 ||
        new Set(m.indicators.map((i) => i.id)).size !== m.indicators.length
      )
        return null;
      for (const i of m.indicators) {
        if (
          !['kospi', 'kosdaq', 'usdkrw'].includes(i.id) ||
          !['ok', 'delayed'].includes(i.status) ||
          !Number.isFinite(i.value) ||
          i.value <= 0 ||
          !/^https?:\/\//.test(i.source.url) ||
          !Number.isFinite(Date.parse(i.observedDate)) ||
          Date.parse(i.observedDate) > cutoff ||
          (i.observedAt !== null &&
            (!Number.isFinite(Date.parse(i.observedAt)) ||
              Date.parse(i.observedAt) > cutoff)) ||
          (i.baselineDate !== null &&
            !(Date.parse(i.baselineDate) < Date.parse(i.observedDate))) ||
          (i.changeRatePercent !== null &&
            (i.baselineDate === null ||
              !/^-?\d+(?:\.\d+)?$/.test(i.changeRatePercent)))
        )
          return null;
      }
    }
    return p;
  } catch {
    return null;
  }
}
