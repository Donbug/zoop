// GraphCanvas 요소 정의: API 노드·간선 → Cytoscape 요소(채움색·글리프·캡션).
// 기업 = 상징색 원 + 로고 실루엣(없으면 이니셜, 비동기로 붙는다), 사건 = 범주색 원 + 번개 아이콘 + 근거 수 배지.
// 연결 없는 사건은 묶음 노드 하나(범주색 원 + 개수)로 바꾼다(G1). 목록 보기는 이 변환을 쓰지 않는다.
import type { ElementDefinition } from "cytoscape";
import type { Schemas } from "@/api/client";
import { badgeAspect, companyFill, contrastRatio, countGlyph, evidenceBadge, issueGlyph } from "@/lib/graph-visuals";
import { ISOLATED_BUNDLE_ID, isolatedIssues } from "@/lib/graph-view";
import { truncate } from "@/lib/utils";
import { cssVar } from "./graph-style";

/** 간선 요약은 이 글자 수를 넘으면 말줄임한다. 호버·선택한 간선에서는 전체를 보인다(G3). */
const EDGE_SUMMARY_MAX = 12;

interface Visual {
  fill: string;
  lowContrast: boolean;
  glyph?: string;
}

/** 노드 채움색·아이콘. 기업 로고 이미지는 비동기로 붙는다(없을 때는 이니셜). */
function visualOf(node: Schemas["GraphNode"], surface: string): Visual {
  if (node.kind === "issue") {
    const fill = cssVar("graph-node-issue");
    return { fill, lowContrast: false, glyph: issueGlyph(cssVar("graph-node-glyph")) };
  }
  const fill = companyFill(node.id, node.brandColor);
  return { fill, lowContrast: contrastRatio(fill, surface) < 3 };
}

/** 원문의 대상이 있으면 먼저 사용해 같은 기사에서 추출된 여러 사건도 구별한다.
 * 번역·동사 추측 없이 원문을 최대 두 줄로 줄인다. 전체 제목은 상세에 보존한다. */
function issueCaption(node: Schemas["GraphNode"]) {
  const text = (node.target?.trim() || node.label).replace(/\s+/g, " ");
  const width = /[가-힣]/.test(text) ? 12 : 24;
  if (text.length <= width) return text;
  const space = text.lastIndexOf(" ", width);
  const split = space > width / 2 ? space : width;
  return `${text.slice(0, split)}\n${truncate(text.slice(split).trim(), width)}`;
}

function companyCaption(node: Schemas["GraphNode"]) {
  const name = truncate(node.label, 16);
  const marks = [node.holding && "보유", node.watch && "관심"].filter(Boolean).join("·");
  return marks ? `${name}\n${marks}` : name;
}

export interface GraphElements {
  definitions: ElementDefinition[];
  /** 묶음에 들어간 사건 id(묶음이 없으면 비어 있음) */
  bundled: Set<string>;
}

export function toElements(nodes: Schemas["GraphNode"][], edges: Schemas["GraphEdge"][], groupIsolated: boolean): GraphElements {
  const surface = cssVar("surface-base");
  const bundled = new Set(groupIsolated ? isolatedIssues(nodes, edges).map((n) => n.id) : []);
  const badgeColors = { fill: cssVar("text-primary"), text: surface, ring: surface };
  const definitions: ElementDefinition[] = [
    ...nodes
      .filter((node) => !bundled.has(node.id))
      .map((node) => {
        // 근거 수가 있는 사건만 배지를 그린다(기업은 null).
        const evidenceCount = node.kind === "issue" ? node.evidenceCount : null;
        return {
          group: "nodes" as const,
          data: {
            id: node.id,
            kind: node.kind,
            label: node.label,
            // action 단독 동사는 구별이 어려워 쓰지 않는다. 원문 대상/제목만 두 줄로 축약한다.
            // 기업 이름 아래에 보유·관심을 글자로도 적어 테두리 모양과 함께 색 없이 구별되게 한다.
            caption: node.kind === "issue" ? issueCaption(node) : companyCaption(node),
            isFocus: node.isFocus,
            mark: node.holding && node.watch ? "both" : node.holding ? "holding" : node.watch ? "watch" : undefined,
            // 요약 라벨 순서(최신 사건 먼저)에 쓴다. 정밀도를 모르는 시각은 없는 것으로 본다.
            eventTime: node.timePrecision && node.timePrecision !== "unknown" ? node.eventTime : null,
            ...(evidenceCount !== null && { evidenceCount, badge: evidenceBadge(evidenceCount, badgeColors), badgeAspect: badgeAspect(evidenceCount) }),
            ...visualOf(node, surface),
          },
        };
      }),
    ...edges.map((edge) => ({
      group: "edges" as const,
      data: {
        id: edge.id,
        source: edge.source,
        target: edge.target,
        relationType: edge.relationType,
        summary: edge.summary,
        short: edge.summary.length > EDGE_SUMMARY_MAX ? `${edge.summary.slice(0, EDGE_SUMMARY_MAX - 1)}…` : edge.summary,
        evidenceIds: edge.evidenceIds,
      },
    })),
  ];
  if (bundled.size > 0) {
    definitions.push({
      group: "nodes",
      data: {
        id: ISOLATED_BUNDLE_ID,
        kind: "bundle",
        label: "연결 없는 사건",
        caption: `연결 없는 사건 ${bundled.size}`,
        count: bundled.size,
        fill: cssVar("graph-node-issue"),
        lowContrast: false,
        glyph: countGlyph(bundled.size, cssVar("graph-node-glyph")),
      },
    });
  }
  return { definitions, bundled };
}
