// 이슈 관제(요구 76): 원장 상태 요약 + [후보 | 그래프 버전 | 작업] 탭.
// 탭·선택한 후보·작업은 주소(?tab=&candidate=&job=)에 둬서 새로고침·공유·뒤로 가기에 남는다.
import { Database, GitBranch, ListChecks, Workflow } from "lucide-react";
import { useSearchParams } from "react-router";
import { ErrorState, SkeletonLines } from "@/components/ui/feedback";
import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/ui/tabs";
import { usePipelineOverview } from "../api";
import { formatCount } from "../format";
import { candidateStatusSpec, graphDbStatusSpec, Status } from "../labels";
import { CandidatesPanel } from "../pipeline/candidates";
import { JobsPanel } from "../pipeline/jobs";
import { VersionsPanel } from "../pipeline/versions";
import { AdminPageHeader, KstTime, Metric } from "../ui";

const tabs = ["candidates", "versions", "jobs"] as const;
type PipelineTab = (typeof tabs)[number];

function Overview() {
  const overview = usePipelineOverview();
  if (overview.isPending) return <SkeletonLines lines={2} label="원장 상태를 불러오고 있어요" />;
  if (overview.isError) return <ErrorState error={overview.error} title="원장 상태를 불러오지 못했어요" onRetry={() => void overview.refetch()} compact />;
  const o = overview.data;
  const neo4j = o.projection.neo4j;
  return (
    <dl className="grid grid-cols-5 gap-x-6 gap-y-3 border-y border-border-subtle py-4">
      <Metric
        icon={ListChecks}
        label="후보 판정"
        value={`${formatCount(o.candidates.active)}건`}
        detail={
          <span className="tabular-nums">
            {candidateStatusSpec.ALLOW.label} {formatCount(o.candidates.allow)} · {candidateStatusSpec.HOLD.label} {formatCount(o.candidates.hold)} · {candidateStatusSpec.REJECT.label}{" "}
            {formatCount(o.candidates.reject)}
          </span>
        }
      />
      <Metric label="검수 대기(보류)" value={`${formatCount(o.review.holdPendingReview)}건`} detail={`검수 결정 ${formatCount(o.review.decisions)}건 · 리비전 ${o.review.revision}`} />
      <Metric
        icon={GitBranch}
        label="사용자에게 보이는 버전"
        value={o.publication.activeVersionId}
        detail={o.publication.ledgerMatchesActive ? "원장과 같아요" : `원장에만 있는 이슈 ${formatCount(o.publication.issuesOnlyInLedger.length)}건`}
      />
      <Metric
        icon={Database}
        label="GraphDB 반영"
        value={<Status spec={graphDbStatusSpec[o.projection.status]} className="text-lg" />}
        detail={
          neo4j?.status === "reachable"
            ? `반영 ${formatCount(neo4j.issuesProjected)}/${formatCount(neo4j.issuesInLedger)} · 대기 작업 ${formatCount(o.projection.pendingJobs)}`
            : `GraphDB 연결 안 됨${neo4j?.error ? `: ${neo4j.error.message}` : ""}`
        }
      />
      <Metric
        icon={Workflow}
        label="원장 확인"
        value={<KstTime value={o.ledger.checkedAt} seconds className="text-base" />}
        detail={`이슈 ${formatCount(o.issues.approved)} · 관계 ${formatCount(o.issues.relations)} · 기사 ${formatCount(o.issues.articles)}`}
      />
    </dl>
  );
}

export function AdminPipelinePage() {
  const [params, setParams] = useSearchParams();
  const tabParam = params.get("tab");
  const tab: PipelineTab = tabs.includes(tabParam as PipelineTab) ? (tabParam as PipelineTab) : "candidates";

  const update = (patch: Record<string, string | null>) => {
    const next = new URLSearchParams(params);
    for (const [key, value] of Object.entries(patch)) {
      if (value === null) next.delete(key);
      else next.set(key, value);
    }
    setParams(next);
  };

  return (
    <>
      <AdminPageHeader title="이슈 관제" icon={Workflow} />
      <Overview />
      <Tabs value={tab} onValueChange={(value) => update({ tab: value === "candidates" ? null : value })} className="flex flex-col gap-4">
        <TabsList className="max-w-xl">
          <TabsTrigger value="candidates">
            <ListChecks aria-hidden="true" />
            후보
          </TabsTrigger>
          <TabsTrigger value="versions">
            <GitBranch aria-hidden="true" />
            그래프 버전
          </TabsTrigger>
          <TabsTrigger value="jobs">
            <Workflow aria-hidden="true" />
            작업
          </TabsTrigger>
        </TabsList>
        <TabsContent value="candidates">
          <CandidatesPanel selectedId={params.get("candidate")} onSelect={(id) => update({ candidate: id })} />
        </TabsContent>
        <TabsContent value="versions">
          <VersionsPanel />
        </TabsContent>
        <TabsContent value="jobs">
          <JobsPanel selectedId={params.get("job")} onSelect={(id) => update({ job: id })} />
        </TabsContent>
      </Tabs>
    </>
  );
}
