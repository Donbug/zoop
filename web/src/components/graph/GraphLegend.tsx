import GraphIcon from './GraphIcon';
import type { GraphResponse } from '@/types/map/graph';
import type { LegendKey } from './graph-view';
import { edgeSwatchClass } from './edge-swatch';

// D-GRP-01/01b: a single horizontal legend controls graph visibility.
const entries: [LegendKey, string, string][] = [
  [
    'company',
    '기업',
    '기업 노드입니다. 원 크기는 연결된 사건 수(활동량)를 나타냅니다.',
  ],
  [
    'issue',
    '사건',
    '사건 노드입니다. 공시·기사에서 확인된 사건이며 여러 기업이 함께 연결될 수 있습니다.',
  ],
  [
    'INVOLVES',
    '직접 관련',
    '직접 관련: 기업이 사건의 당사자입니다. 계약 당사자나 공시 주체처럼 기사·공시에 행위자로 나옵니다.',
  ],
  [
    'STRUCTURALLY_RELATED_TO',
    '구조적 관련',
    '구조적 관련: 사건의 당사자는 아니지만 공급망·지분·고객 관계 같은 구조로 영향이 닿는 기업입니다. 관계에 유효 기간이 있을 수 있습니다.',
  ],
  [
    'FOLLOWS',
    '후속 사건',
    '후속 사건: 앞 사건 다음에 이어서 일어난 사건을 잇는 선입니다. 뒤 사건이 아직 일어나지 않았으면 나타나지 않습니다.',
  ],
  [
    'SHARES_ISSUE',
    '사건 공유',
    '사건 공유: 두 기업이 같은 사건에 각각 직접 또는 구조적으로 연결되어 있을 때 그리는 선입니다. 두 기업 사이의 관계를 기사가 따로 말한 것은 아니며, 근거는 공유한 사건의 근거를 따릅니다.',
  ],
];

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
        const disabled =
          kind &&
          !hidden.includes(key) &&
          hidden.includes(key === 'company' ? 'issue' : 'company');
        return (
          <button
            key={key}
            type="button"
            aria-pressed={!hidden.includes(key)}
            disabled={disabled}
            title={help}
            aria-description={help}
            onClick={() => onToggle(key)}
            className="relationship-count max-md:min-h-10 max-md:min-w-10 shrink-0! gap-1.5! border border-transparent text-zoop-muted aria-pressed:border-zoop-line aria-pressed:text-zoop-ink aria-pressed:font-semibold focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-zoop-ink disabled:cursor-not-allowed disabled:opacity-60 [&[aria-pressed=false]]:bg-transparent! [&[aria-pressed=false]]:opacity-50"
          >
            {kind ? (
              <GraphIcon name={key} size={12} />
            ) : (
              <b aria-hidden="true" className={edgeSwatchClass(key)} />
            )}
            {label} <span>{count}</span>
          </button>
        );
      })}
    </div>
  );
}
