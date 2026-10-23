import type { GraphData } from '@antv/g6';
import type { GraphResponse } from '@/types/map/graph';
import { isSelectableRelation } from '@/types/map/relation';
import layouts from './figma-layout.json';
import { companyLogo, logoScale, logoBackground } from '@/util/company-logo';
import { themeColor } from '@/util/theme-color';
import { separateNodes, shortTitle } from './graph-geometry';

export function graphSummary(data: GraphResponse) {
  const companyNodes = data.nodes.filter((n) => n.kind === 'company');
  const nodesById = new Map(data.nodes.map((node) => [node.id, node]));
  const incidentSets = new Map(
    data.nodes
      .filter((node) => node.kind === 'issue')
      .map((node) => [node.id, new Set<string>()]),
  );
  const companyIssueSets = new Map(
    companyNodes.map((node) => [node.id, new Set<string>()]),
  );
  for (const edge of data.edges) {
    if (
      edge.relationType !== 'INVOLVES' &&
      edge.relationType !== 'STRUCTURALLY_RELATED_TO'
    )
      continue;
    const source = nodesById.get(edge.source);
    const target = nodesById.get(edge.target);
    const issue = source?.kind === 'issue' ? source : target;
    const company = source?.kind === 'company' ? source : target;
    if (issue?.kind !== 'issue' || company?.kind !== 'company') continue;
    incidentSets.get(issue.id)?.add(company.id);
    companyIssueSets.get(company.id)?.add(issue.id);
  }
  const incident = new Map(
    [...incidentSets].map(([issueId, companyIds]) => [
      issueId,
      [...companyIds],
    ]),
  );
  const companyIssueCounts = new Map(
    [...companyIssueSets].map(([companyId, issueIds]) => [
      companyId,
      issueIds.size,
    ]),
  );
  const folded = new Map<string, number>();
  incident.forEach((ids, issueId) => {
    if (ids.length === 1 && !nodesById.get(issueId)?.isFocus)
      folded.set(ids[0], (folded.get(ids[0]) ?? 0) + 1);
  });
  return {
    companyNodes,
    incident,
    companyIssueCounts,
    folded,
    company: companyNodes.length,
    issue: incident.size,
    holding: companyNodes.filter((n) => n.holding).length,
    watch: companyNodes.filter((n) => n.watch).length,
    direct: data.edges.filter(
      (e) =>
        e.relationType === 'INVOLVES' ||
        e.relationType === 'STRUCTURALLY_RELATED_TO',
    ).length,
    follows: data.edges.filter((e) => e.relationType === 'FOLLOWS').length,
    shared: data.edges.filter((e) => e.relationType === 'SHARES_ISSUE').length,
    sharedIssues: [...incident.values()].filter((ids) => ids.length > 1).length,
    disconnected: [...incident.values()].filter((ids) => ids.length === 0)
      .length,
  };
}

// Review calibration for D-GRP-01/01b fixture distribution (0–6 issues).
// The value represents graph activity only, never importance or causality.
export function companyNodeSize(issueCount: number, scale = 1) {
  const level =
    issueCount <= 0
      ? 0
      : issueCount === 1
        ? 1
        : issueCount === 2
          ? 2
          : issueCount <= 4
            ? 3
            : 4;
  return [36, 44, 52, 68, 88][level] * scale;
}

export function focusNeighborhood(
  data: GraphResponse,
  focusId: string | null,
  hops: 1 | 2,
) {
  if (!focusId || !data.nodes.some((node) => node.id === focusId))
    return new Set<string>();
  const visible = new Set([focusId]);
  let frontier = new Set([focusId]);
  for (let depth = 0; depth < hops; depth += 1) {
    const next = new Set<string>();
    data.edges.forEach((edge) => {
      if (frontier.has(edge.source) && !visible.has(edge.target))
        next.add(edge.target);
      if (frontier.has(edge.target) && !visible.has(edge.source))
        next.add(edge.source);
    });
    next.forEach((id) => visible.add(id));
    frontier = next;
  }
  return visible;
}

// Figma 619:1819 / 619:2374 presentation only; API DTOs never contain x/y.
const issueLayout: Record<string, [number, number, number, number]> = {
  'HBM4 공급 계약': [559, 218, 302, 301],
  'HBM3E 12단 경쟁': [756, 113, 341, 261],
  'ASML 제조 협력 확대': [773, 346, 367, 347],
  '램프 10억 달러 투자': [951, 329, 527, 234],
  'FSD 칩 위탁 생산': [832, 426, 334, 178],
  'AI 통신망 MOU': [1120, 490, 706, 299],
  'TSMC 2나노 증설': [497, 128, 200, 280],
  '스냅드래곤 엑시노스 경쟁': [472, 211, 200, 300],
  'Azure GPU 증설': [517, 543, 400, 400],
};
export function toG6Data(
  data: GraphResponse,
  width: number,
  height: number,
  expandedId?: string | null,
  forcedNodes: string[] = [],
  emphasizedNodes: Set<string> = new Set(),
): GraphData {
  const summary = graphSummary(data);
  const personal = data.metadata.mode === 'personal';
  const layout = personal ? layouts.personal : layouts.all;
  const sx = width / 1245.33,
    sy = height / 705.33,
    scale = personal ? 0.69 : 1;
  const followsIds = new Set(
    data.edges
      .filter((e) => e.relationType === 'FOLLOWS')
      .flatMap((e) => [e.source, e.target]),
  );
  const visible = data.nodes.filter(
    (n) =>
      forcedNodes.includes(n.id) ||
      n.kind === 'company' ||
      n.isFocus ||
      n.id === expandedId ||
      (summary.incident.get(n.id)?.length ?? 0) > 1 ||
      followsIds.has(n.id),
  );
  const nodeIds = new Set(visible.map((n) => n.id));
  const positions = new Map<
    string,
    { x: number; y: number; size: number; symbol: string | null }
  >();
  summary.companyNodes.forEach((n, i) => {
    const found = layout.find((p) => p.label === n.label);
    // Real API companies outside the fixture use a deterministic ring layout.
    positions.set(
      n.id,
      found ??
        (n.label === 'KT'
          ? {
              x: personal ? 657 : 1029,
              y: personal ? 384 : 405,
              size: 22 * scale,
              symbol: 'K',
            }
          : {
              x: 623 + Math.cos(i * 2.4) * 360,
              y: 353 + Math.sin(i * 2.4) * 250,
              size: 26 * scale,
              symbol: n.label.slice(0, 1),
            }),
    );
  });
  const result: GraphData = {
    nodes: visible.map((n, i) => {
      const company = n.kind === 'company',
        p = positions.get(n.id),
        planned = issueLayout[n.label];
      const neighbors = (summary.incident.get(n.id) ?? [])
        .map((id) => positions.get(id))
        .filter((v) => v !== undefined);
      const x =
        p?.x ??
        (planned
          ? planned[personal ? 2 : 0]
          : (neighbors.length
              ? neighbors.reduce((v, n) => v + n.x, 0) / neighbors.length
              : 1000) +
            Math.cos(i) * 50);
      const y =
        p?.y ??
        (planned
          ? planned[personal ? 3 : 1]
          : (neighbors.length
              ? neighbors.reduce((v, n) => v + n.y, 0) / neighbors.length
              : 400) +
            Math.sin(i) * 50);
      const size = company
        ? companyNodeSize(summary.companyIssueCounts.get(n.id) ?? 0, scale)
        : 7 * scale;
      const badges = [
        ...(company && summary.folded.has(n.id)
          ? [
              {
                text: `ϟ${summary.folded.get(n.id)}`,
                placement: 'right-top' as const,
                fill: themeColor('muted'),
                background: false,
                fontSize: 7.178 * scale,
                fontFamily: 'JetBrains Mono Variable',
              },
            ]
          : []),
        ...(n.holding || n.watch
          ? [
              {
                text: [n.holding ? '보유' : '', n.watch ? '관심' : '']
                  .filter(Boolean)
                  .join('·'),
                placement: 'bottom' as const,
                offsetY: 12,
                fill: themeColor('ink'),
                backgroundFill: themeColor('soft'),
                fontSize: 8,
              },
            ]
          : []),
      ];
      const dimmed = emphasizedNodes.size > 0 && !emphasizedNodes.has(n.id);
      const logo = company ? companyLogo(n.id, n.logoUrl) : null;
      const iconSize = logo ? size * logoScale(logo) : size;
      return {
        id: n.id,
        type: company ? 'circle' : 'diamond',
        data: { kind: n.kind },
        style: {
          // Spread positions without inflating node icons or labels.
          x: width / 2 + (x * sx - width / 2) * 1.75,
          y: height / 2 + (y * sy - height / 2) * 1.65,
          size,
          fill: company
            ? logo
              ? logoBackground(logo)
              : themeColor('paper')
            : themeColor('ink'),
          stroke: themeColor('ink'),
          lineWidth: n.isFocus ? 1.4 : 0.667,
          halo: n.isFocus,
          haloStroke: themeColor('ink'),
          haloLineWidth: 0.667,
          haloFill: 'transparent',
          haloStrokeOpacity: 1,
          icon: company,
          iconSrc: logo ?? undefined,
          iconText: logo ? undefined : (p?.symbol ?? n.label.slice(0, 1)),
          iconWidth: iconSize,
          iconHeight: iconSize,
          iconRadius: logoScale(logo) === 1 ? size / 2 : 0,
          iconFontSize: size * 0.34,
          iconFontFamily: 'Inter Variable',
          iconFontWeight: 700,
          iconFill: n.brandColor ?? themeColor('ink'),
          labelText: company ? n.label : shortTitle(n.label, 13 * scale),
          labelPlacement: company ? 'bottom' : 'top',
          labelFontFamily: company ? 'Inter Variable' : 'Pretendard Variable',
          labelFontSize: (company ? 17.2 : 13) * scale,
          labelFontWeight: company ? 500 : 700,
          labelFill: company ? themeColor('muted') : themeColor('ink'),
          labelOffsetY: company ? (n.holding || n.watch ? 28 : 10) : -5,
          labelBackground: !company,
          labelBackgroundFill: themeColor('paper'),
          labelBackgroundStroke: themeColor('ink'),
          labelBackgroundLineWidth: 0.5,
          labelBackgroundRadius: 8,
          labelPadding: [2, 7],
          badges,
          cursor: 'pointer',
          opacity: dimmed ? 0.16 : 1,
        },
      };
    }),
    edges: data.edges
      .filter((e) => nodeIds.has(e.source) && nodeIds.has(e.target))
      .map((e) => {
        const dimmed =
          emphasizedNodes.size > 0 &&
          (!emphasizedNodes.has(e.source) || !emphasizedNodes.has(e.target));
        return {
          id: e.id,
          source: e.source,
          target: e.target,
          style: {
            stroke:
              e.relationType === 'FOLLOWS' ? '#c0362c' : themeColor('faint'),
            lineWidth: 0.65,
            strokeOpacity: dimmed
              ? 0.08
              : e.relationType === 'SHARES_ISSUE'
                ? 0.5
                : 0.75,
            lineDash: e.relationType === 'SHARES_ISSUE' ? [2, 4] : undefined,
            endArrow: e.relationType === 'FOLLOWS',
            endArrowSize: 4,
            cursor: isSelectableRelation(e) ? 'pointer' : 'default',
            increasedLineWidthForHitTesting: isSelectableRelation(e) ? 8 : 0,
          },
        };
      }),
  };
  result.nodes = separateNodes(result.nodes ?? []);
  return result;
}
