// 기업 패널 → 관련 이슈 → 영향 경로(명세 FS022, D03). 이슈–기업 간선을 누르지 않고 기업 패널에서 들어온다.
//  - 확인된 연결: 선택 기업에서 사건까지 단계마다 관계 유형·역할·보도 표현·근거(승인된 관계만).
//  - 함께 연결된 기업: 같은 사건에 이어진 다른 기업과 그 역할·근거.
//  - 해석 한계: 연결은 기사·등록 관계로 확인된 사실이고, 영향(주가·실적)이나 단계 사이 인과는 판단하지 않는다.
//  - 기준 시점: 지도(그래프 버전)의 기준 시각. 역할은 사건 상세 조회로 채우고, 실패하면 경로는 그대로 두고 그 영역만 다시 시도한다.
//    사건을 바꾸면 조회 키가 바뀌므로 이전 사건의 늦은 응답이 새 경로를 덮지 않는다.
import { FileText, Info, MessageCircleQuestion, Route, Scale, Users } from "lucide-react";
import { Fragment } from "react";
import type { Schemas } from "@/api/client";
import { useEvent } from "@/api/queries";
import { CompanyMark } from "@/components/domain/company-mark";
import { EventRow } from "@/components/domain/event-row";
import type { GraphSelection } from "@/components/domain/graph-canvas";
import { EdgeGlyph } from "@/components/domain/relation-type-tag";
import { Button } from "@/components/ui/button";
import { ErrorState, SkeletonLines } from "@/components/ui/feedback";
import { IconHint } from "@/components/ui/icon-hint";
import { ListRow } from "@/components/ui/list-row";
import { SectionHeader } from "@/components/ui/section-header";
import type { ImpactPath } from "@/lib/impact-path";
import { assertionStatusLabel, formatKst, relationLabel } from "@/lib/labels";
import { useOverlays, type EvidenceRequest } from "./overlays";

interface ImpactDetailProps {
  impact: ImpactPath;
  nodes: Schemas["GraphNode"][];
  /** 지도 기준 시점(그래프 버전 시각) */
  asOf: string | null;
  onSelect: (selection: GraphSelection) => void;
  onShowEvidence: (request: EvidenceRequest) => void;
}

export function ImpactDetail({ impact, nodes, asOf, onSelect, onShowEvidence }: ImpactDetailProps) {
  const event = useEvent(impact.issueId);
  const { openChat } = useOverlays();
  const node = (id: string) => nodes.find((n) => n.id === id);
  const issue = node(impact.issueId);
  // 이 사건의 상세(역할)만 쓴다. 키가 사건 id라 다른 사건의 응답은 섞이지 않는다.
  const detail = event.data?.id === impact.issueId ? event.data : undefined;
  const roleOf = (companyId: string) => {
    const link = detail?.companies.find((c) => c.id === companyId);
    if (!link) return null;
    return link.role ?? (link.roleUnconfirmed ? "역할 확인 안 됨" : null);
  };
  const stepRole = (edge: Schemas["GraphEdge"], a: string, b: string) => {
    const companyId = node(a)?.kind === "company" ? a : node(b)?.kind === "company" ? b : null;
    return (companyId && (edge.source === impact.issueId || edge.target === impact.issueId) ? roleOf(companyId) : null) ?? edge.summary;
  };
  const evidenceButton = (edge: Schemas["GraphEdge"], title: string) =>
    edge.evidenceIds.length > 0 && (
      <Button variant="ghost" size="sm" onClick={() => onShowEvidence({ title, evidenceIds: edge.evidenceIds, eventId: impact.issueId })}>
        <FileText aria-hidden="true" />
        근거 {edge.evidenceIds.length}건
      </Button>
    );
  const forecast = impact.steps.some((s) => s.edge.assertionStatus && s.edge.assertionStatus !== "occurred");
  const structural = [...impact.steps, ...impact.others].some((s) => s.edge.relationType === "STRUCTURALLY_RELATED_TO");

  const company = node(impact.companyId);
  const issueActions = issue && (
    <div className="flex flex-wrap gap-2 px-4">
      <Button variant="secondary" onClick={() => onSelect({ kind: "node", id: impact.issueId })}>
        사건 상세 보기
      </Button>
      <Button
        variant="ghost"
        onClick={() =>
          openChat({
            targets: [
              { id: impact.issueId, kind: "issue", label: issue.label, detail: `근거 ${issue.evidenceCount ?? 0}건` },
              ...(company ? [{ id: company.id, kind: "company" as const, label: company.label }] : []),
            ],
          })
        }
      >
        <MessageCircleQuestion aria-hidden="true" />
        AI에게 묻기
      </Button>
    </div>
  );

  if (!impact.route) {
    return (
      <div className="flex flex-col gap-3 pb-4">
        <p className="px-4 pt-2 text-base text-text-primary">이 기업과 사건을 잇는 승인된 연결이 없어요.</p>
        {issueActions}
      </div>
    );
  }

  return (
    <div className="flex flex-col pb-4">
      <p className="px-4 text-sm text-text-secondary tabular-nums">
        {impact.steps.length === 1 ? "직접 연결" : `간접 연결 · ${impact.steps.length}단계`} · 지도 기준 {formatKst(asOf)}
      </p>
      <div className="pt-3">{issueActions}</div>

      <section aria-label="확인된 연결">
        <SectionHeader
          as="h3"
          icon={Route}
          title="확인된 연결"
          action={
            <IconHint icon={Info} label="연결을 찾는 방법">
              <p>승인된 관계 선만 따라 가장 적은 단계로 이은 경로예요. 사건을 공유한다는 파생 선은 쓰지 않아요.</p>
            </IconHint>
          }
        />
        <ol className="flex flex-col">
          {impact.route.nodeIds.map((id, i) => {
            const n = node(id);
            const step = impact.steps[i];
            if (!n) return null;
            return (
              <Fragment key={id}>
                <li>
                  {n.kind === "company" ? (
                    <ListRow
                      divider="none"
                      leading={<CompanyMark id={id} name={n.label} brandColor={n.brandColor} logoUrl={n.logoUrl} />}
                      title={
                        <>
                          <span className="sr-only">기업: </span>
                          {n.label}
                        </>
                      }
                    />
                  ) : (
                    <div className="px-4">
                      <EventRow
                        headingLevel="h4"
                        title={n.label}
                        eventTime={n.eventTime}
                        timePrecision={n.timePrecision}
                        evidenceCount={n.evidenceCount ?? undefined}
                        onShowEvidence={() => onShowEvidence({ title: n.label, eventId: id })}
                        divider={false}
                      />
                    </div>
                  )}
                </li>
                {step && (
                  // 단계 사이: 관계 유형 · 역할(요약) · 보도 표현과 그 연결의 근거
                  <li className="ml-7 flex min-h-11 flex-wrap items-center gap-x-2 gap-y-1 border-l-2 border-border-subtle py-1 pl-5 text-sm text-text-secondary">
                    <EdgeGlyph type={step.edge.relationType} />
                    <span className="font-medium text-text-primary">{relationLabel[step.edge.relationType]}</span>
                    <span>{stepRole(step.edge, step.from, step.to)}</span>
                    {step.edge.assertionStatus && <span>· {assertionStatusLabel(step.edge.assertionStatus)}</span>}
                    {evidenceButton(step.edge, `${node(step.from)?.label ?? ""} – ${node(step.to)?.label ?? ""}`)}
                  </li>
                )}
              </Fragment>
            );
          })}
        </ol>
        {event.isPending && (
          <div className="px-4">
            <SkeletonLines lines={1} label="역할을 불러오고 있어요" />
          </div>
        )}
        {event.isError && (
          <ErrorState className="px-4" compact error={event.error} title="역할을 불러오지 못했어요" onRetry={() => void event.refetch()} />
        )}
      </section>

      <section aria-label="함께 연결된 기업">
        <SectionHeader as="h3" icon={Users} title={`함께 연결된 기업 ${impact.others.length}곳`} />
        {impact.others.length === 0 ? (
          <p className="px-4 text-base text-text-secondary">이 사건에 함께 연결된 다른 기업이 없어요.</p>
        ) : (
          <ul>
            {impact.others.map(({ edge, companyId }) => {
              const company = node(companyId);
              const name = company?.label ?? companyId;
              return (
                <li key={edge.id} className="flex items-center gap-1 pr-2">
                  <ListRow
                    className="min-w-0 flex-1"
                    leading={<CompanyMark id={companyId} name={name} brandColor={company?.brandColor} logoUrl={company?.logoUrl} />}
                    title={name}
                    description={[relationLabel[edge.relationType], roleOf(companyId) ?? edge.summary].join(" · ")}
                    onClick={() => onSelect({ kind: "node", id: companyId })}
                  />
                  {evidenceButton(edge, `${name} – ${issue?.label ?? ""}`)}
                </li>
              );
            })}
          </ul>
        )}
      </section>

      <section aria-label="해석 한계">
        <SectionHeader as="h3" icon={Scale} title="해석 한계" />
        <ul className="flex list-disc flex-col gap-1 pr-4 pl-9 text-sm text-text-secondary">
          <li>위 연결은 기사에 적힌 사실과 등록된 사업 관계예요. 이 사건이 주가나 실적에 주는 영향은 판단하지 않아요.</li>
          {impact.steps.length > 1 && <li>중간 사건·기업을 거친 연결은 단계마다 근거가 따로 있고, 단계 사이의 인과는 확인되지 않았어요.</li>}
          {structural && <li>구조적 관련은 사업 관계로 이어졌다는 뜻이고, 이 사건에 직접 참여했다는 뜻은 아니에요.</li>}
          {forecast && <li>보도 표현이 발생이 아닌 연결(계획·전망 등)은 아직 일어난 일로 확인되지 않았어요.</li>}
        </ul>
      </section>
    </div>
  );
}
