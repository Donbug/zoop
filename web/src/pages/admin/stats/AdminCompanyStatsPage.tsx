import { useCallback } from 'react';
import { Link, useParams } from 'react-router-dom';
import { getCompanyInsights } from '@/apis/admin/insights';
import { ApiError } from '@/apis/auth/ApiService';
import {
  Empty,
  ErrorBox,
  Loading,
  Metric,
  Note,
  PageHeader,
  Section,
  Segmented,
  Table,
} from '@/components/admin/common/AdminUi';
import {
  FOCUS_RING,
  TD,
  TH,
  count,
} from '@/components/admin/common/adminStyles';
import {
  parseWindow,
  windowOptions,
} from '@/components/admin/stats/statsWindow';
import { useAsyncData } from '@/hooks/useAsyncData';
import { useRouteQuery } from '@/hooks/useRouteQuery';
import { formatKst } from '@/util/format';

// A-ADM-02 기업별 통계 상세 (FS065, getCompanyInsights). 종목 순위에서 기업을 고르면 열린다.
export default function AdminCompanyStatsPage() {
  const { companyId = '' } = useParams();
  const { params, updateQuery } = useRouteQuery();
  const window = parseWindow(params.get('window'));
  const load = useCallback(
    () => getCompanyInsights(companyId, window),
    [companyId, window],
  );
  const stats = useAsyncData(load);
  const data = stats.data;
  const back = `/admin/stats?tab=companies${window === '7d' ? '' : `&window=${window}`}`;
  const notFound =
    stats.status === 'error' &&
    stats.error instanceof ApiError &&
    stats.error.status === 404;

  return (
    <div
      className="flex flex-col gap-5 py-8 text-zoop-ink"
      data-screen-id="A-ADM-02"
    >
      <Link
        to={back}
        className={`self-start text-[11px] text-zoop-muted hover:text-zoop-ink ${FOCUS_RING}`}
      >
        ← 종목 순위
      </Link>
      <PageHeader
        title={data ? data.name : '기업 통계'}
        actions={
          <Segmented
            label="집계 기간"
            value={window}
            options={windowOptions}
            onChange={(value) =>
              updateQuery(
                { window: value === '7d' ? null : value },
                { replace: true },
              )
            }
          />
        }
      />
      {stats.status === 'loading' && (
        <Loading>기업 통계를 불러오고 있어요</Loading>
      )}
      {notFound && (
        <Empty>
          이 기업의 통계가 없어요. 통계에 나타난 적 없는 기업이에요.
        </Empty>
      )}
      {stats.status === 'error' && !notFound && (
        <ErrorBox
          title="기업 통계를 불러오지 못했어요"
          error={stats.error}
          onRetry={stats.reload}
        />
      )}
      {data && (
        <>
          <Note>
            {data.ticker ? `${data.ticker} · ` : ''}
            {data.inCatalog ? '' : '현재 그래프 목록에 없는 기업 · '}집계 시각{' '}
            {formatKst(data.asOf)}
          </Note>
          <dl className="grid grid-cols-2 gap-x-6 gap-y-5 border-y-[0.667px] border-zoop-line py-5 md:grid-cols-3">
            <Metric
              label="노드 조회"
              value={`${count(data.nodeViews)}회`}
              detail={`조회한 사용자 ${count(data.viewers)}명`}
            />
            <Metric
              label="간선 선택"
              value={`${count(data.edgeSelections)}회`}
              detail="이 기업에 이어진 연결선"
            />
            <Metric
              label="사건 선택"
              value={`${count(data.issueSelections)}회`}
              detail="이 기업과 연결된 사건 노드"
            />
            <Metric
              label="AI 질문"
              value={`${count(data.aiQuestions)}회`}
              detail="질문에 이 기업을 연결한 횟수"
            />
            <Metric
              label="관심 등록"
              value={`${count(data.watchlistMembers)}명`}
              detail="지금 저장된 회원 설정 기준"
            />
            <Metric
              label="가상 보유"
              value={`${count(data.holdingMembers)}명`}
              detail="연결한 가상 계좌 기준"
            />
          </dl>
          <Section title="일별 추이">
            {data.series.length === 0 ? (
              <Empty>이 기간에 이 기업의 활동이 없어요.</Empty>
            ) : (
              <Table caption={`${data.name} 일별 추이`}>
                <thead>
                  <tr>
                    <th className={TH}>날짜(KST)</th>
                    <th className={`${TH} text-right`}>노드 조회</th>
                    <th className={`${TH} text-right`}>간선 선택</th>
                    <th className={`${TH} text-right`}>사건 선택</th>
                    <th className={`${TH} text-right`}>AI 질문</th>
                  </tr>
                </thead>
                <tbody>
                  {[...data.series].reverse().map((day) => (
                    <tr key={day.date}>
                      <td className={`${TD} font-inter tabular-nums`}>
                        {day.date}
                      </td>
                      <td className={`${TD} text-right tabular-nums`}>
                        {count(day.nodeViews)}
                      </td>
                      <td className={`${TD} text-right tabular-nums`}>
                        {count(day.edgeSelections)}
                      </td>
                      <td className={`${TD} text-right tabular-nums`}>
                        {count(day.issueSelections)}
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
          <Note>{data.note}</Note>
        </>
      )}
    </div>
  );
}
