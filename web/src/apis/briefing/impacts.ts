import { ApiError, call } from '@/apis/auth/ApiService';
import type { BriefingResponse, BriefingItem } from '@/types/briefing';
import type { BriefingImpacts } from '@/types/briefing/impacts';

/** Read only: never substitute a different round/version or a company-wide document sentiment. */
export async function getBriefingItemImpacts(
  round: BriefingResponse,
  item: BriefingItem,
) {
  const query = round.graphVersion
    ? `?graphVersion=${encodeURIComponent(round.graphVersion)}`
    : '';
  const value = await call<BriefingImpacts>(
    `/api/v1/briefings/${encodeURIComponent(round.id)}/items/${encodeURIComponent(item.eventId)}/impacts${query}`,
    'GET',
    undefined,
    { skipAuth: true },
  );
  validateBriefingImpacts(value, round, item);
  // An explicitly labelled later review is separate from the immutable publication result.
  if (
    value.companies.length === 0 &&
    ['publication_snapshot_not_recorded', 's3_receipt_not_recorded'].includes(
      value.reason ?? '',
    )
  ) {
    try {
      const review = await call<BriefingImpacts>(
        `/api/v1/briefings/${encodeURIComponent(round.id)}/items/${encodeURIComponent(item.eventId)}/impact-reviews${query}`,
        'GET',
        undefined,
        { skipAuth: true },
      );
      validateBriefingImpacts(review, round, item);
      if (review.reviewContext) return review;
    } catch (error) {
      // Old servers do not have the optional review route; an outage/corruption stays an error.
      if (!(error instanceof ApiError && error.status === 404)) throw error;
    }
  }
  return value;
}

export function validateBriefingImpacts(
  value: BriefingImpacts,
  round: BriefingResponse,
  item: BriefingItem,
) {
  const fail = () => {
    throw new Error(
      '요청한 회차·이슈·기업·근거와 S3 평가가 일치하지 않습니다.',
    );
  };
  if (
    !value ||
    value.roundId !== round.id ||
    value.eventId !== item.eventId ||
    value.graphVersion !== round.graphVersion ||
    !Number.isFinite(Date.parse(value.dataAsOf)) ||
    Date.parse(value.dataAsOf) !== Date.parse(round.dataAsOf ?? '') ||
    !['available', 'unavailable'].includes(value.status) ||
    value.metadata?.source !== 's3_issue_impacts' ||
    value.metadata.graphVersion !== value.graphVersion ||
    Date.parse(value.metadata.asOf) !== Date.parse(value.dataAsOf) ||
    !Array.isArray(value.companies)
  )
    fail();
  const companies = new Set(item.companies.map((c) => c.id)),
    seen = new Set<string>();
  if (value.reviewContext) {
    const review = value.reviewContext;
    if (
      review.mode !== 'historical_reassessment' ||
      review.inputScope !== 'preserved_quote_context' ||
      review.generationModel !== 'gpt-6-luna' ||
      review.verifierModel !== 'jev-1.14.0' ||
      !/^[a-f0-9]{64}$/.test(review.resultVersion) ||
      !Number.isFinite(Date.parse(review.assessedAt)) ||
      Date.parse(review.assessedAt) < Date.parse(value.dataAsOf) ||
      (review.citationPolicy != null &&
        review.citationPolicy !== 'complete-source-paragraph-1')
    )
      fail();
  }
  for (const c of value.companies) {
    if (
      !companies.has(c.companyId) ||
      seen.has(c.companyId) ||
      !c.companyName?.trim() ||
      !Array.isArray(c.assessments) ||
      !['available', 'unavailable'].includes(c.status)
    )
      fail();
    seen.add(c.companyId);
    const ids = new Set<string>();
    for (const a of c.assessments) {
      if (
        value.reviewContext &&
        (a.provenance?.sourceKind !== 'collected' ||
          a.provenance.executionMode !== 'live' ||
          a.provenance.recordingKind !== 'provider')
      )
        fail();
      if (
        !a.id ||
        ids.has(a.id) ||
        !a.relationId ||
        ![
          'verified',
          'not-applicable',
          'not-proposed',
          'no-evidence',
          'technical-reject',
          'verifier-reject',
          'withheld',
        ].includes(a.status) ||
        !a.provenance ||
        !['collected', 'synthetic'].includes(a.provenance.sourceKind) ||
        !(
          (a.provenance.executionMode === 'live' &&
            a.provenance.recordingKind === 'provider') ||
          (a.provenance.executionMode === 'replay' &&
            a.provenance.recordingKind === 'authored-test')
        ) ||
        !Array.isArray(a.evidence)
      )
        fail();
      ids.add(a.id);
      const facts = a.facts ?? [];
      if (
        !Array.isArray(facts) ||
        facts.length > 16 ||
        (a.status === 'withheld' && facts.length > 0) ||
        (value.reviewContext?.citationPolicy ===
          'complete-source-paragraph-1' &&
          facts.length === 0)
      )
        fail();
      const factIds = new Set<string>();
      for (const f of facts) {
        if (
          !f.id ||
          factIds.has(f.id) ||
          !f.quote?.trim() ||
          !f.articleId ||
          !f.articleVersion ||
          !f.title?.trim() ||
          !f.url?.trim() ||
          'effect' in f ||
          !Number.isSafeInteger(f.start) ||
          !Number.isSafeInteger(f.end) ||
          f.start < 0 ||
          f.end <= f.start ||
          Array.from(f.quote).length !== f.end - f.start ||
          !Number.isFinite(Date.parse(f.publishedAt)) ||
          Date.parse(f.publishedAt) > Date.parse(value.dataAsOf)
        )
          fail();
        factIds.add(f.id);
      }
      if (a.evidencePlan) {
        const p = a.evidencePlan;
        if (
          a.status === 'withheld' ||
          p.status !== 'prepared_not_evaluated' ||
          !Number.isFinite(Date.parse(p.preparedAt)) ||
          Date.parse(p.preparedAt) < Date.parse(value.dataAsOf) ||
          !p.reason?.trim() ||
          !Array.isArray(p.existingEvidence) ||
          !p.existingEvidence.length ||
          p.existingEvidence.length > 8 ||
          !Array.isArray(p.collectionNeeds) ||
          !p.collectionNeeds.length ||
          p.collectionNeeds.length > 16 ||
          'label' in p ||
          'effect' in p
        )
          fail();
        const ids = new Set<string>();
        for (const item of p.existingEvidence) {
          const f = item.source;
          if (
            ![
              'direct',
              'issuer_explanation',
              'conditional_risk',
              'background',
            ].includes(item.scope) ||
            !item.note?.trim() ||
            !f ||
            !f.id ||
            ids.has(f.id) ||
            !f.quote?.trim() ||
            !f.articleId ||
            !f.articleVersion ||
            !f.title?.trim() ||
            !f.url?.trim() ||
            'effect' in f ||
            'label' in f ||
            !Number.isSafeInteger(f.start) ||
            !Number.isSafeInteger(f.end) ||
            f.start < 0 ||
            f.end <= f.start ||
            f.end - f.start > 2000 ||
            Array.from(f.quote).length !== f.end - f.start ||
            !Number.isFinite(Date.parse(f.publishedAt)) ||
            Date.parse(f.publishedAt) > Date.parse(value.dataAsOf)
          )
            fail();
          ids.add(f.id);
        }
        for (const n of p.collectionNeeds) {
          if (
            !['before_cutoff_gap', 'future_followup'].includes(n.kind) ||
            !n.what?.trim() ||
            !n.why?.trim() ||
            !n.preferredSource?.trim()
          )
            fail();
        }
        if (p.research) {
          const r = p.research;
          const validDate = (s: string) => Number.isFinite(Date.parse(s));
          if (
            r.status !== 'editorial_sources_not_ai_evaluated' ||
            !validDate(r.linkedAt) ||
            Date.parse(r.linkedAt) <= Date.parse(value.dataAsOf) ||
            !Array.isArray(r.sources) ||
            r.sources.length > 4 ||
            (!r.sources.length && !r.timeCheck) ||
            'label' in r ||
            'effect' in r
          )
            fail();
          const sourceIds = new Set<string>();
          for (const s of r.sources) {
            let official = false;
            try {
              const url = new URL(s.url);
              official =
                url.protocol === 'https:' &&
                !url.username &&
                !url.password &&
                !url.port &&
                ['news.samsung.com', 'www.sec.gov'].includes(url.hostname);
            } catch {
              /* Invalid sources fail closed below. */
            }
            if (
              !s.id ||
              sourceIds.has(s.id) ||
              s.companyId !== c.companyId ||
              !official ||
              !s.title?.trim() ||
              !s.summary?.trim() ||
              !s.limitations?.trim() ||
              !s.excerpt?.trim() ||
              !validDate(s.publishedAt) ||
              Date.parse(s.publishedAt) > Date.parse(value.dataAsOf) ||
              ![
                'issuer_html_jsonld',
                'SEC_index_accepted_America_New_York',
              ].includes(s.timeBasis) ||
              !['direct_http', 'web_tool_extract'].includes(s.transport) ||
              !/^[a-f0-9]{64}$/.test(s.textSha256) ||
              s.historicalVersionVerified !== false ||
              'label' in s ||
              'effect' in s
            )
              fail();
            sourceIds.add(s.id);
          }
          if (r.timeCheck) {
            const t = r.timeCheck;
            if (
              t.status !== 'publisher_time_disagreement' ||
              !t.summary?.trim() ||
              !t.limitation?.trim() ||
              !validDate(t.storedPublishedAt) ||
              !validDate(t.distributionPublishedAt) ||
              !t.storedUrl?.startsWith('https://') ||
              !t.distributionUrl?.startsWith('https://www.globenewswire.com/')
            )
              fail();
          }
        }
      }
      if (a.status === 'verified') {
        if (
          !a.label ||
          !['positive', 'negative', 'mixed', 'undetermined'].includes(
            a.label,
          ) ||
          !a.evidence.length
        )
          fail();
      } else if (a.label !== null || a.evidence.length) fail();
      if (a.supplementalReview) {
        const s = a.supplementalReview;
        if (
          !value.reviewContext ||
          a.status !== 'verified' ||
          !a.evidencePlan?.research?.sources.length ||
          s.mode !== 'supplemental_historical_simulation' ||
          s.previousLabel !== a.label ||
          !Number.isFinite(Date.parse(s.assessedAt)) ||
          Date.parse(s.assessedAt) <= Date.parse(value.dataAsOf) ||
          s.verifierModel !== 'jev-1.14.0' ||
          s.historicalVersionVerified !== false ||
          !/^[a-f0-9]{64}$/.test(s.resultVersion) ||
          !['supported', 'insufficient'].includes(s.targetVerdict) ||
          !s.summary?.trim() ||
          !s.limitations?.trim() ||
          !Array.isArray(s.confirmedFacts) ||
          !s.confirmedFacts.length ||
          s.confirmedFacts.length > 8 ||
          !Array.isArray(s.evidence) ||
          !s.evidence.length ||
          s.evidence.length > 16
        )
          fail();
        const ids = new Set<string>();
        for (const e of s.evidence) {
          const source = a.evidencePlan?.research?.sources.find(
            (x) =>
              e.articleId === 'supplement-' + x.id &&
              e.articleVersion === 'sha256-' + x.textSha256,
          );
          const original = (a.facts ?? []).find(
            (x) =>
              x.articleId === e.articleId &&
              x.articleVersion === e.articleVersion &&
              x.quote === e.quote &&
              x.start === e.start &&
              x.end === e.end,
          );
          if (
            !e.id ||
            ids.has(e.id) ||
            !e.quote?.trim() ||
            !Number.isSafeInteger(e.start) ||
            !Number.isSafeInteger(e.end) ||
            e.start < 0 ||
            e.end - e.start !== Array.from(e.quote).length ||
            !['positive', 'negative', 'neutral', 'uncertain'].includes(
              e.effect,
            ) ||
            !Number.isFinite(Date.parse(e.publishedAt ?? '')) ||
            Date.parse(e.publishedAt!) > Date.parse(value.dataAsOf) ||
            (!source && !original) ||
            (source &&
              (source.url !== e.url ||
                source.title !== e.title ||
                Date.parse(source.publishedAt) !== Date.parse(e.publishedAt!)))
          )
            fail();
          ids.add(e.id);
        }
        for (const f of s.confirmedFacts) {
          if (
            !f.text?.trim() ||
            !Array.isArray(f.evidenceIds) ||
            !f.evidenceIds.length ||
            new Set(f.evidenceIds).size !== f.evidenceIds.length ||
            f.evidenceIds.some((id) => !ids.has(id))
          )
            fail();
        }
        const effects = new Set(s.evidence.map((e) => e.effect));
        const computed =
          effects.has('uncertain') || s.targetVerdict === 'insufficient'
            ? 'undetermined'
            : effects.has('positive') && effects.has('negative')
              ? 'mixed'
              : effects.has('positive')
                ? 'positive'
                : effects.has('negative')
                  ? 'negative'
                  : 'undetermined';
        if (s.label !== computed) fail();
      }
      const evidence = new Set<string>();
      for (const e of a.evidence) {
        if (
          !e.id ||
          evidence.has(e.id) ||
          !e.quote?.trim() ||
          !e.articleId ||
          !e.articleVersion ||
          !['positive', 'negative', 'neutral', 'uncertain'].includes(
            e.effect,
          ) ||
          !Number.isSafeInteger(e.start) ||
          !Number.isSafeInteger(e.end) ||
          e.start < 0 ||
          e.end <= e.start ||
          (e.publishedAt !== null &&
            (!Number.isFinite(Date.parse(e.publishedAt)) ||
              Date.parse(e.publishedAt) > Date.parse(value.dataAsOf)))
        )
          fail();
        evidence.add(e.id);
      }
    }
    if (
      (c.status === 'available') !==
      c.assessments.some((a) => a.status === 'verified')
    )
      fail();
  }
  if (
    (value.status === 'available') !==
    value.companies.some((c) => c.status === 'available')
  )
    fail();
}
