// RelationList: 그래프와 같은 데이터를 목록으로 보여주는 대체 뷰(그래프 옆 [목록] 전환).
// 기업은 ListRow(지도와 같은 상징색 표지), 사건은 EventRow 한 행씩. 사건 행에서 바로 [근거 N건 보기]를 열 수 있다.
// 연결선 상세는 기업을 고른 뒤 상세의 '연결' 목록에서 연다. 처음 표시될 때 행이 차례로 떠오른다.
import { Building2, Zap } from "lucide-react";
import type { Schemas } from "@/api/client";
import { ListRow } from "@/components/ui/list-row";
import { SectionHeader } from "@/components/ui/section-header";
import { cn } from "@/lib/utils";
import { CompanyMark } from "./company-mark";
import { EventRow } from "./event-row";
import type { GraphSelection } from "./graph-canvas";

export interface IssueEvidence {
  id: string;
  title: string;
  evidenceIds: string[];
}

interface RelationListProps {
  nodes: Schemas["GraphNode"][];
  edges: Schemas["GraphEdge"][];
  selection: GraphSelection | null;
  onSelect: (selection: GraphSelection | null) => void;
  label: string;
  /** 사건 id → 근거 id 목록. 아직 모르면(불러오는 중) 행에 근거 버튼을 그리지 않는다. */
  evidenceByIssue?: ReadonlyMap<string, string[]>;
  onShowEvidence?: (issue: IssueEvidence) => void;
  /** 관련 기업 링크에 실을 이력 state */
  linkState?: unknown;
  className?: string;
}

export function RelationList({ nodes, edges, selection, onSelect, label, evidenceByIssue, onShowEvidence, linkState, className }: RelationListProps) {
  const byId = new Map(nodes.map((n) => [n.id, n]));
  const neighbors = (id: string) =>
    edges.flatMap((e) => (e.source === id ? [e.target] : e.target === id ? [e.source] : [])).flatMap((n) => byId.get(n) ?? []);
  const companies = nodes.filter((n) => n.kind === "company");
  const issues = nodes.filter((n) => n.kind === "issue").sort((a, b) => (b.eventTime ?? "").localeCompare(a.eventTime ?? ""));

  return (
    <div className={cn("overflow-y-auto", className)} aria-label={label} role="region">
      {companies.length > 0 && (
        <section aria-labelledby="relation-list-companies">
          <SectionHeader id="relation-list-companies" as="h2" icon={Building2} title={`기업 ${companies.length}곳`} className="pt-2" />
          <ul className="stagger">
            {companies.map((node) => {
              const issueCount = neighbors(node.id).filter((n) => n.kind === "issue").length;
              const marks = [node.holding ? "보유" : null, node.watch ? "관심" : null].filter(Boolean).join(" · ");
              return (
                <li key={node.id}>
                  <ListRow
                    leading={<CompanyMark id={node.id} name={node.label} brandColor={node.brandColor} logoUrl={node.logoUrl} />}
                    title={node.label}
                    description={marks || undefined}
                    trailing={
                      <span className="flex items-center gap-1 tabular-nums">
                        <Zap className="size-4" aria-hidden="true" />
                        <span className="sr-only">사건</span>
                        {issueCount}
                      </span>
                    }
                    selected={selection?.kind === "node" && selection.id === node.id}
                    onClick={() => onSelect({ kind: "node", id: node.id })}
                    data-selection-id={node.id}
                  />
                </li>
              );
            })}
          </ul>
        </section>
      )}
      {issues.length > 0 && (
        <section aria-labelledby="relation-list-issues">
          <SectionHeader id="relation-list-issues" as="h2" icon={Zap} title={`사건 ${issues.length}건`} />
          <ul className="stagger">
            {issues.map((node) => {
              const related = neighbors(node.id).filter((n) => n.kind === "company");
              const evidenceIds = evidenceByIssue?.get(node.id);
              const selected = selection?.kind === "node" && selection.id === node.id;
              return (
                <li key={node.id} data-selection-id={node.id} className={cn("px-4", selected && "bg-surface-selected")}>
                  <EventRow
                    headingLevel="h3"
                    title={node.label}
                    eventTime={node.eventTime}
                    timePrecision={node.timePrecision}
                    companies={related.map((c) => ({ id: c.id, name: c.label }))}
                    linkState={linkState}
                    evidenceCount={evidenceIds?.length}
                    onShowEvidence={
                      evidenceIds && onShowEvidence ? () => onShowEvidence({ id: node.id, title: node.label, evidenceIds }) : undefined
                    }
                    onSelect={() => onSelect({ kind: "node", id: node.id })}
                  />
                </li>
              );
            })}
          </ul>
        </section>
      )}
    </div>
  );
}
