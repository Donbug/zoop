import type { GraphData } from '@antv/g6';
import type { GraphResponse } from '@/types/map/graph';
import { isSelectableRelation } from '@/types/map/relation';
import { leafRank, relationshipPositions } from './relationship-layout';
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

/** D-GRP-01: single-company issues each company shows before it is selected. */
export const ISSUES_PER_COMPANY = 5;

/**
 * D-GRP-01 (2026-11-04 review): a company shows at most ISSUES_PER_COMPANY of the
 * issues that involve only it (most evidence, then latest first). The rest fold into
 * a "+N" badge until the company is selected. Shared, focus and follow-up issues,
 * the selected issue and any forced node always stay.
 */
export function foldedIssues(
  data: GraphResponse,
  expandedId?: string | null,
  forcedNodes: string[] = [],
) {
  const summary = graphSummary(data);
  const follows = new Set(
    data.edges
      .filter((e) => e.relationType === 'FOLLOWS')
      .flatMap((e) => [e.source, e.target]),
  );
  const byCompany = new Map<string, GraphResponse['nodes']>();
  for (const node of data.nodes) {
    const companies = summary.incident.get(node.id);
    if (
      node.kind !== 'issue' ||
      companies?.length !== 1 ||
      node.isFocus ||
      follows.has(node.id)
    )
      continue;
    byCompany.set(companies[0], [...(byCompany.get(companies[0]) ?? []), node]);
  }
  const hidden = new Set<string>();
  const counts = new Map<string, number>();
  for (const [companyId, issues] of byCompany) {
    if (companyId === expandedId) continue;
    const folded = [...issues]
      .sort(leafRank)
      .slice(ISSUES_PER_COMPANY)
      .filter((n) => n.id !== expandedId && !forcedNodes.includes(n.id));
    folded.forEach((n) => hidden.add(n.id));
    if (folded.length) counts.set(companyId, folded.length);
  }
  return { hidden, counts };
}

/** D-GRP-01 (2026-11-04 review): issue diamonds were 7px and hard to spot. */
export const ISSUE_NODE_SIZE = 30;

/**
 * D-GRP-01: 0..1 evidence strength per issue on a log scale against the busiest
 * issue on this map, so one heavily sourced issue does not flatten the rest.
 */
export function evidenceStrength(data: GraphResponse) {
  const issues = data.nodes.filter((n) => n.kind === 'issue');
  const max = Math.max(1, ...issues.map((n) => n.evidenceCount ?? 0));
  return new Map(
    issues.map((n) => [
      n.id,
      Math.log1p(Math.max(0, n.evidenceCount ?? 0)) / Math.log1p(max),
    ]),
  );
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
  // D-GRP-01: 2026-11-04 review enlarged every level by 25% (was 36/44/52/68/88).
  return [45, 55, 65, 85, 110][level] * scale;
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
  const scale = personal ? 0.69 : 1;
  const positions = relationshipPositions(data);
  // D-GRP-01: every company keeps up to ISSUES_PER_COMPANY of its own issues and
  // their INVOLVES edges, so related companies never look disconnected (#543);
  // the rest fold into a "+N" badge until the company is selected.
  const fold = foldedIssues(data, expandedId, forcedNodes);
  const visible = data.nodes.filter((n) => !fold.hidden.has(n.id));
  const nodeIds = new Set(visible.map((n) => n.id));
  const strength = evidenceStrength(data);
  const result: GraphData = {
    nodes: visible.map((n) => {
      const company = n.kind === 'company';
      const position = positions.get(n.id)!;
      // D-GRP-03: 고른 기업의 이름은 주변보다 크고 진하게 보인다.
      const chosen = company && n.id === expandedId;
      const size = company
        ? companyNodeSize(summary.companyIssueCounts.get(n.id) ?? 0, scale)
        : ISSUE_NODE_SIZE * scale;
      const tone = company ? 1 : (strength.get(n.id) ?? 0);
      const badges = [
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
                fontSize: 10 * scale,
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
        data: { kind: n.kind, chosen, folded: fold.counts.get(n.id) ?? 0 },
        style: {
          // Camera and styling remain independent of relationship placement.
          x: width / 2 + position.x,
          y: height / 2 + position.y,
          size,
          fill: company
            ? logo
              ? logoBackground(logo)
              : themeColor('paper')
            : themeColor('ink'),
          // D-GRP-01: monotone shade by evidence; weak issues read as a light outline.
          fillOpacity: company ? 1 : 0.15 + 0.85 * tone,
          stroke: themeColor('ink'),
          lineWidth: n.isFocus ? 1.4 : 0.667,
          halo: n.isFocus,
          haloStroke: themeColor('ink'),
          haloLineWidth: 0.667,
          haloFill: 'transparent',
          haloStrokeOpacity: 1,
          icon: company,
          iconSrc: logo ?? undefined,
          iconText: logo ? undefined : n.label.slice(0, 1),
          iconWidth: iconSize,
          iconHeight: iconSize,
          iconRadius: logoScale(logo) === 1 ? size / 2 : 0,
          iconFontSize: size * 0.34,
          iconFontFamily: 'SUIT Variable',
          iconFontWeight: 700,
          iconFill: n.brandColor ?? themeColor('ink'),
          labelText: company
            ? n.label
            : shortTitle(n.label, 15 * scale, 220 * scale),
          labelPlacement: company ? 'bottom' : 'top',
          labelFontFamily: company
            ? 'Pretendard Variable'
            : 'Wanted Sans Variable',
          labelFontSize: (company ? (chosen ? 24 : 19) : 15) * scale,
          labelFontWeight: chosen ? 800 : company ? 500 : 700,
          labelFill: themeColor('ink'),
          labelOffsetY: company ? (n.holding || n.watch ? 28 : 10) : -5,
          labelBackground: !company,
          labelBackgroundFill: themeColor('paper'),
          labelBackgroundStroke: themeColor('ink'),
          labelBackgroundLineWidth: 0.5,
          labelBackgroundRadius: 8,
          labelPadding: [3, 8],
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
        const issueTone = strength.get(e.source) ?? strength.get(e.target);
        return {
          id: e.id,
          source: e.source,
          target: e.target,
          style: {
            // D-GRP-01: 관계 설명은 상세·키보드 목록에 남기고 선 위 이름표는 표시하지 않아요.
            labelText: '',
            labelVisibility: 'hidden',
            stroke:
              e.relationType === 'FOLLOWS' || issueTone !== undefined
                ? themeColor('ink')
                : themeColor('faint'),
            lineWidth: 1.3,
            // D-GRP-01: an issue's line follows its evidence shade (monotone).
            strokeOpacity: dimmed
              ? 0.08
              : e.relationType === 'SHARES_ISSUE'
                ? 0.5
                : issueTone !== undefined && e.relationType !== 'FOLLOWS'
                  ? 0.15 + 0.5 * issueTone
                  : 0.75,
            lineDash: e.relationType === 'SHARES_ISSUE' ? [2, 4] : undefined,
            endArrow: e.relationType === 'FOLLOWS',
            endArrowSize: 6,
            cursor: isSelectableRelation(e) ? 'pointer' : 'default',
            increasedLineWidthForHitTesting: isSelectableRelation(e) ? 8 : 0,
          },
        };
      }),
  };
  result.nodes = separateNodes(result.nodes ?? []);
  return result;
}
