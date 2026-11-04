import GraphIcon from './GraphIcon';
import type { GraphResponse } from '@/types/map/graph';
import type { LegendKey } from './graph-view';
import { edgeSwatchClass } from './edge-swatch';
import { legendEntries as entries } from './relation-help';

export default function GraphLegend({
  data,
  hidden,
  onToggle,
}: {
  data: GraphResponse;
  hidden: LegendKey[];
  onToggle: (key: LegendKey) => void;
}) {
  return (
    <div
      role="group"
      aria-label="그래프 표시 필터"
      className="relationship-graph-filters flex shrink-0 items-center gap-1 whitespace-nowrap"
    >
      {entries.map(([key, label, help]) => {
        const kind = key === 'company' || key === 'issue';
        const count = kind
          ? data.nodes.filter((node) => node.kind === key).length
          : data.edges.filter((edge) => edge.relationType === key).length;
        // D-GRP-01 (2026-11-04 결정): 기업·사건은 끌 수 없는 개수 표시다.
        if (kind)
          return (
            <span
              key={key}
              title={help}
              aria-description={help}
              className="relationship-count shrink-0! gap-1.5! border border-zoop-line font-semibold text-zoop-ink"
            >
              <GraphIcon name={key} size={12} />
              {label} <span>{count}</span>
            </span>
          );
        return (
          <button
            key={key}
            type="button"
            aria-pressed={!hidden.includes(key)}
            title={help}
            aria-description={help}
            onClick={() => onToggle(key)}
            className="relationship-count shrink-0! gap-1.5! border border-transparent text-zoop-muted aria-pressed:border-zoop-line aria-pressed:text-zoop-ink aria-pressed:font-semibold focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-zoop-ink [&[aria-pressed=false]]:bg-transparent! [&[aria-pressed=false]]:opacity-50"
          >
            <b aria-hidden="true" className={edgeSwatchClass(key)} />
            {label} <span>{count}</span>
          </button>
        );
      })}
    </div>
  );
}
