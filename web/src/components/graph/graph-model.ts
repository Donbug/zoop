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

/** D-GRP-01 (2026-11-04 요청): 사건 제목 상자를 알약 모양으로 그린다. 위아래 여백은 글자의 1/4,
 * 양옆은 둥근 끝에 글자가 닿지 않게 3/4이고, 반지름은 한 줄 상자 높이(줄 간격 1.3 + 위아래 여백)의 절반이다. */
export const issuePillPadding = (fontSize: number): [number, number] => [
  fontSize * 0.25,
  fontSize * 0.75,
];
export const issuePillRadius = (fontSize: number) =>
  (fontSize * 1.3 + fontSize * 0.5) / 2;

/** D-GRP-01 (2026-11-04 reviews): issue nodes were 7px diamonds, then 30/36/40/48/65 diamonds.
 * Now circles of 64 (the user picked 2x of a 32 circle after comparing 32/64/80): smaller than
 * a regular company (83–119) and about 1/3 of the busiest one (188). */
export const ISSUE_NODE_SIZE = 64;

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
  // D-GRP-01: 2026-11-04 reviews enlarged every level by 25% (was 36/44/52/68/88), then
  // by another 35% (was 45/55/65/85/110) when node spacing went back to the earlier map,
  // then by another 15% (was 61/74/88/115/149), then levels 1-3 by 18% and 4-5 by 10%
  // (was 70/85/101/132/171) so small companies read better without the hubs taking over.
  return [83, 100, 119, 145, 188][level] * scale;
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
  _forcedNodes: string[] = [],
  emphasizedNodes: Set<string> = new Set(),
): GraphData {
  void _forcedNodes;
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
        // D-GRP-01 (2026-11-04 요청): 사건도 기업처럼 원으로 그린다. 크기와 진하기로 구분한다.
        type: 'circle',
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
          // D-GRP-01 (2026-11-04 요청): 사건 제목 상자는 상태 배지처럼 양끝이 둥근 알약 모양이다.
          labelBackgroundRadius: issuePillRadius(15 * scale),
          labelPadding: issuePillPadding(15 * scale),
          badges,
          cursor: 'pointer',
          opacity: dimmed ? 0.16 : 1,
        },
      };
    }),
    // D-GRP-01 (2026-11-04 결정): 사건 공유 선은 공유 사건 노드의 기업–사건–기업 연결과
    // 같은 내용이라 그리지 않는다. 관련 기업 목록(D-GRP-03)은 응답의 선을 그대로 쓴다.
    edges: data.edges
      .filter(
        (e) =>
          e.relationType !== 'SHARES_ISSUE' &&
          nodeIds.has(e.source) &&
          nodeIds.has(e.target),
      )
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
              : issueTone !== undefined && e.relationType !== 'FOLLOWS'
                ? 0.15 + 0.5 * issueTone
                : 0.75,
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
