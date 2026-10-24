import { useState } from 'react';
import { Empty, PageHeader, Tabs } from '@/components/admin/common/AdminUi';
import AnalysisJobs from '@/components/admin/pipeline/AnalysisJobs';
import GraphVersions from '@/components/admin/pipeline/GraphVersions';
import { useRouteQuery } from '@/hooks/useRouteQuery';

type PipelineTab = 'candidates' | 'versions' | 'jobs';

const TABS: { value: PipelineTab; label: string }[] = [
  { value: 'candidates', label: '후보' },
  { value: 'versions', label: '그래프 버전' },
  { value: 'jobs', label: '작업' },
];

// A-ADM-03 그래프 관제·검수 (/admin/pipeline). 와이어프레임의 [후보 | 그래프 버전 | 작업] 탭.
// - 그래프 버전(listGraphVersions·activateGraphVersion)과 작업(listAnalysisJobs 등, #292) API를 연결한다.
// - 후보 검수 API(listAnalysisCandidates 등)는 아직 없어 준비 중으로 둔다.
// - 고른 탭은 주소(?tab=)에 남는다. 기본은 연결된 그래프 버전 탭이다.
export default function PipelineReview() {
  const { params, updateQuery } = useRouteQuery();
  const requested = params.get('tab');
  const tab: PipelineTab =
    requested === 'candidates' || requested === 'jobs' ? requested : 'versions';
  // 작업 탭은 처음 열 때 읽고, 그 뒤로는 숨기기만 해서 진행 중인 다시 실행·취소를 잃지 않게 한다.
  const [jobsOpened, setJobsOpened] = useState(tab === 'jobs');
  if (tab === 'jobs' && !jobsOpened) setJobsOpened(true);

  return (
    <div className="flex flex-col gap-5 py-8 text-zoop-ink">
      <PageHeader title="이슈 관제" />
      <Tabs
        label="그래프 관제 보기"
        value={tab}
        options={TABS}
        onChange={(next) =>
          updateQuery({ tab: next === 'versions' ? null : next })
        }
      />
      {/* 다른 탭으로 옮겨도 진행 중인 버전 전환과 그 결과를 잃지 않도록 숨기기만 한다. */}
      <div hidden={tab !== 'versions'}>
        <GraphVersions />
      </div>
      {tab === 'candidates' && (
        <Empty>
          후보 검수는 아직 준비 중이에요. 검수 API가 생기면 연결해요.
        </Empty>
      )}
      {jobsOpened && (
        <div hidden={tab !== 'jobs'}>
          <AnalysisJobs />
        </div>
      )}
    </div>
  );
}
