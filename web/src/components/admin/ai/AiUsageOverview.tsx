import { useCallback } from 'react';
import { getAiUsage } from '@/apis/admin/briefings';
import {
  DailyCostChart,
  DailyTokenChart,
  FeatureShare,
  MemberRate,
} from '@/components/admin/ai/AiUsageCharts';
import {
  VIEW_FEATURES,
  totalsByDay,
  type AiUsageView,
} from '@/components/admin/ai/aiUsageModel';
import {
  Empty,
  ErrorBox,
  Loading,
  Note,
  PageHeader,
  Section,
  Segmented,
  Table,
  Tabs,
} from '@/components/admin/common/AdminUi';
import { TD, TH, count } from '@/components/admin/common/adminStyles';
import { aiSourceLabel, policyGroupLabel } from '@/constants/adminLabels';
import { useAsyncData } from '@/hooks/useAsyncData';
import { useRouteQuery } from '@/hooks/useRouteQuery';
import type { AiUsageWindow, FeatureCost } from '@/types/admin/briefings';
import { formatKst } from '@/util/format';

const WINDOWS: { value: AiUsageWindow; label: string }[] = [
  { value: '24h', label: '24시간' },
  { value: '7d', label: '7일' },
  { value: '30d', label: '30일' },
  { value: 'all', label: '전체' },
];

const VIEWS: { value: AiUsageView; label: string }[] = [
  { value: 'all', label: '전체' },
  { value: 'briefing', label: '브리핑' },
  { value: 'chatbot', label: 'AI 챗봇' },
];

const parseView = (value: string | null): AiUsageView =>
  value === 'briefing' || value === 'chatbot' ? value : 'all';

/** 날짜별·회원 수 계약 제안 필드를 서버가 아직 주지 않을 때 */
const NOT_PROVIDED = 'AI 사용량 API가 아직 이 값을 주지 않아요.';

const parseWindow = (value: string | null): AiUsageWindow =>
  WINDOWS.some((option) => option.value === value)
    ? (value as AiUsageWindow)
    : '7d';

/** 모르는 값(null)은 0이 아니라 '–'로 보여 준다(FS068). */
const known = (value: number | null) => (value === null ? '–' : count(value));

function duration(ms: number | null | undefined) {
  if (ms === null || ms === undefined) return '–';
  if (ms < 1000) return `${Math.round(ms)}ms`;
  return `${(ms / 1000).toLocaleString('ko-KR', { maximumFractionDigits: 1 })}초`;
}

function money(value: number, currency: string | null) {
  const amount = value.toLocaleString('ko-KR', { maximumFractionDigits: 4 });
  return currency ? `${amount} ${currency}` : amount;
}

/** 실제 청구 비용과 추정 비용을 따로 적는다. 둘 다 없으면 '미제공'과 이유 */
function CostCell({ cost }: { cost: FeatureCost }) {
  if (cost.actual === null && cost.estimated === null)
    return (
      <span className="text-zoop-muted">
        미제공<span className="sr-only">: {cost.reason}</span>
      </span>
    );
  return (
    <span className="flex flex-col tabular-nums">
      {cost.actual !== null && (
        <span>실제 {money(cost.actual, cost.currency)}</span>
      )}
      {cost.estimated !== null && (
        <span className="text-zoop-muted">
          추정 {money(cost.estimated, cost.currency)}
        </span>
      )}
    </span>
  );
}

const NUM = `${TD} text-right tabular-nums`;
const NUM_HEAD = `${TH} text-right whitespace-nowrap`;

// A-ADM-04b AI 사용량·오류 (FS068, getAiUsage)
// - 기능별 접수 요청과 실제 모델 호출·재사용·재시도를 구분한다. 기능 간 합계를 전체 요청 수로 쓰지 않는다.
// - 비용은 실제·추정을 구분하고, 자료가 없는 값은 0으로 바꾸지 않는다.
// - [전체 | 브리핑 | AI 챗봇] 보기(?view=)로 회원 사용 비율·날짜별 토큰·비용을 나눠 본다(강사 피드백 2026-10-24).
//   날짜별(daily)·회원 수(members)는 계약 제안 필드라, 서버가 주지 않으면 '아직 제공하지 않음'으로 둔다.
export default function AiUsageOverview() {
  const { params, updateQuery } = useRouteQuery();
  const window = parseWindow(params.get('window'));
  const view = parseView(params.get('view'));
  const viewLabel = VIEWS.find((option) => option.value === view)?.label;
  const load = useCallback(() => getAiUsage(window), [window]);
  const usage = useAsyncData(load);
  const data = usage.data;
  const allowed = VIEW_FEATURES[view];
  const features = data
    ? data.features.filter(
        (feature) => !allowed || allowed.includes(feature.feature),
      )
    : [];
  const days = data?.daily ? totalsByDay(data.daily, view) : null;
  const errors = data
    ? features.flatMap((feature) =>
        feature.recentErrors.map((error) => ({ ...error, feature })),
      )
    : [];

  return (
    <div className="flex flex-col gap-5 py-8 text-zoop-ink">
      <PageHeader
        title="AI 운영"
        actions={
          <Segmented
            label="집계 기간"
            value={window}
            options={WINDOWS}
            onChange={(value) =>
              updateQuery(
                { window: value === '7d' ? null : value },
                { replace: true },
              )
            }
          />
        }
      />
      <Tabs
        label="AI 사용량 보기"
        value={view}
        options={VIEWS}
        onChange={(next) =>
          updateQuery({ view: next === 'all' ? null : next }, { replace: true })
        }
      />
      {usage.status === 'loading' && (
        <Loading>AI 사용량을 불러오고 있어요</Loading>
      )}
      {usage.status === 'error' && (
        <ErrorBox
          title="AI 사용량을 불러오지 못했어요"
          error={usage.error}
          onRetry={usage.reload}
        />
      )}
      {data && (
        <>
          <Note>
            집계 시각 {formatKst(data.asOf)} · 비용{' '}
            {data.cost.actual === null && data.cost.estimated === null
              ? `미제공(${data.cost.reason})`
              : '실제·추정 구분 표시'}{' '}
            · 범위{' '}
            {WINDOWS.find((option) => option.value === data.window)?.label}
          </Note>
          <Section
            title={`${view === 'all' ? 'AI' : viewLabel} 사용 회원 비율`}
          >
            {data.members ? (
              <MemberRate members={data.members} view={view} />
            ) : (
              <Empty>{NOT_PROVIDED}</Empty>
            )}
          </Section>
          <Section title={`${viewLabel} 날짜별 토큰 사용량`}>
            {days ? (
              <DailyTokenChart
                title={`${viewLabel} 날짜별 토큰 사용량`}
                days={days}
              />
            ) : (
              <Empty>{NOT_PROVIDED}</Empty>
            )}
          </Section>
          <Section title={`${viewLabel} 날짜별 AI 비용`}>
            {days ? (
              <DailyCostChart
                title={`${viewLabel} 날짜별 AI 비용`}
                days={days}
                currency={data.cost.currency}
              />
            ) : (
              <Empty>{NOT_PROVIDED}</Empty>
            )}
          </Section>
          {view === 'all' && (
            <Section title="기능별 토큰 비중">
              <FeatureShare features={data.features} />
            </Section>
          )}
          <Section title="기능별 사용량">
            {features.length === 0 ? (
              <Empty>집계할 AI 기능이 없어요.</Empty>
            ) : (
              <Table caption="AI 기능별 사용량">
                <thead>
                  <tr>
                    <th className={TH}>기능</th>
                    <th className={TH}>처리 방식</th>
                    <th className={NUM_HEAD}>요청</th>
                    <th className={NUM_HEAD}>성공</th>
                    <th className={NUM_HEAD}>실패</th>
                    <th className={NUM_HEAD}>평균 처리</th>
                    <th className={NUM_HEAD}>p95</th>
                    <th className={NUM_HEAD}>실제 모델 호출</th>
                    <th className={NUM_HEAD}>재생(호출 아님)</th>
                    <th className={NUM_HEAD}>재시도</th>
                    <th className={NUM_HEAD}>입력 토큰</th>
                    <th className={NUM_HEAD}>출력 토큰</th>
                    <th className={TH}>비용</th>
                    <th className={TH}>집계 출처</th>
                  </tr>
                </thead>
                <tbody>
                  {features.map((feature) => (
                    <tr key={feature.feature}>
                      <td className={`${TD} whitespace-nowrap font-semibold`}>
                        {feature.label}
                      </td>
                      <td className={`${TD} min-w-32 text-zoop-muted`}>
                        {feature.engine}
                      </td>
                      <td className={NUM}>{count(feature.requests)}</td>
                      <td className={NUM}>{count(feature.succeeded)}</td>
                      <td className={NUM}>{count(feature.failed)}</td>
                      <td className={NUM}>
                        {duration(feature.latencyMs?.avg)}
                      </td>
                      <td className={NUM}>
                        {duration(feature.latencyMs?.p95)}
                      </td>
                      <td className={NUM}>{known(feature.usage.modelCalls)}</td>
                      <td className={NUM}>
                        {count(feature.usage.replayCalls)}
                      </td>
                      <td className={NUM}>{count(feature.usage.retries)}</td>
                      <td className={NUM}>
                        {known(feature.usage.inputTokens)}
                      </td>
                      <td className={NUM}>
                        {known(feature.usage.outputTokens)}
                      </td>
                      <td className={`${TD} whitespace-nowrap`}>
                        <CostCell cost={feature.cost} />
                      </td>
                      <td className={`${TD} whitespace-nowrap text-zoop-muted`}>
                        {aiSourceLabel[feature.source] ?? feature.source}
                      </td>
                    </tr>
                  ))}
                </tbody>
              </Table>
            )}
            {features.some((feature) => feature.note) && (
              <ul
                aria-label="집계 참고"
                className="flex flex-col gap-1 text-[11px] leading-relaxed text-zoop-muted"
              >
                {features
                  .filter((feature) => feature.note)
                  .map((feature) => (
                    <li key={feature.feature}>
                      ⓘ {feature.label}: {feature.note}
                    </li>
                  ))}
              </ul>
            )}
          </Section>

          <Section title="최근 오류">
            {errors.length === 0 ? (
              <Empty>이 기간에 기록된 오류가 없어요.</Empty>
            ) : (
              <Table caption="AI 최근 오류">
                <thead>
                  <tr>
                    <th className={TH}>시각</th>
                    <th className={TH}>기능</th>
                    <th className={TH}>코드</th>
                    <th className={TH}>내용</th>
                  </tr>
                </thead>
                <tbody>
                  {errors.map((error, index) => (
                    <tr key={`${error.feature.feature}-${error.at}-${index}`}>
                      <td
                        className={`${TD} whitespace-nowrap font-inter tabular-nums`}
                      >
                        {formatKst(error.at)}
                      </td>
                      <td className={`${TD} whitespace-nowrap`}>
                        {error.feature.label}
                      </td>
                      <td className={`${TD} font-inter`}>
                        {error.code ?? '–'}
                      </td>
                      <td className={TD}>{error.message ?? '–'}</td>
                    </tr>
                  ))}
                </tbody>
              </Table>
            )}
          </Section>

          {view === 'all' && data.pastRuns.length > 0 && (
            <Section title="뉴스 분석 실행 기록">
              <Table caption="뉴스 분석 실행 기록">
                <thead>
                  <tr>
                    <th className={TH}>실행</th>
                    <th className={TH}>정책</th>
                    <th className={NUM_HEAD}>처리</th>
                    <th className={NUM_HEAD}>승인</th>
                    <th className={NUM_HEAD}>보류</th>
                    <th className={NUM_HEAD}>거부</th>
                    <th className={NUM_HEAD}>오류</th>
                    <th className={NUM_HEAD}>모델 호출</th>
                    <th className={NUM_HEAD}>입력 토큰</th>
                    <th className={NUM_HEAD}>걸린 시간</th>
                    <th className={TH}>출처</th>
                  </tr>
                </thead>
                <tbody>
                  {data.pastRuns.map((run, index) => (
                    <tr key={run.runId ?? `${run.label}-${index}`}>
                      <td className={`${TD} font-semibold`}>{run.label}</td>
                      <td className={`${TD} text-zoop-muted`}>
                        {policyGroupLabel[run.policyGroup] ?? run.policyGroup}
                      </td>
                      <td className={NUM}>{known(run.processed)}</td>
                      <td className={NUM}>{known(run.approved)}</td>
                      <td className={NUM}>{known(run.held)}</td>
                      <td className={NUM}>{known(run.rejected)}</td>
                      <td className={NUM}>{known(run.errorCount)}</td>
                      {/* 미측정 사용량(null)은 0이 아니라 –로 둔다. */}
                      <td className={NUM}>{known(run.usage?.calls ?? null)}</td>
                      <td className={NUM}>
                        {known(run.usage?.inputTokens ?? null)}
                      </td>
                      <td className={NUM}>
                        {duration(
                          run.usage ? run.usage.elapsedSeconds * 1000 : null,
                        )}
                      </td>
                      <td className={`${TD} text-zoop-muted`}>
                        {aiSourceLabel[run.source] ?? run.source}
                      </td>
                    </tr>
                  ))}
                </tbody>
              </Table>
            </Section>
          )}
        </>
      )}
    </div>
  );
}
