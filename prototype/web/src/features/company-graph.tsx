import { Map as MapIcon, Network } from "lucide-react";
import type { UseQueryResult } from "@tanstack/react-query";
import type { Schemas } from "@/api/client";
import { GraphCanvas, type GraphSelection } from "@/components/domain/graph-canvas";
import { GraphLegend } from "@/components/domain/graph-legend";
import { CompanyMark } from "@/components/domain/company-mark";
import { Button } from "@/components/ui/button";
import { EmptyState, ErrorState, SkeletonRows } from "@/components/ui/feedback";
import { Segmented } from "@/components/ui/segmented";
import { formatKst } from "@/lib/labels";
import { cn } from "@/lib/utils";

export function CompanyGraph({ companyId, graph, asOf, hops, onHops, selectedId, highlightedIds, onIssue, onCompany, onMap }: {
  companyId: string; graph: UseQueryResult<Schemas["GraphResponse"]>; asOf: string; hops: 1 | 2;
  onHops: (hops: 1 | 2) => void; selectedId: string | null; highlightedIds: ReadonlySet<string>;
  onIssue: (id: string) => void; onCompany: (id: string) => void; onMap: () => void;
}) {
  const select = (selection: GraphSelection | null) => {
    if (!selection || selection.kind !== "node") return;
    const node = graph.data?.nodes.find(node => node.id === selection.id);
    if (node?.kind === "company") { if (node.id !== companyId) onCompany(node.id); }
    else if (node?.kind === "issue") onIssue(node.id);
  };
  return <section aria-labelledby="company-graph-title" className="flex min-w-0 flex-col gap-3 border-t border-border-subtle pt-4 min-[1400px]:border-t-0 min-[1400px]:pt-0">
    <div className="flex flex-wrap items-center justify-between gap-2"><h2 id="company-graph-title" className="flex items-center gap-2 text-lg font-semibold"><Network className="size-5 text-text-secondary" aria-hidden="true" />관계 그래프</h2><Button variant="ghost" size="sm" onClick={onMap}><MapIcon aria-hidden="true" />지도에서 보기</Button></div>
    <p className="text-sm text-text-secondary tabular-nums" aria-live="polite">기준 <time dateTime={asOf}>{formatKst(asOf)}</time></p>
    <Segmented aria-label="관계 탐색 깊이" value={String(hops)} onValueChange={value => onHops(value === "2" ? 2 : 1)} options={[{ value: "1", label: "1단계" }, { value: "2", label: "2단계" }]} />
    {graph.isPending && <SkeletonRows count={4} label="관계 그래프를 불러오고 있어요" />}
    {graph.isError && <ErrorState compact error={graph.error} title="관계 그래프를 불러오지 못했어요" onRetry={() => void graph.refetch()} />}
    {graph.data && <>
      <GraphLegend nodes={graph.data.nodes} edges={graph.data.edges} marks={false} />
      <GraphCanvas nodes={graph.data.nodes} edges={graph.data.edges} focus={{ id: companyId, hops }} compactFocus minimalToolbar selection={selectedId ? { kind: "node", id: selectedId } : null} highlightedNodes={highlightedIds} onSelect={select} ariaLabel={`기업 중심 관계 그래프. 기업 ${graph.data.nodes.filter(n => n.kind === "company").length}개, 사건 ${graph.data.nodes.filter(n => n.kind === "issue").length}개`} className="h-96 min-h-96 border-y border-border-subtle" />
      {!graph.data.edges.length && <EmptyState title="이 시점에 표시할 검증 관계가 없어요" />}
      <details className="text-sm" open><summary className="min-h-11 cursor-pointer py-3 font-medium text-text-secondary">관계 목록 · 키보드로 선택하기</summary><ul aria-label="기업 관계 그래프 목록" className="max-h-64 overflow-y-auto divide-y divide-border-subtle">{graph.data.nodes.filter(n => n.id !== companyId).map(node => <li key={node.id}><button type="button" aria-pressed={node.kind === "issue" ? selectedId === node.id || highlightedIds.has(node.id) : undefined} onClick={() => node.kind === "company" ? onCompany(node.id) : onIssue(node.id)} className={cn("flex min-h-11 w-full items-center gap-2 px-2 py-3 text-left text-base hover:bg-surface-sunken", (selectedId === node.id || highlightedIds.has(node.id)) && "bg-surface-selected font-semibold")}>
        {node.kind === "company" ? <CompanyMark id={node.id} name={node.label} brandColor={node.brandColor} logoUrl={node.logoUrl} /> : <span className="text-sm text-text-secondary">사건</span>}<span className="min-w-0 flex-1">{node.label}</span>
      </button></li>)}</ul></details>
    </>}
  </section>;
}
