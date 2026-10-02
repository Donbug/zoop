// 작업(요구 76): 실행 중·지난 작업 목록, 상세 로그, 재시도·취소. 실행 중 작업이 있으면 5초마다 갱신.
// GraphDB 반영 재시도는 모델 호출이 없는 무료 작업, 모델 오류 재처리·신규 기사 처리는 유료 작업(확인 대화상자 필수).
// 작업은 동시에 하나만 돌 수 있어, 잠겨 있으면 실행 버튼을 끄고 이유를 옆에 적는다.
// 실패·취소 작업은 다시 실행할 수 있는지와 그 이유(FS067-03)를, 기사 처리 작업은 신규 0건 성공과 확인 못 한 실패를
// 구분해(FS058) 보여 준다.
import { Ban, CircleDollarSign, Database, RotateCw, Sparkles, Terminal, X } from "lucide-react";
import { useState } from "react";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { EmptyState, ErrorState, SkeletonLines, SkeletonRows } from "@/components/ui/feedback";
import { useToast } from "@/components/ui/toast";
import { useCancelJob, useCreateJob, useJob, useJobs, useRetryJob, type IngestBaseline, type Job } from "../api";
import { formatCount, formatDurationMs } from "../format";
import { ingestOutcomeSpec, jobKindLabel, jobStatusSpec, Status } from "../labels";
import { PaidRunDialog } from "../paid-run-dialog";
import { ReasonDialog } from "../reason-dialog";
import { AdminSection, DataTable, KstTime, SelectableRow, StatusLabel, Td, Th } from "../ui";

function PaidMark({ paid }: { paid: boolean }) {
  return paid ? <StatusLabel icon={CircleDollarSign} label="유료" tone="warning" /> : <StatusLabel icon={Database} label="무료" tone="neutral" />;
}

/** 작업 실행·재시도 확인 창 상태. retryOf가 있으면 그 작업의 재시도. */
type Launch = { kind: string; paid: boolean; retryOf?: Job } | null;

/** 다음 기사 처리가 시작할 기준 시점: 정상 종료한 가장 최근 기사 처리의 시작 시각. 실패·취소는 옮기지 않는다. */
function IngestBaselineLine({ baseline }: { baseline: IngestBaseline }) {
  if (!baseline.at && baseline.unresolvedFailures === 0) return null;
  return (
    <div className="flex flex-col gap-1">
      <dl className="flex flex-wrap items-center gap-x-6 gap-y-1 text-base">
        <div className="flex flex-wrap items-center gap-x-2">
          <dt className="text-sm font-medium text-text-secondary">기사 처리 기준 시점</dt>
          <dd className="flex flex-wrap items-center gap-x-2">
            <KstTime value={baseline.at} seconds />
            {baseline.outcome && <Status spec={ingestOutcomeSpec[baseline.outcome]} />}
          </dd>
        </div>
        {baseline.unresolvedFailures > 0 && (
          <div className="flex items-center gap-x-2">
            <dt className="text-sm font-medium text-text-secondary">다시 처리할 실패</dt>
            <dd className="tabular-nums">{formatCount(baseline.unresolvedFailures)}건</dd>
          </div>
        )}
      </dl>
      <p className="text-sm text-text-secondary">정상 종료한 가장 최근 기사 처리의 시작 시각이에요. 실패·취소는 옮기지 않아요.</p>
    </div>
  );
}

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

  const paidTitle = launch ? `${jobKindLabel[launch.kind] ?? "유료 작업"}${launch.retryOf ? " 다시 실행" : ""}` : "";

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
        <IngestBaselineLine baseline={data.ingest} />
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
                    {job.ingest?.newArticles != null && <span className="block text-sm text-text-secondary">신규 기사 {formatCount(job.ingest.newArticles)}건</span>}
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
          <JobDetail
            id={selectedId}
            lockReason={lockReason}
            paidBlocked={paidBlocked}
            retryRule={data.retryRule}
            onSelect={onSelect}
            onClose={() => onSelect(null)}
            onRetry={(job) => setLaunch({ kind: job.kind, paid: job.paid, retryOf: job })}
          />
        ) : (
          <EmptyState title="작업을 골라 주세요" description="상세 로그와 결과 보고를 보여 줘요." />
        )}
      </aside>

      {launch?.paid ? (
        <PaidRunDialog
          open
          onOpenChange={closeLaunch}
          title={paidTitle}
          target={
            <p>
              {launch.kind === "ingest-run" ? "마지막으로 정상 종료한 시점부터 기사 파일을 이어서 처리해요." : "모델 호출 중 오류가 난 후보를 다시 검증해요."}
              {launch.retryOf?.dataset && <span className="block text-sm text-text-secondary">기사 파일: {launch.retryOf.dataset}</span>}
              {launch.retryOf && <span className="block text-sm text-text-secondary">재시도 대상: {launch.retryOf.id}</span>}
            </p>
          }
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
  retryRule,
  onSelect,
  onClose,
  onRetry,
}: {
  id: string;
  lockReason: string | null;
  paidBlocked: string | null;
  retryRule: string;
  onSelect: (id: string) => void;
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
  const closed = j.status === "failed" || j.status === "cancelled";
  // 작업 상태로 안 되는 이유(j.retry)가 먼저, 상태는 괜찮은데 실행 환경이 막고 있으면 그 이유.
  const retryNote = j.retry.allowed ? retryBlocked : j.retry.reason;

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
        {j.dataset && (
          <>
            <dt className="text-sm text-text-secondary">기사 파일</dt>
            <dd className="break-all">{j.dataset}</dd>
          </>
        )}
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
      <div className="flex flex-col gap-2">
        <div className="flex flex-wrap items-center gap-2">
          {closed && (
            <Button variant="secondary" disabled={!j.retry.allowed || Boolean(retryBlocked)} onClick={() => onRetry(j)}>
              <RotateCw aria-hidden="true" />
              다시 실행{j.paid ? " (유료)" : " (무료)"}
            </Button>
          )}
          {closed && j.retry.blockedBy && (
            <Button variant="ghost" onClick={() => onSelect(j.retry.blockedBy!)}>
              {j.retry.blockedBy} 보기
            </Button>
          )}
          {active && (
            <Button variant="secondary" disabled={j.cancelRequested} onClick={() => setCancelOpen(true)}>
              <Ban aria-hidden="true" />
              {j.cancelRequested ? "취소 요청됨" : "작업 취소"}
            </Button>
          )}
        </div>
        {closed && retryNote && (
          <p role="status" className="flex items-start gap-2 text-sm text-text-secondary">
            <Ban className="mt-0.5 size-4 shrink-0" aria-hidden="true" />
            {retryNote}
          </p>
        )}
        {closed && (
          <p className="flex flex-wrap items-center gap-x-2 gap-y-1 text-sm text-text-secondary">
            <span>{retryRule}</span>
            <Badge variant="warning">팀 확인 필요</Badge>
          </p>
        )}
      </div>

      {j.ingest && (
        <AdminSection title="기사 처리 결과" id="job-ingest">
          <dl className="grid grid-cols-[auto_1fr] gap-x-4 gap-y-2 text-base">
            <dt className="text-sm text-text-secondary">결과</dt>
            <dd>{j.ingest.outcome ? <Status spec={ingestOutcomeSpec[j.ingest.outcome]} /> : <span className="text-text-secondary">처리 중</span>}</dd>
            <dt className="text-sm text-text-secondary">신규 기사</dt>
            <dd className="tabular-nums">
              {j.ingest.newArticles != null ? (
                <>
                  {formatCount(j.ingest.newArticles)}건{j.ingest.duplicateArticles ? <span className="text-text-secondary"> · 이미 처리한 기사 {formatCount(j.ingest.duplicateArticles)}건 제외</span> : null}
                </>
              ) : (
                <span className="text-text-secondary">{j.ingest.outcome ? "확인하지 못했어요" : "–"}</span>
              )}
            </dd>
            <dt className="text-sm text-text-secondary">기준 시점</dt>
            <dd className="flex flex-wrap items-center gap-x-2">
              <KstTime value={j.ingest.baselineBefore} seconds />
              <span aria-hidden="true">→</span>
              <KstTime value={j.ingest.baselineAfter} seconds />
              {j.ingest.outcome && <Badge>{j.ingest.baselineAdvanced ? "옮겼어요" : "그대로예요"}</Badge>}
            </dd>
          </dl>
        </AdminSection>
      )}

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
          {j.report.collectionErrorCount > 0 && (
            <div className="flex flex-col gap-1">
              <p className="text-sm font-medium text-text-secondary">기사를 가져오는 요청 실패 {formatCount(j.report.collectionErrorCount)}건</p>
              <ul className="flex list-disc flex-col gap-1 pl-5 text-sm text-text-primary">
                {j.report.collectionErrors.map((entry, index) => (
                  <li key={index}>{[entry.stage, entry.type, entry.message].filter((part) => part != null && part !== "").map(String).join(" · ")}</li>
                ))}
              </ul>
            </div>
          )}
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
