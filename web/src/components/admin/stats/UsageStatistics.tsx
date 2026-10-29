import { useAdminRefresh } from '@/hooks/useAdminRefresh';
import { useCallback } from 'react';
import { Link } from 'react-router-dom';
import { getInsightsSummary, listCompanyInsights } from '@/apis/admin/insights';
import {
  Empty,
  ErrorBox,
  Loading,
  MoreButton,
  Note,
  Section,
  Table,
} from '@/components/admin/common/AdminUi';
import { LINK, TD, TH, count } from '@/components/admin/common/adminStyles';
import { editionLabel } from '@/constants/adminLabels';
import { useAsyncData } from '@/hooks/useAsyncData';
import { useCursorPages } from '@/hooks/useCursorPages';
import type { StatsMetric, StatsWindow } from '@/types/admin/insights';
import { formatKst } from '@/util/format';
import { MetricBasis, MetricValue } from './insightsFormat';

function MetricTable({
  caption,
  metrics,
  minSample,
}: {
  caption: string;
  metrics: StatsMetric[];
  minSample: number;
}) {
  if (metrics.length === 0)
    return <Empty>이 묶음에 제공하는 지표가 없어요.</Empty>;
  return (
    <Table caption={caption}>
      <thead>
        <tr>
          <th className={TH}>지표</th>
          <th className={`${TH} text-right`}>값</th>
          <th className={`${TH} text-right`}>산식</th>
          <th className={TH}>정의</th>
        </tr>
      </thead>
      <tbody>
        {metrics.map((metric) => (
          <tr key={metric.key}>
            <td className={`${TD} whitespace-nowrap`}>{metric.label}</td>
            <td className={`${TD} text-right`}>
              <MetricValue metric={metric} />
            </td>
            <td className={`${TD} text-right text-zoop-muted`}>
              <MetricBasis metric={metric} minSample={minSample} />
            </td>
            <td className={`${TD} min-w-60 text-zoop-muted`}>
              {metric.definition}
            </td>
          </tr>
        ))}
      </tbody>
    </Table>
  );
}

/** A-ADM-02 요약: 지표(산식·정의) · 일별 추이 · 브리핑 회차별 조회 */
export function StatsSummaryPanel({ window }: { window: StatsWindow }) {
  const load = useCallback(() => getInsightsSummary(window), [window]);
  const summary = useAsyncData(load);
  useAdminRefresh(summary.reload, 10000);
  if (summary.status === 'loading')
    return <Loading>이용 통계를 불러오고 있어요</Loading>;
  if (summary.status === 'error')
    return (
      <ErrorBox
        title="이용 통계를 불러오지 못했어요"
        error={summary.error}
        onRetry={summary.reload}
      />
    );
  const data = summary.data;
  const byGroup = (group: StatsMetric['group']) =>
    data.metrics.filter(
      (metric) => metric.key !== 'onboarding' && metric.group === group,
    );
  const trend = [...data.trend].reverse();

  return (
    <>
      {summary.refreshError && (
        <p role="status" className="text-[11px] text-zoop-muted">
          새로 고치지 못했어요. 이전 결과를 표시해요.
        </p>
      )}
      <Note>
        집계 시각 {formatKst(data.asOf)} · 비율은 분모가 {data.minSample}{' '}
        미만이면 숨기고 건수만 보여 줘요.
      </Note>
      <Section title="서비스 이용">
        <MetricTable
          caption="서비스 이용 지표"
          metrics={byGroup('usage')}
          minSample={data.minSample}
        />
      </Section>
      <Section title="브리핑 관심도">
        <MetricTable
          caption="브리핑 관심도 지표"
          metrics={byGroup('interest')}
          minSample={data.minSample}
        />
      </Section>
      <Section title="AI 질문">
        <MetricTable
          caption="AI 질문 지표"
          metrics={byGroup('ai')}
          minSample={data.minSample}
        />
      </Section>
      <Section title="일별 추이">
        {trend.length === 0 ? (
          <Empty>이 기간에 집계된 날이 없어요.</Empty>
        ) : (
          <Table caption="일별 이용 추이">
            <thead>
              <tr>
                <th className={TH}>날짜(KST)</th>
                <th className={`${TH} text-right`}>활성 사용자</th>
                <th className={`${TH} text-right`}>노드 선택</th>
                <th className={`${TH} text-right`}>간선 선택</th>
                <th className={`${TH} text-right`}>브리핑 조회</th>
                <th className={`${TH} text-right`}>AI 질문</th>
              </tr>
            </thead>
            <tbody>
              {trend.map((day) => (
                <tr key={day.date}>
                  <td className={`${TD} font-inter tabular-nums`}>
                    {day.date}
                  </td>
                  <td className={`${TD} text-right tabular-nums`}>
                    {count(day.activeUsers)}
                  </td>
                  <td className={`${TD} text-right tabular-nums`}>
                    {count(day.nodeSelections)}
                  </td>
                  <td className={`${TD} text-right tabular-nums`}>
                    {count(day.edgeSelections)}
                  </td>
                  <td className={`${TD} text-right tabular-nums`}>
                    {count(day.briefingViews)}
                  </td>
                  <td className={`${TD} text-right tabular-nums`}>
                    {count(day.aiQuestions)}
                  </td>
                </tr>
              ))}
            </tbody>
          </Table>
        )}
      </Section>
      <Section title="브리핑 회차별 조회">
        {data.rounds.length === 0 ? (
          <Empty>이 기간에 브리핑을 조회하거나 평가한 기록이 없어요.</Empty>
        ) : (
          <Table caption="브리핑 회차별 조회·평가">
            <thead>
              <tr>
                <th className={TH}>회차</th>
                <th className={`${TH} text-right`}>조회</th>
                <th className={`${TH} text-right`}>조회한 사용자</th>
                <th className={`${TH} text-right`}>이슈 열기</th>
                <th className={`${TH} text-right`}>좋아요</th>
                <th className={`${TH} text-right`}>싫어요</th>
              </tr>
            </thead>
            <tbody>
              {data.rounds.map((round) => (
                <tr key={round.roundId}>
                  <td className={`${TD} whitespace-nowrap tabular-nums`}>
                    {round.date} {editionLabel[round.edition]}
                  </td>
                  <td className={`${TD} text-right tabular-nums`}>
                    {count(round.views)}
                  </td>
                  <td className={`${TD} text-right tabular-nums`}>
                    {count(round.viewers)}
                  </td>
                  <td className={`${TD} text-right tabular-nums`}>
                    {count(round.issueOpens)}
                  </td>
                  <td className={`${TD} text-right tabular-nums`}>
                    {count(round.likes)}
                  </td>
                  <td className={`${TD} text-right tabular-nums`}>
                    {count(round.dislikes)}
                  </td>
                </tr>
              ))}
            </tbody>
          </Table>
        )}
      </Section>
    </>
  );
}

/** A-ADM-02 종목 순위: 관심 등록·가상 보유·노드 조회·간선 선택·AI 질문 */
export function CompanyRankingPanel({ window }: { window: StatsWindow }) {
  const load = useCallback(
    (cursor?: string) => listCompanyInsights(window, cursor),
    [window],
  );
  const ranking = useCursorPages(load);
  useAdminRefresh(ranking.reload, 10000);
  if (ranking.status === 'loading')
    return <Loading>종목 순위를 불러오고 있어요</Loading>;
  if (ranking.status === 'error' && ranking.error)
    return (
      <ErrorBox
        title="종목 순위를 불러오지 못했어요"
        error={ranking.error}
        onRetry={ranking.reload}
      />
    );
  const first = ranking.pages[0];
  const rows = ranking.items;
  const windowQuery = window === '7d' ? '' : `?window=${window}`;

  return (
    <>
      {ranking.refreshError && (
        <p role="status" className="text-[11px] text-zoop-muted">
          새로 고치지 못했어요. 이전 결과를 표시해요.
        </p>
      )}
      <Note>
        기업 {count(first.totalCompanies)}개 중 활동이 있는 기업 · 집계 시각{' '}
        {formatKst(first.asOf)} · {first.holdingsNote}
      </Note>
      {rows.length === 0 ? (
        <Empty>
          아직 집계할 종목 활동이 없어요. 사용자가 지도에서 기업을 고르거나 관심
          종목을 저장하면 여기에 나타나요.
        </Empty>
      ) : (
        <Table caption="종목 순위">
          <thead>
            <tr>
              <th className={`${TH} w-12 text-right`}>순위</th>
              <th className={TH}>기업</th>
              <th className={`${TH} text-right`}>관심 등록(명)</th>
              <th className={`${TH} text-right`}>가상 보유(명)</th>
              <th className={`${TH} text-right`}>노드 조회</th>
              <th className={`${TH} text-right`}>간선 선택</th>
              <th className={`${TH} text-right`}>AI 질문</th>
            </tr>
          </thead>
          <tbody>
            {rows.map((row, index) => (
              <tr key={row.companyId}>
                <td className={`${TD} text-right text-zoop-muted tabular-nums`}>
                  {index + 1}
                </td>
                <td className={`${TD} whitespace-nowrap`}>
                  <Link
                    to={`/admin/stats/companies/${encodeURIComponent(row.companyId)}${windowQuery}`}
                    className={LINK}
                  >
                    {row.name}
                  </Link>
                  {row.ticker && (
                    <span className="ml-2 font-inter text-[11px] text-zoop-faint">
                      {row.ticker}
                    </span>
                  )}
                </td>
                <td className={`${TD} text-right tabular-nums`}>
                  {count(row.watchlistMembers)}
                </td>
                <td className={`${TD} text-right tabular-nums`}>
                  {count(row.holdingMembers)}
                </td>
                <td className={`${TD} text-right tabular-nums`}>
                  {count(row.nodeViews)}
                </td>
                <td className={`${TD} text-right tabular-nums`}>
                  {count(row.edgeSelections)}
                </td>
                <td className={`${TD} text-right tabular-nums`}>
                  {count(row.aiQuestions)}
                </td>
              </tr>
            ))}
          </tbody>
        </Table>
      )}
      {ranking.hasMore && (
        <MoreButton
          loading={ranking.loadingMore}
          error={ranking.moreError}
          onClick={ranking.loadMore}
        />
      )}
    </>
  );
}
