import { PageHeader, Segmented, Tabs } from '@/components/admin/common/AdminUi';
import {
  parseWindow,
  windowOptions,
} from '@/components/admin/stats/statsWindow';
import {
  CompanyRankingPanel,
  StatsSummaryPanel,
} from '@/components/admin/stats/UsageStatistics';
import { useRouteQuery } from '@/hooks/useRouteQuery';

type StatsTab = 'summary' | 'companies';

// A-ADM-02 이용 통계 (FS065). 기간(7일·30일·전체)과 탭은 주소에 남아 새로 고쳐도 유지된다.
export default function AdminStatsPage() {
  const { params, updateQuery } = useRouteQuery();
  const window = parseWindow(params.get('window'));
  const tab: StatsTab =
    params.get('tab') === 'companies' ? 'companies' : 'summary';

  return (
    <div
      className="flex flex-col gap-5 py-8 text-zoop-ink"
      data-screen-id="A-ADM-02"
    >
      <PageHeader
        title="이용 통계"
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
      <Tabs
        label="이용 통계 보기"
        value={tab}
        options={[
          { value: 'summary', label: '요약' },
          { value: 'companies', label: '종목 순위' },
        ]}
        onChange={(value) =>
          updateQuery(
            { tab: value === 'summary' ? null : value },
            { replace: true },
          )
        }
      />
      <div role="tabpanel" className="flex flex-col gap-6">
        {tab === 'summary' ? (
          <StatsSummaryPanel window={window} />
        ) : (
          <CompanyRankingPanel window={window} />
        )}
      </div>
    </div>
  );
}
