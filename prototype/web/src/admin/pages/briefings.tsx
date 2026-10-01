// 브리핑 운영(요구 79·80): 회차별 데이터 기준 시점·생성/검증/발행 상태·실패 사유, 미발행 회차 재처리,
// 발행본 정정 등록·제공 중단/재개. 발행 원문은 바뀌지 않고, 정정은 원문 옆에 따로 쌓인다.
import { Ban, CirclePlay, FilePen, Newspaper, RotateCw, TriangleAlert, X } from "lucide-react";
import { useState } from "react";
import { useSearchParams } from "react-router";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { EmptyState, ErrorState, SkeletonLines, SkeletonRows } from "@/components/ui/feedback";
import { Select } from "@/components/ui/select";
import { useToast } from "@/components/ui/toast";
import { useAdminBriefing, useAdminBriefings, useBriefingSuspension, useCreateCorrection, useReprocessBriefing, type Round } from "../api";
import { formatCount } from "../format";
import { editionLabel, roundStatusSpec, stageStatusSpec, Status } from "../labels";
import { ReasonDialog } from "../reason-dialog";
import { AdminPageHeader, AdminSection, DataTable, KstTime, SelectableRow, StatusLabel, Td, Th } from "../ui";

const stageNames = [
  ["generate", "생성"],
  ["verify", "검증"],
  ["publish", "발행"],
] as const;

function StageList({ stages }: { stages: Round["stages"] }) {
  return (
    <ul className="flex gap-3" aria-label="단계별 상태">
      {stageNames.map(([key, label]) => {
        const spec = stageStatusSpec[stages[key].status];
        return (
          <li key={key}>
            <StatusLabel icon={spec.icon} tone={spec.tone} spin={spec.spin} label={label} className="font-normal" />
            <span className="sr-only"> {spec.label}</span>
          </li>
        );
      })}
    </ul>
  );
}

export function AdminBriefingsPage() {
  const rounds = useAdminBriefings();
  const [params, setParams] = useSearchParams();
  const selectedId = params.get("round");
  const select = (id: string | null) => {
    const next = new URLSearchParams(params);
    if (id) next.set("round", id);
    else next.delete("round");
    setParams(next);
  };

  return (
    <>
      <AdminPageHeader
        title="브리핑 운영"
        icon={Newspaper}
        actions={
          rounds.data && (
            <p className="text-sm text-text-secondary tabular-nums">
              예정 출근 {rounds.data.schedule.morning} · 퇴근 {rounds.data.schedule.evening} (KST)
            </p>
          )
        }
      />
      {rounds.isPending && <SkeletonRows count={6} label="브리핑 회차를 불러오고 있어요" />}
      {rounds.isError && <ErrorState error={rounds.error} title="브리핑 회차를 불러오지 못했어요" onRetry={() => void rounds.refetch()} />}
      {rounds.data && (
        <div className="grid grid-cols-[minmax(0,1fr)_minmax(400px,520px)] gap-6">
          <DataTable caption="브리핑 회차" className="self-start">
            <thead>
              <tr>
                <Th>회차</Th>
                <Th>상태</Th>
                <Th>데이터 기준 시점</Th>
                <Th>실패 사유</Th>
                <Th className="text-right">정정</Th>
              </tr>
            </thead>
            <tbody>
              {rounds.data.items.map((round) => (
                <SelectableRow key={round.id} selected={round.id === selectedId} onSelect={() => select(round.id)}>
                  <Td>
                    <button type="button" onClick={() => select(round.id)} className="min-h-11 text-left font-medium whitespace-nowrap tabular-nums hover:underline focus-visible:-outline-offset-2">
                      {round.date} {editionLabel[round.edition]}
                    </button>
                  </Td>
                  <Td>
                    <span className="flex items-center gap-2">
                      <Status spec={roundStatusSpec[round.status]} />
                      {round.delayed && round.status !== "missing" && <Badge variant="warning">지연</Badge>}
                    </span>
                  </Td>
                  <Td>
                    <KstTime value={round.dataWindow.end} />
                  </Td>
                  <Td className="max-w-56 truncate text-text-secondary" title={round.failureReason ?? undefined}>
                    {round.failureReason ?? "–"}
                  </Td>
                  <Td className="text-right">{round.correctionCount > 0 ? formatCount(round.correctionCount) : "–"}</Td>
                </SelectableRow>
              ))}
            </tbody>
          </DataTable>
          <aside aria-label="회차 상세" className="min-w-0 border-l border-border-subtle pl-6">
            {selectedId ? (
              <RoundDetail id={selectedId} onClose={() => select(null)} />
            ) : (
              <EmptyState title="회차를 골라 주세요" description="발행 원문과 정정, 처리 기록을 보여 줘요." />
            )}
          </aside>
        </div>
      )}
    </>
  );
}

type Action = "reprocess" | "correct" | "suspend" | "resume" | null;

function RoundDetail({ id, onClose }: { id: string; onClose: () => void }) {
  const round = useAdminBriefing(id);
  const reprocess = useReprocessBriefing();
  const correct = useCreateCorrection();
  const suspension = useBriefingSuspension();
  const toast = useToast();
  const [action, setAction] = useState<Action>(null);
  const [correctionTarget, setCorrectionTarget] = useState("round");

  if (round.isPending) return <SkeletonLines lines={8} label="회차 상세를 불러오고 있어요" />;
  if (round.isError) return <ErrorState error={round.error} title="회차 상세를 불러오지 못했어요" onRetry={() => void round.refetch()} compact />;
  const r = round.data;
  const items = r.published?.items ?? [];
  const mutation = action === "reprocess" ? reprocess : action === "correct" ? correct : suspension;
  const close = (open: boolean) => {
    if (!open) {
      setAction(null);
      reprocess.reset();
      correct.reset();
      suspension.reset();
      setCorrectionTarget("round");
    }
  };
  const done = (title: string) => () => {
    close(false);
    toast({ tone: "success", title });
  };

  const confirm = ({ reason, body }: { reason: string; body: string }) => {
    if (action === "reprocess") reprocess.mutate({ id, body: { reason } }, { onSuccess: done("재처리를 요청했어요") });
    if (action === "correct")
      correct.mutate({ id, body: { eventId: correctionTarget === "round" ? null : correctionTarget, correctedText: body, reason } }, { onSuccess: done("정정을 등록했어요") });
    if (action === "suspend" || action === "resume")
      suspension.mutate({ id, body: { action, reason } }, { onSuccess: done(action === "suspend" ? "제공을 중단했어요" : "제공을 다시 시작했어요") });
  };

  const dialogCopy = {
    reprocess: { title: "브리핑 재처리", confirm: "재처리 요청", reason: "재처리 사유", icon: <RotateCw aria-hidden="true" /> },
    correct: { title: "정정 등록", confirm: "정정 등록하기", reason: "정정 사유", icon: <FilePen aria-hidden="true" /> },
    suspend: { title: "제공 중단", confirm: "제공 중단하기", reason: "사용자에게 보일 중단 사유", icon: <Ban aria-hidden="true" /> },
    resume: { title: "제공 재개", confirm: "제공 다시 시작하기", reason: "재개 사유", icon: <CirclePlay aria-hidden="true" /> },
  } as const;
  const copy = action ? dialogCopy[action] : null;

  return (
    <article aria-labelledby="round-title" className="flex flex-col gap-4 pb-6">
      <div className="flex items-start gap-2">
        <h2 id="round-title" className="flex-1 text-lg font-semibold text-text-primary tabular-nums">
          {r.date} {editionLabel[r.edition]} 브리핑
        </h2>
        <Button variant="ghost" size="icon" aria-label="회차 상세 닫기" onClick={onClose}>
          <X aria-hidden="true" />
        </Button>
      </div>
      <dl className="grid grid-cols-[auto_1fr] gap-x-4 gap-y-2 text-base">
        <dt className="text-sm text-text-secondary">상태</dt>
        <dd>
          <Status spec={roundStatusSpec[r.status]} />
        </dd>
        <dt className="text-sm text-text-secondary">단계</dt>
        <dd>
          <StageList stages={r.stages} />
        </dd>
        <dt className="text-sm text-text-secondary">데이터 범위</dt>
        <dd>
          {r.dataWindow.openStart ? "처음부터" : <KstTime value={r.dataWindow.start} />} ~ <KstTime value={r.dataWindow.end} />
        </dd>
        <dt className="text-sm text-text-secondary">발행</dt>
        <dd>
          <KstTime value={r.publishedAt} seconds />
          {r.graphVersion && <span className="ml-2 text-sm text-text-secondary">그래프 {r.graphVersion}</span>}
        </dd>
        <dt className="text-sm text-text-secondary">시도</dt>
        <dd className="tabular-nums">{formatCount(r.attempts)}회</dd>
      </dl>
      {r.failureReason && (
        <p role="alert" className="flex items-start gap-2 text-base text-text-primary">
          <TriangleAlert className="mt-0.5 size-5 shrink-0 text-error" aria-hidden="true" />
          {r.failureReason}
        </p>
      )}
      {r.suspension && (
        <p className="flex items-start gap-2 text-base text-text-primary">
          <Ban className="mt-0.5 size-5 shrink-0 text-error" aria-hidden="true" />
          <span>
            제공 중단: {r.suspension.reason} <span className="text-sm text-text-secondary">(<KstTime value={r.suspension.at} /> · {r.suspension.adminEmail})</span>
          </span>
        </p>
      )}

      <div className="flex flex-wrap items-center gap-2 border-y border-border-subtle py-3">
        <Button variant="secondary" disabled={!r.reprocessable} onClick={() => setAction("reprocess")}>
          <RotateCw aria-hidden="true" />
          재처리
          <span className="text-sm font-normal text-text-secondary">무료</span>
        </Button>
        <Button variant="secondary" disabled={!r.published} onClick={() => setAction("correct")}>
          <FilePen aria-hidden="true" />
          정정 등록
        </Button>
        {r.status === "suspended" ? (
          <Button variant="secondary" onClick={() => setAction("resume")}>
            <CirclePlay aria-hidden="true" />
            제공 재개
          </Button>
        ) : (
          <Button variant="secondary" disabled={!r.published} onClick={() => setAction("suspend")}>
            <Ban aria-hidden="true" />
            제공 중단
          </Button>
        )}
        {!r.reprocessable && r.blockedReason && <p className="w-full text-sm text-text-secondary">재처리할 수 없어요: {r.blockedReason}</p>}
      </div>

      <AdminSection title="발행 원문과 정정" icon={Newspaper} id="round-content">
        {!r.published ? (
          <p className="text-base text-text-secondary">발행된 원문이 없어요.</p>
        ) : (
          <div className="grid grid-cols-2 gap-4">
            <section aria-labelledby="round-original" className="flex min-w-0 flex-col gap-2">
              <h3 id="round-original" className="text-base font-semibold text-text-primary">
                발행 원문
              </h3>
              {items.length === 0 ? (
                <p className="text-base text-text-secondary">담긴 핵심 이슈가 없어요.</p>
              ) : (
                <ol className="flex flex-col divide-y divide-border-subtle">
                  {items.map((item) => (
                    <li key={item.eventId} className="flex flex-col gap-1 py-2">
                      <p className="text-base font-medium text-text-primary">
                        <span className="text-text-secondary tabular-nums">{item.rank}. </span>
                        {item.title}
                      </p>
                      <p className="text-sm text-text-secondary">{item.reason}</p>
                    </li>
                  ))}
                </ol>
              )}
            </section>
            <section aria-labelledby="round-corrections" className="flex min-w-0 flex-col gap-2">
              <h3 id="round-corrections" className="text-base font-semibold text-text-primary">
                정정 {formatCount(r.corrections.length)}
              </h3>
              {r.corrections.length === 0 ? (
                <p className="text-base text-text-secondary">등록된 정정이 없어요.</p>
              ) : (
                <ol className="flex flex-col divide-y divide-border-subtle">
                  {r.corrections.map((c) => (
                    <li key={c.id} className="flex flex-col gap-1 py-2">
                      {c.original && <p className="text-sm text-text-secondary line-through decoration-text-tertiary">원문: {c.original}</p>}
                      <p className="text-base text-text-primary">
                        <FilePen className="mr-1 inline size-4 text-text-secondary" aria-label="정정" />
                        {c.corrected}
                      </p>
                      <p className="text-sm text-text-secondary">
                        사유 {c.reason} · <KstTime value={c.createdAt} /> · {c.adminEmail}
                      </p>
                    </li>
                  ))}
                </ol>
              )}
            </section>
          </div>
        )}
      </AdminSection>

      <AdminSection title="처리 기록" id="round-attempts">
        {r.attemptsLog.length === 0 ? (
          <p className="text-base text-text-secondary">아직 처리 기록이 없어요.</p>
        ) : (
          <DataTable caption="회차 처리 기록">
            <thead>
              <tr>
                <Th>#</Th>
                <Th>시작</Th>
                <Th>상태</Th>
                <Th>요청</Th>
                <Th>실패 사유</Th>
              </tr>
            </thead>
            <tbody>
              {r.attemptsLog.map((a) => (
                <tr key={a.n}>
                  <Td>{a.n}</Td>
                  <Td>
                    <KstTime value={a.startedAt} seconds />
                  </Td>
                  <Td>
                    <Status spec={roundStatusSpec[a.status as Round["status"]]} />
                  </Td>
                  <Td className="text-text-secondary">{a.trigger === "scheduler" ? "예약" : (a.adminEmail ?? "관리자")}</Td>
                  <Td className="text-text-secondary">{a.failureReason ?? "–"}</Td>
                </tr>
              ))}
            </tbody>
          </DataTable>
        )}
      </AdminSection>

      <ReasonDialog
        key={action ?? "closed"}
        open={action !== null}
        onOpenChange={close}
        title={copy?.title ?? ""}
        target={
          <p className="tabular-nums">
            {r.date} {editionLabel[r.edition]} 브리핑
          </p>
        }
        bodyLabel={action === "correct" ? "정정 내용" : undefined}
        reasonLabel={copy?.reason}
        confirmLabel={copy?.confirm ?? ""}
        confirmIcon={copy?.icon}
        pending={mutation.isPending}
        error={mutation.error}
        onConfirm={confirm}
      >
        {action === "correct" && (
          <Select
            label="정정할 항목"
            value={correctionTarget}
            onValueChange={setCorrectionTarget}
            options={[{ value: "round", label: "회차 전체" }, ...items.map((item) => ({ value: item.eventId, label: `${item.rank}. ${item.title}` }))]}
          />
        )}
        {action === "reprocess" && <p className="text-sm text-text-secondary">규칙 기반 생성이라 모델을 호출하지 않아요(무료).</p>}
        {action === "suspend" && <p className="text-sm text-text-secondary">중단 사유는 사용자 화면에 그대로 보여요. 내부 정보는 적지 마세요.</p>}
      </ReasonDialog>
    </article>
  );
}
