import { useCallback } from 'react';
import { getPersonalizedBriefing } from '@/apis/briefing/briefing';
import { getPortfolio } from '@/apis/portfolio/portfolio';
import { getSettings } from '@/apis/settings/settings';
import { useAsyncData } from '@/hooks/useAsyncData';
import { selectMemberId, useAuthStore } from '@/stores/useAuthStore';
import type { BriefingResponse } from '@/types/briefing';

export type PersonalBasis =
  | {
      kind: 'holdings';
      names: string[];
      weights: (number | null)[];
      valuationAt: string | null;
    }
  | { kind: 'watchlist'; count: number; ids: string[]; names: string[] }
  | { kind: 'none' };
export type PersonalBriefingState =
  | { status: 'idle' }
  | { status: 'loading' }
  | { status: 'error'; error: unknown }
  | {
      status: 'ready';
      basis: PersonalBasis;
      briefing: BriefingResponse | null;
    };

function sameValue(a: unknown, b: unknown): boolean {
  if (a === b) return true;
  if (Array.isArray(a) || Array.isArray(b))
    return (
      Array.isArray(a) &&
      Array.isArray(b) &&
      a.length === b.length &&
      a.every((value, i) => sameValue(value, b[i]))
    );
  if (a && b && typeof a === 'object' && typeof b === 'object') {
    const left = a as Record<string, unknown>,
      right = b as Record<string, unknown>;
    const keys = Object.keys(left);
    return (
      keys.length === Object.keys(right).length &&
      keys.every(
        (key) => Object.hasOwn(right, key) && sameValue(left[key], right[key]),
      )
    );
  }
  return false;
}

/** FS036: annotate the same published round; never accept a new publication as personalization. */
export function usePersonalBriefing(round: BriefingResponse | null) {
  const memberId = useAuthStore(selectMemberId);
  const revision = useAuthStore((s) => s.sessionRevision);
  const load = useCallback(async (): Promise<PersonalBriefingState> => {
    if (!round || !memberId) return { status: 'idle' };
    const current = () => {
      if (useAuthStore.getState().sessionRevision !== revision)
        throw new Error('계정이 변경됐어요.');
    };
    current();
    const portfolio = await getPortfolio();
    current();
    const holdings = portfolio.connected ? portfolio.holdings : [];
    let basis: PersonalBasis;
    let ids: string[];
    if (holdings.length) {
      ids = holdings.map((h) => h.companyId);
      basis = {
        kind: 'holdings',
        names: holdings.map((h) => h.name),
        weights: holdings.map((h) => h.weight ?? null),
        valuationAt: portfolio.valuation?.calculatedAt ?? null,
      };
    } else {
      const settings = await getSettings();
      current();
      ids = settings.watchlistIds;
      const labels = new Map(
        round.items.flatMap((item) =>
          item.companies.map((company) => [company.id, company.name] as const),
        ),
      );
      basis = ids.length
        ? {
            kind: 'watchlist',
            count: ids.length,
            ids,
            names: ids.map((id) => labels.get(id) ?? id),
          }
        : { kind: 'none' };
    }
    if (basis.kind === 'none')
      return { status: 'ready', basis, briefing: null };
    const briefing = await getPersonalizedBriefing(round.id);
    current();
    const fields = [
      'id',
      'date',
      'edition',
      'status',
      'graphVersion',
      'marketSummary',
      'marketVariables',
    ] as const;
    const itemFields = [
      'eventId',
      'rank',
      'title',
      'eventTime',
      'timePrecision',
      'summary',
      'reason',
      'evidenceIds',
      'evidenceCount',
      'companies',
    ] as const;
    if (
      fields.some((key) => !sameValue(briefing[key], round[key])) ||
      (['dataAsOf', 'publishedAt', 'generatedAt'] as const).some((key) =>
        round[key] === null
          ? briefing[key] !== null
          : Date.parse(briefing[key] ?? '') !== Date.parse(round[key]!),
      ) ||
      briefing.metadata.graphVersion !== round.metadata.graphVersion ||
      Date.parse(briefing.metadata.asOf) !== Date.parse(round.metadata.asOf) ||
      briefing.items.length !== round.items.length ||
      briefing.items.some(
        (item, i) =>
          itemFields.some(
            (key) => !sameValue(item[key], round.items[i][key]),
          ) ||
          !Array.isArray(item.matchedCompanyIds) ||
          item.matchedCompanyIds.some(
            (id) =>
              !ids.includes(id) ||
              !item.companies.some((company) => company.id === id),
          ),
      )
    )
      throw new Error(
        '선택한 발행본·기준 종목과 개인화 응답이 일치하지 않아요.',
      );
    return { status: 'ready', basis, briefing };
  }, [round, memberId, revision]);
  const result = useAsyncData(load);
  const state: PersonalBriefingState =
    !round || !memberId
      ? { status: 'idle' }
      : result.status === 'loading'
        ? { status: 'loading' }
        : result.status === 'error'
          ? { status: 'error', error: result.error }
          : result.data!;
  return { state, reload: result.reload };
}
