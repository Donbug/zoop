import { useState } from 'react';
import { PageHeader, Tabs } from '@/components/admin/common/AdminUi';
import AnalysisCandidates from '@/components/admin/pipeline/AnalysisCandidates';
import PipelineOverview from '@/components/admin/pipeline/PipelineOverview';
import PublicationRules from '@/components/admin/pipeline/PublicationRules';
import AnalysisJobs from '@/components/admin/pipeline/AnalysisJobs';
import GraphVersions from '@/components/admin/pipeline/GraphVersions';
import { useRouteQuery } from '@/hooks/useRouteQuery';

type PipelineTab = 'candidates' | 'versions' | 'jobs';

const TABS: { value: PipelineTab; label: string }[] = [
  { value: 'candidates', label: '후보' },
  { value: 'versions', label: '그래프 버전' },
  { value: 'jobs', label: '작업' },
];

// A-ADM-03 그래프 관제·검수 (/admin/pipeline). 와이어프레임대로 개요·자동 검수 규칙 아래에 [후보 | 그래프 버전 | 작업] 탭.
// - 그래프 버전(listGraphVersions·activateGraphVersion)과 작업(listAnalysisJobs 등, #292) API를 연결한다.
// - 탭 위에 이슈 관제 개요(getPipelineOverview)를, 후보 탭에 후보 목록·상세(listAnalysisCandidates·getAnalysisCandidate)를 연결한다.
// - 고른 탭은 주소(?tab=)에 남는다. 기본은 와이어프레임처럼 후보 탭이다.
// - 자동 검수 규칙은 탭이 아니라 개요 아래에 늘 보인다. 예전 ?tab=rules 주소는 후보 탭으로 연다.
export default function PipelineReview() {
  const { params, updateQuery } = useRouteQuery();
  const requested = params.get('tab');
  const tab: PipelineTab =
    requested === 'versions' || requested === 'jobs' ? requested : 'candidates';
  // 그래프 버전 탭도 처음 열 때 읽고 그 뒤로는 숨기기만 해서 진행 중인 버전 전환과 그 결과를 잃지 않게 한다.
  const [versionsOpened, setVersionsOpened] = useState(tab === 'versions');
  if (tab === 'versions' && !versionsOpened) setVersionsOpened(true);
  // 작업 탭은 처음 열 때 읽고, 그 뒤로는 숨기기만 해서 진행 중인 다시 실행·취소를 잃지 않게 한다.
  // 그래프 버전을 바꾸면 후보 탭의 공개 표시 상태를 다시 읽는다.
  const [graphRevision, setGraphRevision] = useState(0);
  const [jobsOpened, setJobsOpened] = useState(tab === 'jobs');
  if (tab === 'jobs' && !jobsOpened) setJobsOpened(true);

  return (
    <div className="flex flex-col gap-5 py-8 text-zoop-ink">
      <PageHeader title="이슈 관제" />
      <PipelineOverview onOpenJobs={() => updateQuery({ tab: 'jobs' })} />
      <PublicationRules />
      <Tabs
        label="그래프 관제 보기"
        value={tab}
        options={TABS}
        variant="line"
        onChange={(next) =>
          updateQuery({ tab: next === 'candidates' ? null : next })
        }
      />
      {/* 다른 탭으로 옮겨도 필터·더 보기 결과를 잃지 않도록 숨기기만 한다. */}
      <div hidden={tab !== 'candidates'}>
        <AnalysisCandidates graphRevision={graphRevision} />
      </div>
      {versionsOpened && (
        <div hidden={tab !== 'versions'}>
          <GraphVersions
            onActivated={() => setGraphRevision((value) => value + 1)}
          />
        </div>
      )}
      {jobsOpened && (
        <div hidden={tab !== 'jobs'}>
          <AnalysisJobs />
        </div>
      )}
    </div>
  );
}
