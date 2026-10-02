// GraphLegend(Neo4j Browser식 라벨 칩: 표지 + 이름 + 개수, 누르면 표시 켜기/끄기) · GraphModeSwitch(전체/개인화 모드 Segmented)
import { Bookmark, Building2, Globe, Info, Lock, Zap, type LucideIcon } from "lucide-react";
import type { ReactNode } from "react";
import type { Schemas } from "@/api/client";
import { hitArea } from "@/components/ui/button";
import { IconHint } from "@/components/ui/icon-hint";
import { Segmented } from "@/components/ui/segmented";
import type { LegendKey } from "@/lib/graph-view";
import { modeLabel, relationLabel, type GraphMode, type RelationType } from "@/lib/labels";
import { cn } from "@/lib/utils";
import { EdgeGlyph } from "./relation-type-tag";

const legendEdges: RelationType[] = ["INVOLVES", "STRUCTURALLY_RELATED_TO", "FOLLOWS", "SHARES_ISSUE"];

const chipClass = "flex h-8 shrink-0 items-center gap-1.5 rounded-sm px-2.5 text-sm whitespace-nowrap";

function Chip({ mark, label, count }: { mark: ReactNode; label: string; count: number }) {
  return (
    <li className={cn(chipClass, "bg-surface-sunken text-text-primary")}>
      {mark}
      <span className="font-medium">{label}</span>
      <data value={count} className="text-text-secondary tabular-nums">
        {count}
      </data>
    </li>
  );
}

/** 누르면 그 종류를 지도에서 숨기거나 다시 보인다. 끈 칩은 바탕이 빠지고 표지가 흐려진다(개수는 유지). */
function ToggleChip({ mark, label, count, shown, locked, onToggle }: { mark: ReactNode; label: string; count: number; shown: boolean; locked: boolean; onToggle: () => void }) {
  return (
    <li className="shrink-0">
      <button
        type="button"
        aria-pressed={shown}
        // 마지막으로 남은 노드 종류는 끌 수 없다(지도가 비지 않게).
        disabled={locked}
        onClick={onToggle}
        className={cn(
          chipClass,
          hitArea,
          "pressable border border-transparent text-text-secondary hover:border-border-subtle",
          "aria-pressed:bg-surface-sunken aria-pressed:text-text-primary disabled:cursor-default",
          "[&:not([aria-pressed=true])_[data-mark]]:opacity-40",
        )}
      >
        <span data-mark="" className="flex items-center">
          {mark}
        </span>
        <span className="font-medium">{label}</span>
        <data value={count} className="text-text-secondary tabular-nums">
          {count}
        </data>
      </button>
    </li>
  );
}

interface GraphLegendProps {
  nodes: Schemas["GraphNode"][];
  edges: Schemas["GraphEdge"][];
  /** 꺼 둔 항목. onToggle과 함께 주면 칩이 토글 버튼이 된다(G5). */
  hidden?: ReadonlySet<LegendKey>;
  onToggle?: (key: LegendKey) => void;
  className?: string;
}

/**
 * 지도에 있는 노드 종류·관계 유형만 개수와 함께 칩으로 보여준다. 크기·거리의 뜻은 정보 아이콘 안에.
 * onToggle이 있으면 노드 종류·관계 유형 칩은 표시 켜기/끄기 버튼(aria-pressed)이다. 보유·관심은 표시 규칙이라 토글하지 않는다.
 */
export function GraphLegend({ nodes, edges, hidden, onToggle, className }: GraphLegendProps) {
  const companies = nodes.filter((n) => n.kind === "company").length;
  const issues = nodes.length - companies;
  const holding = nodes.filter((n) => n.holding).length;
  const watch = nodes.filter((n) => n.watch).length;
  const byType = legendEdges.map((type) => ({ type, count: edges.filter((e) => e.relationType === type).length })).filter((t) => t.count > 0);
  const nodeKinds = [companies > 0 && "company", issues > 0 && "issue"].filter(Boolean) as LegendKey[];
  const shownKinds = nodeKinds.filter((k) => !hidden?.has(k));
  const chip = (key: LegendKey, mark: ReactNode, label: string, count: number) =>
    onToggle ? (
      <ToggleChip
        key={key}
        mark={mark}
        label={label}
        count={count}
        shown={!hidden?.has(key)}
        locked={nodeKinds.includes(key) && shownKinds.length === 1 && shownKinds[0] === key}
        onToggle={() => onToggle(key)}
      />
    ) : (
      <Chip key={key} mark={mark} label={label} count={count} />
    );
  return (
    <div className={cn("flex min-w-0 items-center gap-1", className)}>
      {/* 모바일에서는 가로로 밀리는 영역이라 키보드로도 스크롤할 수 있게 포커스를 받는다(버튼 칩이면 버튼이 받는다). */}
      <ul
        aria-label="그래프 범례"
        tabIndex={onToggle ? undefined : 0}
        className="flex min-w-0 flex-1 items-center gap-x-1.5 gap-y-3 overflow-x-auto rounded-sm py-1.5 md:flex-wrap md:overflow-visible"
      >
        {companies > 0 && chip("company", <Building2 className="size-4 text-text-secondary" aria-hidden="true" />, "기업", companies)}
        {issues > 0 &&
          chip(
            "issue",
            <span className="flex size-4 items-center justify-center rounded-full bg-graph-node-issue text-graph-node-glyph" aria-hidden="true">
              <Zap className="size-2.5" strokeWidth={3} />
            </span>,
            "사건",
            issues,
          )}
        {holding > 0 && <Chip mark={<MarkRing kind="holding" />} label="보유" count={holding} />}
        {watch > 0 && <Chip mark={<MarkRing kind="watch" />} label="관심" count={watch} />}
        {byType.map(({ type, count }) => chip(type, <EdgeGlyph type={type} className="w-6" />, relationLabel[type], count))}
      </ul>
      <IconHint icon={Info} label="지도 읽는 법">
        <p>기업은 상징색 원, 사건은 번개 원이에요. 선 가운데 글자는 관계 요약이에요.</p>
        {(holding > 0 || watch > 0) && <p>보유 종목은 실선 테두리, 관심 종목은 점선 테두리이고 이름 아래에 보유·관심이라고 적어요. 둘 다면 이중 테두리예요.</p>}
        {onToggle && <p>범례 칩을 누르면 그 종류를 지도에서 숨기거나 다시 보여요.</p>}
        <p>노드 크기와 거리는 인과 관계나 중요도를 뜻하지 않아요.</p>
      </IconHint>
    </div>
  );
}

/** 보유(실선)·관심(점선) 테두리 견본. 지도 노드의 테두리 모양과 같다. */
export function MarkRing({ kind }: { kind: "holding" | "watch" }) {
  return <span className={cn("size-3.5 rounded-full border-[3px] border-graph-node-mark", kind === "watch" && "border-dashed border-[2.5px]")} aria-hidden="true" />;
}

interface GraphModeSwitchProps {
  value: GraphMode;
  onValueChange: (mode: GraphMode) => void;
  /** 선택할 수 없는 모드와 그 이유(누를 수 없음). */
  disabledModes?: Partial<Record<GraphMode, string>>;
  /** 누를 수는 있지만 잠긴 모드(예: 비회원의 개인화). 자물쇠를 붙이고, 누르면 부모가 잠금 안내를 보여준다. */
  lockedModes?: GraphMode[];
  fill?: boolean;
  className?: string;
}

const modeIcon: Record<GraphMode, LucideIcon> = { all: Globe, personal: Bookmark };

/** 지금 모드를 다시 누르면 같은 모드로 onValueChange를 부른다(부모가 진행 중인 전환을 거둘 수 있게, FS019). */
export function GraphModeSwitch({ value, onValueChange, disabledModes = {}, lockedModes = [], fill, className }: GraphModeSwitchProps) {
  const modes: GraphMode[] = ["all", "personal"];
  return (
    <Segmented
      aria-label="탐색 모드"
      value={value}
      onValueChange={onValueChange}
      onReselect={onValueChange}
      fill={fill}
      className={className}
      options={modes.map((mode) => {
        const locked = lockedModes.includes(mode);
        const Icon = locked ? Lock : modeIcon[mode];
        return {
          value: mode,
          label: (
            <>
              <Icon aria-hidden="true" />
              {modeLabel[mode]}
            </>
          ),
          ariaLabel: locked ? `${modeLabel[mode]} (로그인 필요)` : modeLabel[mode],
          disabled: Boolean(disabledModes[mode]),
          disabledReason: disabledModes[mode],
        };
      })}
    />
  );
}
