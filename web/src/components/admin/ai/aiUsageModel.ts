import type { AiUsageDay } from '@/types/admin/briefings';

// A-ADM-04b AI 사용량 보기별 기능 묶음과 날짜별 합계(AiUsageCharts가 그린다).

export type AiUsageView = 'all' | 'briefing' | 'chatbot';

/** 화면별로 묶는 기능. 브리핑 전망(briefing-outlook)은 브리핑 비용에 넣는다. */
export const VIEW_FEATURES: Record<AiUsageView, string[] | null> = {
  all: null,
  briefing: ['briefing', 'briefing-outlook'],
  chatbot: ['chatbot'],
};

/** 합계 구성값을 모두 알아야 더한다. 일부라도 모르면 부분합을 전체처럼 보이지 않는다. */
export function sum(values: (number | null)[]) {
  if (values.length === 0 || values.some((value) => value === null))
    return null;
  return (values as number[]).reduce((a, b) => a + b, 0);
}

export type DayTotals = {
  date: string;
  input: number | null;
  output: number | null;
  calls: number | null;
  /** 기능마다 실제 청구액이 있으면 실제, 없으면 추정을 더한 값 */
  cost: number | null;
  /** 더한 값이 모두 실제면 actual, 모두 추정이면 estimated, 섞였으면 mixed */
  costKind: 'actual' | 'estimated' | 'mixed' | null;
};

/** 날짜별 사용량을 화면의 기능 묶음으로 합친다. */
export function totalsByDay(days: AiUsageDay[], view: AiUsageView) {
  const allowed = VIEW_FEATURES[view];
  return [...days]
    .sort((a, b) => a.date.localeCompare(b.date))
    .map<DayTotals>((day) => {
      const rows = day.features.filter(
        (row) => !allowed || allowed.includes(row.feature),
      );
      const costs = rows.map((row) =>
        row.actualCost !== null
          ? { value: row.actualCost, actual: true }
          : row.estimatedCost !== null
            ? { value: row.estimatedCost, actual: false }
            : null,
      );
      const cost = sum(costs.map((entry) => entry?.value ?? null));
      const knownCosts = costs.filter((entry) => entry !== null);
      const actualCount = knownCosts.filter((entry) => entry.actual).length;
      return {
        date: day.date,
        input: sum(rows.map((row) => row.inputTokens)),
        output: sum(rows.map((row) => row.outputTokens)),
        calls: sum(rows.map((row) => row.modelCalls)),
        cost,
        costKind:
          cost === null
            ? null
            : actualCount === knownCosts.length
              ? 'actual'
              : actualCount === 0
                ? 'estimated'
                : 'mixed',
      };
    });
}
