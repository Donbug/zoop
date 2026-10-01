// 작업(요구 76): 실행 중·지난 작업 목록, 상세 로그, 재시도·취소. 실행 중 작업이 있으면 5초마다 갱신.
// GraphDB 반영 재시도는 모델 호출이 없는 무료 작업, 모델 오류 재처리는 유료 작업(확인 대화상자 필수).
// 작업은 동시에 하나만 돌 수 있어, 잠겨 있으면 실행 버튼을 끄고 이유를 옆에 적는다.
import { Ban, CircleDollarSign, Database, RotateCw, Sparkles, Terminal, X } from "lucide-react";
import { useState } from "react";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { EmptyState, ErrorState, SkeletonLines, SkeletonRows } from "@/components/ui/feedback";
import { useToast } from "@/components/ui/toast";
import { useCancelJob, useCreateJob, useJob, useJobs, useRetryJob, type Job } from "../api";
import { formatCount, formatDurationMs } from "../format";
import { jobKindLabel, jobStatusSpec, Status } from "../labels";
import { PaidRunDialog } from "../paid-run-dialog";
import { ReasonDialog } from "../reason-dialog";
import { AdminSection, DataTable, KstTime, SelectableRow, StatusLabel, Td, Th } from "../ui";

function PaidMark({ paid }: { paid: boolean }) {
  return paid ? <StatusLabel icon={CircleDollarSign} label="유료" tone="warning" /> : <StatusLabel icon={Database} label="무료" tone="neutral" />;
}

/** 작업 실행·재시도 확인 창 상태. retryOf가 있으면 그 작업의 재시도. */
type Launch = { kind: string; paid: boolean; retryOf?: Job } | null;

export function JobsPanel({ selectedId, onSelect }: { selectedId: string | null; onSelect: (id: string | null) => void }) {
  const jobs = useJobs();
  const create = useCreateJob();
  const retry = useRetryJob();
  const toast = useToast();
  const [launch, setLaunch] = useState<Launch>(null);

  if (jobs.isPending) return <SkeletonRows count={4} label="작업 목록을 불러오고 있어요" />;
  if (jobs.isError) return <ErrorState error={jobs.error} title="작업 목록을 불러오지 못했어요" onRetry={() => void jobs.refetch()} />;
  const data = jobs.data;
  const lockReason = data.lock.locked ? (data.lock.reason ?? "다른 작업이 실행 중이에요.") : null;
  const sandboxReason = !data.sandbox.ready
    ? `실행 환경이 준비되지 않았어요: ${data.sandbox.problems.join(", ") || "원인 미상"}`
    : data.sandbox.policy?.match === false
      ? "실행 환경의 검증 정책이 기대값과 달라요."
      : null;
  const paidBlocked = lockReason ?? sandboxReason;
  const mutation = launch?.retryOf ? retry : create;

  const onLaunched = (result: { job: Job; deduplicated: boolean }) => {
    setLaunch(null);
    onSelect(result.job.id);
    toast({ tone: "success", title: result.deduplicated ? "같은 작업이 이미 진행 중이에요" : `${jobKindLabel[result.job.kind] ?? result.job.label}을 시작했어요` });
  };

  const run = (input: { reason: string; maxModelCalls?: number }) => {
    if (!launch) return;
    const paidFields = launch.paid ? { maxModelCalls: input.maxModelCalls, confirmPaid: true } : {};
    if (launch.retryOf) retry.mutate({ id: launch.retryOf.id, reason: input.reason, ...paidFields }, { onSuccess: onLaunched });
    else create.mutate({ kind: launch.kind as Job["kind"], reason: input.reason, ...paidFields }, { onSuccess: onLaunched });
  };

  const closeLaunch = (open: boolean) => {
    if (!open) {
      setLaunch(null);
      create.reset();
      retry.reset();
    }
  };

  return (
    <div className="grid grid-cols-[minmax(0,1fr)_minmax(400px,520px)] gap-6">
      <div className="flex min-w-0 flex-col gap-4">
        <div className="flex flex-col gap-2 border-b border-border-subtle pb-4">
          <div className="flex flex-wrap items-center gap-2">
            <Button variant="secondary" disabled={Boolean(lockReason)} onClick={() => setLaunch({ kind: "flush-graph", paid: false })}>
              <Database aria-hidden="true" />
              GraphDB 반영 재시도
              <span className="text-sm font-normal text-text-secondary">무료</span>
            </Button>
            <Button variant="secondary" disabled={Boolean(paidBlocked)} onClick={() => setLaunch({ kind: "retry-model-errors", paid: true })}>
              <Sparkles aria-hidden="true" />
              모델 오류 재처리
              <span className="text-sm font-normal text-warning">유료</span>
            </Button>
          </div>
          {paidBlocked && (
            <p role="status" className="flex items-center gap-2 text-sm text-text-secondary">
              <Ban className="size-4 shrink-0" aria-hidden="true" />
              {lockReason ? `실행할 수 없어요: ${lockReason}` : `모델 오류 재처리를 실행할 수 없어요: ${sandboxReason}`}
            </p>
          )}
        </div>
        {data.items.length === 0 ? (
          <EmptyState title="아직 실행한 작업이 없어요" />
        ) : (
          <DataTable caption="작업 목록">
            <thead>
              <tr>
                <Th>작업</Th>
                <Th>상태</Th>
                <Th>비용</Th>
                <Th>요청 시각</Th>
                <Th className="text-right">걸린 시간</Th>
              </tr>
            </thead>
            <tbody>
              {data.items.map((job) => (
                <SelectableRow key={job.id} selected={job.id === selectedId} onSelect={() => onSelect(job.id)}>
                  <Td className="whitespace-nowrap">
                    <button type="button" onClick={() => onSelect(job.id)} className="min-h-11 text-left font-medium hover:underline focus-visible:-outline-offset-2">
                      {jobKindLabel[job.kind] ?? job.label}
                    </button>
                    {job.retryOf && <Badge className="ml-2">재시도</Badge>}
                  </Td>
                  <Td>
                    <Status spec={jobStatusSpec[job.status]} />
                  </Td>
                  <Td>
                    <PaidMark paid={job.paid} />
                  </Td>
                  <Td>
                    <KstTime value={job.requestedAt} />
                  </Td>
                  <Td className="text-right">{job.durationSeconds == null ? "–" : formatDurationMs(job.durationSeconds * 1000)}</Td>
                </SelectableRow>
              ))}
            </tbody>
          </DataTable>
        )}
      </div>
      <aside aria-label="작업 상세" className="min-w-0 border-l border-border-subtle pl-6">
        {selectedId ? (
          <JobDetail id={selectedId} lockReason={lockReason} paidBlocked={paidBlocked} onClose={() => onSelect(null)} onRetry={(job) => setLaunch({ kind: job.kind, paid: job.paid, retryOf: job })} />
        ) : (
          <EmptyState title="작업을 골라 주세요" description="상세 로그와 결과 보고를 보여 줘요." />
        )}
      </aside>

      {launch?.paid ? (
        <PaidRunDialog
          open
          onOpenChange={closeLaunch}
          title={launch.retryOf ? "모델 오류 재처리 다시 실행" : "모델 오류 재처리"}
          target={<p>모델 호출 중 오류가 난 후보를 다시 검증해요.{launch.retryOf && <span className="block text-sm text-text-secondary">재시도 대상: {launch.retryOf.id}</span>}</p>}
          defaultLimit={data.limits.defaultMaxModelCalls}
          maxLimit={data.limits.maxModelCalls}
          pending={mutation.isPending}
          error={mutation.error}
          onConfirm={run}
        />
      ) : (
        <ReasonDialog
          open={launch !== null}
          onOpenChange={closeLaunch}
          title="GraphDB 반영 재시도"
          target={
            <p className="flex items-start gap-2">
              <Database className="mt-0.5 size-5 shrink-0 text-text-secondary" aria-hidden="true" />
              <span>
                승인된 이슈 중 GraphDB에 반영되지 않은 것을 다시 반영해요. <strong className="font-semibold">모델을 호출하지 않는 무료 작업이에요.</strong>
              </span>
            </p>
          }
          reasonLabel="실행 사유"
          confirmLabel="반영 재시도 실행"
          confirmIcon={<RotateCw aria-hidden="true" />}
          pending={mutation.isPending}
          error={mutation.error}
          onConfirm={run}
        />
      )}
    </div>
  );
}

function JobDetail({
  id,
  lockReason,
  paidBlocked,
  onClose,
  onRetry,
}: {
  id: string;
  lockReason: string | null;
  paidBlocked: string | null;
  onClose: () => void;
  onRetry: (job: Job) => void;
}) {
  const job = useJob(id);
  const cancel = useCancelJob();
  const [cancelOpen, setCancelOpen] = useState(false);

  if (job.isPending) return <SkeletonLines lines={8} label="작업 상세를 불러오고 있어요" />;
  if (job.isError) return <ErrorState error={job.error} title="작업 상세를 불러오지 못했어요" onRetry={() => void job.refetch()} compact />;
  const j = job.data;
  const retryBlocked = j.paid ? paidBlocked : lockReason;
  const active = j.status === "queued" || j.status === "running";

  return (
    <article aria-labelledby="job-title" className="flex flex-col gap-4">
      <div className="flex items-start gap-2">
        <h2 id="job-title" className="flex-1 text-lg font-semibold text-text-primary">
          {jobKindLabel[j.kind] ?? j.label}
        </h2>
        <Button variant="ghost" size="icon" aria-label="작업 상세 닫기" onClick={onClose}>
          <X aria-hidden="true" />
        </Button>
      </div>
      <dl className="grid grid-cols-[auto_1fr] gap-x-4 gap-y-2 text-base">
        <dt className="text-sm text-text-secondary">상태</dt>
        <dd className="flex items-center gap-2">
          <Status spec={jobStatusSpec[j.status]} />
          {j.recovered && <Badge variant="warning">재시작 복구</Badge>}
        </dd>
        <dt className="text-sm text-text-secondary">비용</dt>
        <dd>
          <PaidMark paid={j.paid} />
          {j.maxModelCalls != null && <span className="ml-2 text-sm text-text-secondary">호출 상한 {formatCount(j.maxModelCalls)}회</span>}
        </dd>
        <dt className="text-sm text-text-secondary">요청</dt>
        <dd>
          <KstTime value={j.requestedAt} seconds /> · {j.requestedBy}
        </dd>
        <dt className="text-sm text-text-secondary">시작·종료</dt>
        <dd>
          <KstTime value={j.startedAt} seconds /> ~ <KstTime value={j.finishedAt} seconds />
        </dd>
        <dt className="text-sm text-text-secondary">사유</dt>
        <dd>{j.reason}</dd>
        {j.exitCode != null && (
          <>
            <dt className="text-sm text-text-secondary">종료 코드</dt>
            <dd className="tabular-nums">{j.exitCode}</dd>
          </>
        )}
      </dl>
      {j.error && (
        <p role="alert" className="flex items-start gap-2 text-base text-text-primary">
          <X className="mt-0.5 size-5 shrink-0 text-error" aria-hidden="true" />
          <span>
            {j.error.message} <span className="text-sm text-text-secondary">({j.error.code})</span>
          </span>
        </p>
      )}
      <div className="flex flex-wrap items-center gap-2">
        {j.retryable && (
          <Button variant="secondary" disabled={Boolean(retryBlocked)} onClick={() => onRetry(j)}>
            <RotateCw aria-hidden="true" />
            다시 실행{j.paid ? " (유료)" : " (무료)"}
          </Button>
        )}
        {active && (
          <Button variant="secondary" disabled={j.cancelRequested} onClick={() => setCancelOpen(true)}>
            <Ban aria-hidden="true" />
            {j.cancelRequested ? "취소 요청됨" : "작업 취소"}
          </Button>
        )}
        {j.retryable && retryBlocked && <p className="w-full text-sm text-text-secondary">{retryBlocked}</p>}
      </div>

      {j.report && (
        <AdminSection title="실행 보고" id="job-report">
          <dl className="grid grid-cols-4 gap-x-4 gap-y-2 text-base">
            {(
              [
                ["처리", j.report.processed],
                ["승인", j.report.approved],
                ["보류", j.report.held],
                ["거부", j.report.rejected],
                ["대기", j.report.pending],
                ["오류", j.report.errorCount],
                ["모델 호출", j.report.usage.calls],
                ["입력 토큰", j.report.usage.inputTokens],
              ] as const
            ).map(([label, value]) => (
              <div key={label} className="flex flex-col">
                <dt className="text-sm text-text-secondary">{label}</dt>
                <dd className="font-semibold tabular-nums">{formatCount(value)}</dd>
              </div>
            ))}
          </dl>
        </AdminSection>
      )}
      {j.flush && <p className="text-base text-text-primary">완료한 GraphDB 반영 작업 {formatCount(j.flush.completedProjectionJobs)}건</p>}

      <AdminSection title="로그" icon={Terminal} id="job-log">
        {j.command.length > 0 && <p className="text-sm break-all text-text-secondary">{j.command.join(" ")}</p>}
        {j.logTail && j.logTail.length > 0 ? (
          <pre tabIndex={0} aria-label="작업 로그 마지막 줄들" className="max-h-96 overflow-auto bg-surface-sunken p-3 text-sm leading-relaxed whitespace-pre-wrap text-text-primary">
            {j.logTail.join("\n")}
          </pre>
        ) : (
          <p className="text-base text-text-secondary">{active ? "로그를 기다리고 있어요." : "남은 로그가 없어요."}</p>
        )}
      </AdminSection>

      <ReasonDialog
        open={cancelOpen}
        onOpenChange={(open) => {
          setCancelOpen(open);
          if (!open) cancel.reset();
        }}
        title="작업 취소"
        target={<p>{jobKindLabel[j.kind] ?? j.label} 작업을 멈춰요. 이미 처리한 결과는 원장에 남아요.</p>}
        reasonLabel="취소 사유"
        confirmLabel="작업 취소하기"
        confirmIcon={<Ban aria-hidden="true" />}
        pending={cancel.isPending}
        error={cancel.error}
        onConfirm={({ reason }) => cancel.mutate({ id: j.id, reason }, { onSuccess: () => setCancelOpen(false) })}
      />
    </article>
  );
}
