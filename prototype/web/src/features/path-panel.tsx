// 두 기업 사이 경로(G6)의 상세 쪽 화면.
//  - PathPicker: [다른 기업과의 연결 보기] → 지금 지도의 다른 기업 목록(검색, 표지·이름)에서 두 번째 기업 고르기.
//    데스크톱은 버튼 옆 팝오버, 모바일은 바텀시트.
//  - PathDetail: 경로를 단계 행으로. 기업 → (선 요약) → 사건 → (선 요약) → 기업 …, 사건 행에서 근거를 연다.
//    이어지지 않으면 안내 문장만 두고 지도는 바꾸지 않는다(부모가 경로를 넘기지 않는다).
import { Info, Route } from "lucide-react";
import { Fragment, useState } from "react";
import type { Schemas } from "@/api/client";
import { CompanyMark } from "@/components/domain/company-mark";
import { EventRow } from "@/components/domain/event-row";
import type { GraphSelection } from "@/components/domain/graph-canvas";
import { EdgeGlyph } from "@/components/domain/relation-type-tag";
import { Button } from "@/components/ui/button";
import { Sheet } from "@/components/ui/dialog";
import { IconHint } from "@/components/ui/icon-hint";
import { Input } from "@/components/ui/input";
import { ListRow } from "@/components/ui/list-row";
import { Popover } from "@/components/ui/popover";
import { SectionHeader } from "@/components/ui/section-header";
import type { GraphPath } from "@/lib/graph-path";
import { relationLabel } from "@/lib/labels";
import { useMediaQuery } from "@/lib/theme";
import type { EvidenceRequest } from "./overlays";

interface PathPickerProps {
  /** 출발 기업 id(목록에서 뺀다) */
  fromId: string;
  nodes: Schemas["GraphNode"][];
  onPick: (toId: string) => void;
  label?: string;
}

/** 두 번째 기업 고르기. 지도에 다른 기업이 없으면 그리지 않는다. */
export function PathPicker({ fromId, nodes, onPick, label = "다른 기업과의 연결 보기" }: PathPickerProps) {
  const isMobile = useMediaQuery("(max-width: 768px)");
  const [open, setOpen] = useState(false);
  const [query, setQuery] = useState("");
  const others = nodes.filter((n) => n.kind === "company" && n.id !== fromId).sort((a, b) => a.label.localeCompare(b.label, "ko"));
  if (others.length === 0) return null;

  const needle = query.trim().toLowerCase();
  const matches = needle ? others.filter((n) => n.label.toLowerCase().includes(needle)) : others;
  const changeOpen = (next: boolean) => {
    setOpen(next);
    if (!next) setQuery("");
  };
  const pick = (id: string) => {
    changeOpen(false);
    onPick(id);
  };
  const trigger = (
    <Button variant="ghost" onClick={isMobile ? () => changeOpen(true) : undefined}>
      <Route aria-hidden="true" />
      {label}
    </Button>
  );
  const list = (
    <div className="flex min-h-0 flex-col gap-2">
      <Input
        label="연결을 볼 기업"
        variant="search"
        placeholder="기업 이름"
        value={query}
        onChange={(e) => setQuery(e.target.value)}
        onClear={() => setQuery("")}
        autoComplete="off"
      />
      {matches.length === 0 ? (
        <p className="py-3 text-base text-text-secondary">‘{query.trim()}’와 맞는 기업이 없어요.</p>
      ) : (
        <ul aria-label={`지도의 다른 기업 ${matches.length}곳`} className="-mx-4 max-h-[min(320px,50dvh)] overflow-y-auto max-md:max-h-none">
          {matches.map((company) => (
            <li key={company.id}>
              <ListRow
                onClick={() => pick(company.id)}
                leading={<CompanyMark id={company.id} name={company.label} brandColor={company.brandColor} logoUrl={company.logoUrl} />}
                title={company.label}
              />
            </li>
          ))}
        </ul>
      )}
    </div>
  );

  if (isMobile) {
    return (
      <>
        {trigger}
        <Sheet open={open} onOpenChange={changeOpen} title="연결을 볼 기업 고르기" closeLabel="닫기" mobileSnap="full">
          {list}
        </Sheet>
      </>
    );
  }
  return (
    <Popover label="연결을 볼 기업 고르기" trigger={trigger} open={open} onOpenChange={changeOpen} side="bottom" align="start" className="text-base">
      {list}
    </Popover>
  );
}

interface PathDetailProps {
  from: Schemas["GraphNode"];
  /** 최단 경로. null이면 두 기업이 이어지지 않는다. */
  path: GraphPath | null;
  nodes: Schemas["GraphNode"][];
  edges: Schemas["GraphEdge"][];
  onSelect: (selection: GraphSelection) => void;
  onShowEvidence: (request: EvidenceRequest) => void;
  /** 출발 기업은 그대로 두고 두 번째 기업을 다시 고른다. */
  onRepick: (toId: string) => void;
}

export function PathDetail({ from, path, nodes, edges, onSelect, onShowEvidence, onRepick }: PathDetailProps) {
  const picker = <PathPicker fromId={from.id} nodes={nodes} onPick={onRepick} label="다른 기업 고르기" />;

  if (!path) {
    return (
      <div className="flex flex-col gap-1 pb-4">
        <p className="px-4 pt-2 text-base text-text-primary">아직 두 기업을 잇는 사건이 없어요.</p>
        <div className="px-4 pt-2">{picker}</div>
      </div>
    );
  }

  return (
    <section aria-label="경로 단계" className="flex flex-col pb-4">
      <div className="px-4">{picker}</div>
      <SectionHeader
        as="h3"
        icon={Route}
        title={`${path.edgeIds.length}단계`}
        action={
          <IconHint icon={Info} label="경로를 찾는 방법">
            <p>승인된 관계 선만 따라 가장 적은 단계로 잇는 경로예요. 선의 방향은 따지지 않고, 같은 사건에 함께 언급된 파생 경로(사건 공유)는 쓰지 않아요.</p>
          </IconHint>
        }
      />
      <ol className="flex flex-col">
        {path.nodeIds.map((id, i) => {
          const node = nodes.find((n) => n.id === id);
          const edge = i < path.edgeIds.length ? edges.find((e) => e.id === path.edgeIds[i]) : undefined;
          if (!node) return null;
          return (
            <Fragment key={id}>
              <li>
                {node.kind === "company" ? (
                  <ListRow
                    divider="none"
                    onClick={() => onSelect({ kind: "node", id })}
                    leading={<CompanyMark id={id} name={node.label} brandColor={node.brandColor} logoUrl={node.logoUrl} />}
                    title={
                      <>
                        <span className="sr-only">기업: </span>
                        {node.label}
                      </>
                    }
                  />
                ) : (
                  <div className="px-4">
                    <EventRow
                      headingLevel="h4"
                      title={node.label}
                      eventTime={node.eventTime}
                      timePrecision={node.timePrecision}
                      evidenceCount={node.evidenceCount ?? undefined}
                      onShowEvidence={() => onShowEvidence({ title: node.label, eventId: id })}
                      onSelect={() => onSelect({ kind: "node", id })}
                      divider={false}
                    />
                  </div>
                )}
              </li>
              {edge && (
                // 단계 사이 선: 왼쪽 세로줄이 순서를 잇고, 선 견본 + 요약으로 관계를 읽는다.
                <li className="ml-7 flex min-h-9 items-center gap-2 border-l-2 border-border-subtle pl-5 text-sm text-text-secondary">
                  <EdgeGlyph type={edge.relationType} />
                  <span className="sr-only">{relationLabel[edge.relationType]}: </span>
                  {edge.summary}
                </li>
              )}
            </Fragment>
          );
        })}
      </ol>
    </section>
  );
}
