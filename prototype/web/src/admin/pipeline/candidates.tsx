// 후보 목록(통과·보류·폐기 필터, 검색) + 후보 상세(원문 인용·보류 사유·검증 판정·검수 이력·허용/거부).
// 허용·거부는 사유를 받아야만 실행된다. 거부한 후보는 사용자 그래프에서 바로 빠지고, 허용한 보류 후보는 바로 들어간다.
import { Check, ExternalLink, FileText, History, Link2Off, ListChecks, Map as MapIcon, MapPinOff, ShieldCheck, X } from "lucide-react";
import { useDeferredValue, useState } from "react";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { EmptyState, ErrorState, SkeletonLines, SkeletonRows } from "@/components/ui/feedback";
import { Input } from "@/components/ui/input";
import { Segmented } from "@/components/ui/segmented";
import { useToast } from "@/components/ui/toast";
import { relationLabel, type RelationType } from "@/lib/labels";
import { cn } from "@/lib/utils";
import { useCandidate, useCandidates, useDecideCandidate, type CandidateDetail, type CandidateFilters, type CandidateRow } from "../api";
import { formatCount } from "../format";
import { candidateStatusSpec, Status } from "../labels";
import { ReasonDialog } from "../reason-dialog";
import { DataTable, KstTime, SelectableRow, StatusLabel, Td, Th } from "../ui";

type StatusFilter = CandidateFilters["status"];

function OnUserGraph({ on }: { on: boolean }) {
  return on ? <StatusLabel icon={MapIcon} label="표시 중" tone="success" /> : <StatusLabel icon={MapPinOff} label="표시 안 함" tone="neutral" />;
}

function DecisionText({ decision }: { decision: CandidateRow["decision"] }) {
  if (!decision) return <span className="text-text-tertiary">–</span>;
  return decision.decision === "allow" ? <StatusLabel icon={Check} label="허용" tone="success" /> : <StatusLabel icon={X} label="거부" tone="error" />;
}

const ruleNotApplied = {
  admin_decision: "관리자 결정이 우선해요",
  rule_disabled: "규칙이 꺼져 있어요",
  not_published: "이 후보가 든 그래프 버전을 아직 게시하지 않았어요",
} as const;

/** 목록 행의 규칙 배지: 규칙으로 게시 중이면 규칙 id, 다루지만 게시하지 않으면 그 이유(색 없이 글자). */
function RuleBadge({ rule }: { rule: CandidateRow["rule"] }) {
  if (!rule) return null;
  const short = { admin_decision: "결정 우선", rule_disabled: "꺼짐", not_published: "미게시" } as const;
  return (
    <Badge>
      <ListChecks aria-hidden="true" />
      {rule.applied ? `규칙 ${rule.ruleId}` : `규칙 대상 · ${short[rule.notAppliedReason ?? "not_published"]}`}
    </Badge>
  );
}

function RuleState({ rule }: { rule: NonNullable<CandidateRow["rule"]> }) {
  if (rule.applied) return <StatusLabel icon={ListChecks} label={`${rule.ruleId}로 게시 중`} tone="success" />;
  return (
    <span className="flex flex-col gap-0.5">
      <StatusLabel icon={ListChecks} label={`${rule.ruleId} 대상`} />
      <span className="text-sm text-text-secondary">{ruleNotApplied[rule.notAppliedReason ?? "not_published"]}</span>
    </span>
  );
}

/** 규칙이 사용자에게 비우는(또는 비울) 역할과 게시하지 않는 관계: 모델이 적은 문구와 함께. 다른 값으로 채우지 않는다. */
function WithheldRoles({ detail }: { detail: CandidateDetail }) {
  const rule = detail.rule;
  if (!rule) return null;
  const relations = detail.relations.filter((r) => rule.withheldRelations.includes(r.relationId));
  const dropped = detail.relations.filter((r) => rule.droppedRelations.includes(r.relationId));
  const roleCount = rule.withheldParticipants.length + relations.length;
  return (
    <section aria-labelledby="candidate-withheld" className="flex flex-col gap-2">
      <h3 id="candidate-withheld" className="flex items-center gap-2 text-base font-semibold text-text-primary">
        <ListChecks className="size-4 text-text-secondary" aria-hidden="true" />
        {rule.applied ? "규칙이 비운 역할" : "규칙이 비울 역할"} {formatCount(roleCount)}
      </h3>
      {roleCount > 0 && (
        <ul className="flex flex-col divide-y divide-border-subtle">
          {rule.withheldParticipants.map((index) => {
            const p = detail.mention.participants[index];
            return (
              <li key={`p-${index}`} className="flex flex-col py-2 text-base">
                <span className="font-medium text-text-primary">{p?.name ?? `참여자 ${index + 1}`}</span>
                <span className="text-sm text-text-secondary">참여자 · 모델이 적은 역할 “{p?.role || "–"}”</span>
              </li>
            );
          })}
          {relations.map((r) => (
            <li key={r.relationId} className="flex flex-col py-2 text-base">
              <span className="font-medium text-text-primary">{relationLabel[r.relationType as RelationType] ?? r.relationType}</span>
              <span className="text-sm break-all text-text-secondary">
                {r.source} → {r.target} · 모델이 적은 역할 “{r.role ?? "–"}”
              </span>
            </li>
          ))}
        </ul>
      )}
      <p className="text-sm text-text-secondary">사용자에게는 ‘역할 미확인’으로 보여요. 다른 값으로 채우지 않아요.</p>
      {dropped.length > 0 && (
        <>
          <h3 className="mt-2 flex items-center gap-2 text-base font-semibold text-text-primary">
            <ListChecks className="size-4 text-text-secondary" aria-hidden="true" />
            {rule.applied ? "규칙이 게시하지 않은 관계" : "규칙이 게시하지 않을 관계"} {formatCount(dropped.length)}
          </h3>
          <ul className="flex flex-col divide-y divide-border-subtle">
            {dropped.map((r) => (
              <li key={r.relationId} className="flex flex-col py-2 text-base">
                <span className="font-medium text-text-primary">{relationLabel[r.relationType as RelationType] ?? r.relationType}</span>
                <span className="text-sm break-all text-text-secondary">
                  {r.source} → {r.target}
                </span>
              </li>
            ))}
          </ul>
          <p className="text-sm text-text-secondary">이 사건이 아직 일어나지 않은(계획·예정·예측) 일이라 앞선 사건의 후속으로 잇지 않아요.</p>
        </>
      )}
    </section>
  );
}

export function CandidatesPanel({ selectedId, onSelect }: { selectedId: string | null; onSelect: (id: string | null) => void }) {
  const [status, setStatus] = useState<StatusFilter>("HOLD");
  const [ruleOnly, setRuleOnly] = useState(false);
  const [query, setQuery] = useState("");
  const deferredQuery = useDeferredValue(query);
  const candidates = useCandidates({ status, ruleOnly, q: deferredQuery });
  const first = candidates.data?.pages[0];
  const rows = candidates.data?.pages.flatMap((page) => page.items) ?? [];
  const counts = first?.counts;

  const options: { value: StatusFilter; label: string }[] = [
    { value: "HOLD", label: `보류 ${counts ? formatCount(counts.HOLD) : ""}`.trim() },
    { value: "ALLOW", label: `통과 ${counts ? formatCount(counts.ALLOW) : ""}`.trim() },
    { value: "REJECT", label: `폐기 ${counts ? formatCount(counts.REJECT) : ""}`.trim() },
    { value: "ALL", label: "전체" },
  ];

  return (
    <div className="grid min-h-0 grid-cols-[minmax(0,1fr)_minmax(400px,480px)] gap-6">
      <div className="flex min-w-0 flex-col gap-3">
        <div className="flex flex-wrap items-end gap-3">
          <Segmented aria-label="판정 상태" value={status} onValueChange={setStatus} options={options} />
          <Segmented
            aria-label="규칙 대상"
            value={ruleOnly ? "rule" : "all"}
            onValueChange={(value) => setRuleOnly(value === "rule")}
            options={[
              { value: "all", label: "모든 후보" },
              { value: "rule", label: "규칙 대상만" },
            ]}
          />
          <Input
            label="후보 검색"
            hideLabel
            variant="search"
            placeholder="제목·기업·대상으로 찾기"
            value={query}
            onChange={(e) => setQuery(e.target.value)}
            onClear={() => setQuery("")}
            className="w-72"
          />
        </div>
        {candidates.isPending && <SkeletonRows count={6} label="후보를 불러오고 있어요" />}
        {candidates.isError && <ErrorState error={candidates.error} title="후보 목록을 불러오지 못했어요" onRetry={() => void candidates.refetch()} />}
        {candidates.isSuccess && rows.length === 0 && (
          <EmptyState title={query ? "검색어에 맞는 후보가 없어요" : "이 상태의 후보가 없어요"} description={query ? "다른 검색어로 찾아 보세요." : undefined} />
        )}
        {rows.length > 0 && (
          <DataTable caption="후보 목록" className="max-h-[calc(100dvh-320px)] overflow-y-auto">
            <thead>
              <tr>
                <Th>판정</Th>
                <Th>이슈</Th>
                <Th>관련 기업</Th>
                <Th className="text-right">근거</Th>
                <Th>사용자 그래프</Th>
                <Th>검수</Th>
              </tr>
            </thead>
            <tbody>
              {rows.map((row) => (
                <SelectableRow key={row.candidateId} selected={row.candidateId === selectedId} onSelect={() => onSelect(row.candidateId)}>
                  <Td>
                    <Status spec={candidateStatusSpec[row.status]} />
                  </Td>
                  <Td className="max-w-[28rem]">
                    <button
                      type="button"
                      onClick={() => onSelect(row.candidateId)}
                      aria-current={row.candidateId === selectedId ? "true" : undefined}
                      className="line-clamp-2 min-h-11 text-left font-medium text-text-primary hover:underline focus-visible:-outline-offset-2"
                    >
                      {row.title}
                    </button>
                    {!row.active && <Badge className="mt-1">비활성</Badge>}
                  </Td>
                  <Td className="max-w-48 truncate text-text-secondary">{row.companies.map((c) => c.name).join(", ") || "–"}</Td>
                  <Td className="text-right">{formatCount(row.evidenceCount)}</Td>
                  <Td>
                    <div className="flex flex-col items-start gap-1">
                      <OnUserGraph on={row.onUserGraph} />
                      <RuleBadge rule={row.rule} />
                    </div>
                  </Td>
                  <Td>
                    <DecisionText decision={row.decision} />
                  </Td>
                </SelectableRow>
              ))}
            </tbody>
          </DataTable>
        )}
        {candidates.hasNextPage && (
          <Button variant="secondary" className="self-start" loading={candidates.isFetchingNextPage} onClick={() => void candidates.fetchNextPage()}>
            후보 더 보기
          </Button>
        )}
      </div>
      <aside aria-label="후보 상세" className="sticky top-4 flex max-h-[calc(100dvh-220px)] min-w-0 flex-col self-start overflow-y-auto border-l border-border-subtle pl-6">
        {selectedId ? (
          <CandidateDetailView id={selectedId} onClose={() => onSelect(null)} />
        ) : (
          <EmptyState title="후보를 골라 주세요" description="왼쪽 목록에서 후보를 고르면 원문 인용과 판정 근거를 보여 줘요." />
        )}
      </aside>
    </div>
  );
}

type PendingDecision = { decision: "allow" | "reject"; relationId?: string; label: string };

function CandidateDetailView({ id, onClose }: { id: string; onClose: () => void }) {
  const candidate = useCandidate(id);
  const decide = useDecideCandidate();
  const toast = useToast();
  const [pending, setPending] = useState<PendingDecision | null>(null);

  if (candidate.isPending) return <SkeletonLines lines={8} label="후보 상세를 불러오고 있어요" />;
  if (candidate.isError) return <ErrorState error={candidate.error} title="후보 상세를 불러오지 못했어요" onRetry={() => void candidate.refetch()} compact />;
  const c = candidate.data;
  const canAllow = c.active && (c.status === "HOLD" || c.status === "ALLOW") && c.decision?.decision !== "allow";
  const canReject = c.active && c.status !== "REJECT" && c.decision?.decision !== "reject";
  const allowBlocked = !c.active ? "비활성 후보는 허용할 수 없어요." : c.status === "REJECT" ? "폐기 판정 후보는 허용할 수 없어요." : null;

  const submit = ({ reason }: { reason: string }) => {
    if (!pending) return;
    decide.mutate(
      { id, decision: pending.decision, reason, relationId: pending.relationId },
      {
        onSuccess: (result) => {
          setPending(null);
          toast({
            tone: "success",
            title: result.idempotent ? "이미 같은 결정이 적용돼 있어요" : pending.decision === "allow" ? "허용했어요" : "거부했어요",
            description: result.onUserGraph ? `사용자 그래프에 표시돼요 (${result.graphVersion})` : `사용자 그래프에서 빠졌어요 (${result.graphVersion})`,
          });
        },
      },
    );
  };

  return (
    <article className="flex flex-col gap-4 pb-6" aria-labelledby="candidate-title">
      <div className="flex items-start gap-2">
        <h2 id="candidate-title" className="flex-1 text-lg font-semibold text-text-primary">
          {c.title}
        </h2>
        <Button variant="ghost" size="icon" aria-label="후보 상세 닫기" onClick={onClose}>
          <X aria-hidden="true" />
        </Button>
      </div>
      <dl className="grid grid-cols-[auto_1fr] gap-x-4 gap-y-2 text-base">
        <dt className="text-sm text-text-secondary">판정</dt>
        <dd>
          <Status spec={candidateStatusSpec[c.status]} />
          {!c.active && <Badge className="ml-2">비활성</Badge>}
        </dd>
        <dt className="text-sm text-text-secondary">사용자 그래프</dt>
        <dd>
          <OnUserGraph on={c.onUserGraph} />
        </dd>
        {c.rule && (
          <>
            <dt className="text-sm text-text-secondary">자동 검수 규칙</dt>
            <dd>
              <RuleState rule={c.rule} />
            </dd>
          </>
        )}
        <dt className="text-sm text-text-secondary">사건 시각</dt>
        <dd>
          <KstTime value={c.eventTime} />
        </dd>
        <dt className="text-sm text-text-secondary">관련 기업</dt>
        <dd>{c.companies.map((co) => co.name).join(", ") || "–"}</dd>
        <dt className="text-sm text-text-secondary">정책</dt>
        <dd className="text-sm break-all text-text-secondary">{c.policyVersion}</dd>
      </dl>

      {c.reasons.length > 0 && (
        <section aria-labelledby="candidate-reasons" className="flex flex-col gap-1">
          <h3 id="candidate-reasons" className="text-base font-semibold text-text-primary">
            {c.status === "HOLD" ? "보류 사유" : c.status === "REJECT" ? "폐기 사유" : "판정 사유"}
          </h3>
          <ul className="flex list-disc flex-col gap-1 pl-5 text-base text-text-primary">
            {c.reasons.map((reason) => (
              <li key={reason}>{reason}</li>
            ))}
          </ul>
        </section>
      )}
      {c.invalidationReason && <p className="text-base text-text-secondary">비활성 사유: {c.invalidationReason}</p>}

      <div className="flex flex-wrap gap-2 border-y border-border-subtle py-3">
        <Button disabled={!canAllow} title={allowBlocked ?? undefined} onClick={() => setPending({ decision: "allow", label: "후보 허용" })}>
          <Check aria-hidden="true" />
          허용하고 사용자 그래프에 넣기
        </Button>
        <Button variant="secondary" disabled={!canReject} onClick={() => setPending({ decision: "reject", label: "후보 거부" })}>
          <X aria-hidden="true" />
          거부하고 그래프에서 빼기
        </Button>
        {allowBlocked && <p className="w-full text-sm text-text-secondary">{allowBlocked}</p>}
      </div>

      <section aria-labelledby="candidate-evidence" className="flex flex-col gap-2">
        <h3 id="candidate-evidence" className="flex items-center gap-2 text-base font-semibold text-text-primary">
          <FileText className="size-4 text-text-secondary" aria-hidden="true" />
          원문 인용 {formatCount(c.evidence.length)}
        </h3>
        {c.evidence.length === 0 ? (
          <p className="text-base text-text-secondary">원문 인용이 없어요. 인용 없이 허용할 수 없어요.</p>
        ) : (
          <ol className="flex flex-col divide-y divide-border-subtle">
            {c.evidence.map((ev) => {
              const article = c.articles.find((a) => a.articleId === ev.articleId);
              return (
                <li key={`${ev.articleId}-${ev.start}`} className="flex flex-col gap-2 py-3">
                  <p className="flex flex-wrap items-center gap-x-2 text-sm text-text-secondary">
                    <span className="font-medium text-text-primary">{article?.publisher ?? "출처 미상"}</span>
                    <span aria-hidden="true">·</span>
                    <span>
                      발행 <KstTime value={article?.publishedAt} />
                    </span>
                    {article?.synthetic && <Badge>합성</Badge>}
                  </p>
                  <p className="text-base font-medium text-text-primary">{ev.articleTitle}</p>
                  <blockquote className="bg-surface-sunken px-4 py-3 text-base leading-relaxed text-text-primary">“{ev.quote}”</blockquote>
                  {ev.url ? (
                    <a href={ev.url} target="_blank" rel="noreferrer" className="inline-flex min-h-11 w-fit items-center gap-1 text-sm font-medium text-brand-primary underline-offset-4 hover:underline">
                      <ExternalLink className="size-4" aria-hidden="true" />
                      원문 기사 보기<span className="sr-only">(새 창에서 열림)</span>
                    </a>
                  ) : (
                    <span className="inline-flex min-h-11 items-center gap-1 text-sm text-text-secondary">
                      <Link2Off className="size-4" aria-hidden="true" />
                      원문 링크 없음
                    </span>
                  )}
                </li>
              );
            })}
          </ol>
        )}
      </section>

      {c.relations.length > 0 && (
        <section aria-labelledby="candidate-relations" className="flex flex-col gap-2">
          <h3 id="candidate-relations" className="text-base font-semibold text-text-primary">
            연결 관계 {formatCount(c.relations.length)}
          </h3>
          <ul className="flex flex-col divide-y divide-border-subtle">
            {c.relations.map((rel) => (
              <li key={rel.relationId} className="flex flex-col gap-1 py-2">
                <p className="flex flex-wrap items-center gap-x-3 gap-y-1 text-base">
                  <span className="font-medium text-text-primary">{relationLabel[rel.relationType as RelationType] ?? rel.relationType}</span>
                  <span className="text-sm text-text-secondary">근거 {formatCount(rel.evidenceCount)}</span>
                  <OnUserGraph on={rel.onUserGraph} />
                  <DecisionText decision={rel.decision} />
                </p>
                <p className="text-sm break-all text-text-secondary">
                  {rel.source} → {rel.target}
                </p>
                <p className="flex flex-wrap items-center gap-x-2 gap-y-1 text-sm text-text-secondary">
                  {rel.role && <span>모델이 적은 역할 “{rel.role}”</span>}
                  {c.rule?.withheldRelations.includes(rel.relationId) && (
                    <Badge>
                      <ListChecks aria-hidden="true" />
                      규칙이 비움
                    </Badge>
                  )}
                  {c.rule?.droppedRelations.includes(rel.relationId) && (
                    <Badge>
                      <ListChecks aria-hidden="true" />
                      규칙이 게시하지 않음
                    </Badge>
                  )}
                </p>
                <div className="flex gap-2">
                  <Button
                    variant="ghost"
                    size="sm"
                    disabled={rel.decision?.decision === "allow" || rel.evidenceCount === 0}
                    onClick={() => setPending({ decision: "allow", relationId: rel.relationId, label: "관계 허용" })}
                  >
                    <Check aria-hidden="true" />
                    관계 허용
                  </Button>
                  <Button
                    variant="ghost"
                    size="sm"
                    disabled={rel.decision?.decision === "reject"}
                    onClick={() => setPending({ decision: "reject", relationId: rel.relationId, label: "관계 거부" })}
                  >
                    <X aria-hidden="true" />
                    관계 거부
                  </Button>
                </div>
              </li>
            ))}
          </ul>
        </section>
      )}

      {c.rule && <WithheldRoles detail={c} />}

      <VerificationSection verification={c.verification} />

      <section aria-labelledby="candidate-history" className="flex flex-col gap-2">
        <h3 id="candidate-history" className="flex items-center gap-2 text-base font-semibold text-text-primary">
          <History className="size-4 text-text-secondary" aria-hidden="true" />
          검수 이력
        </h3>
        {c.history.length === 0 ? (
          <p className="text-base text-text-secondary">아직 검수 기록이 없어요.</p>
        ) : (
          <ol className="flex flex-col divide-y divide-border-subtle">
            {c.history.map((h) => (
              <li key={h.id} className="flex flex-col gap-0.5 py-2">
                <p className="flex flex-wrap items-center gap-x-3 text-sm text-text-secondary">
                  <DecisionText decision={h} />
                  <span>{h.targetType === "relation" ? "관계" : "후보"}</span>
                  <KstTime value={h.decidedAt} />
                  <span>{h.origin === "snapshot-migration" ? "기존 검수 이관" : h.adminEmail}</span>
                </p>
                <p className="text-base text-text-primary">{h.reason}</p>
              </li>
            ))}
          </ol>
        )}
      </section>

      <ReasonDialog
        key={pending ? `${pending.decision}-${pending.relationId ?? "candidate"}` : "closed"}
        open={pending !== null}
        onOpenChange={(open) => {
          if (!open) {
            setPending(null);
            decide.reset();
          }
        }}
        title={pending?.label ?? ""}
        target={
          <p className={cn("font-medium")}>
            {c.title}
            {pending?.relationId && <span className="block text-sm font-normal break-all text-text-secondary">관계 {pending.relationId}</span>}
          </p>
        }
        reasonLabel={pending?.decision === "allow" ? "허용 사유" : "거부 사유"}
        confirmLabel={pending?.decision === "allow" ? "허용하기" : "거부하기"}
        confirmIcon={pending?.decision === "allow" ? <Check aria-hidden="true" /> : <X aria-hidden="true" />}
        pending={decide.isPending}
        error={decide.error}
        onConfirm={submit}
      >
        <p className="text-sm text-text-secondary">
          {pending?.decision === "allow" ? "허용하면 사용자 그래프에 바로 나타나요." : "거부하면 사용자 그래프에서 바로 빠져요."} 사유는 감사 로그에 남아요.
        </p>
      </ReasonDialog>
    </article>
  );
}

function VerificationSection({ verification }: { verification: CandidateDetail["verification"] }) {
  if (!verification) return null;
  const verdicts = [...verification.verdicts, ...verification.fieldVerdicts.map((f) => ({ target: f.field, decision: f.decision, reason: f.reason }))];
  return (
    <section aria-labelledby="candidate-verification" className="flex flex-col gap-2">
      <h3 id="candidate-verification" className="flex items-center gap-2 text-base font-semibold text-text-primary">
        <ShieldCheck className="size-4 text-text-secondary" aria-hidden="true" />
        검증 판정
      </h3>
      <p className="text-sm text-text-secondary">
        {verification.provider} · {verification.model}
      </p>
      {verdicts.length > 0 && (
        <DataTable caption="검증 판정">
          <thead>
            <tr>
              <Th>대상</Th>
              <Th>판정</Th>
              <Th>사유</Th>
            </tr>
          </thead>
          <tbody>
            {verdicts.map((v, i) => (
              <tr key={`${v.target}-${i}`}>
                <Td className="text-sm break-all">{v.target}</Td>
                <Td className="text-sm">{v.decision}</Td>
                <Td className="text-sm">{v.reason}</Td>
              </tr>
            ))}
          </tbody>
        </DataTable>
      )}
    </section>
  );
}
