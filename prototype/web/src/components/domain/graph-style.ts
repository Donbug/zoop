// GraphCanvas 스타일: 토큰 읽기, 라벨 LOD, Cytoscape 스타일시트.
// - 모든 노드는 원, 구분은 색. 관계 유형은 선 모양(실선·파선·점선)과 화살표. 사건 공유(파생)만 방향이 없다.
// - 라벨 LOD: 화면 글자는 최소 13px. 기업명은 유지하고 사건·관계 요약은 확대나 선택으로 읽는다.
// - 간선 요약(G3): 평소에는 12자 말줄임. 노드를 고르면 최신 사건 순 6개(.labelled)만, 나머지(.quiet)는 호버·선택 때 전체.
// - 근거 수 배지(G4): 사건 노드 오른쪽 위, 두 번째 배경 이미지 층. 배율이 낮으면 숨긴다.
// - 묶음(G1): 범주색 원 + 개수, 이중 테두리로 사건 여러 개가 겹친 것을 나타낸다.
// - 포커스·범례 필터로 숨긴 요소는 display: none(재배치 없음).
// - 경로(G6): 경로 노드·선만 선명하고(나머지는 .dimmed), 경로 선 요약은 배율·선 수와 관계없이 전체를 보인다.
import type cytoscape from "cytoscape";
import type { StylesheetJson } from "cytoscape";

export function cssVar(name: string) {
  return getComputedStyle(document.documentElement).getPropertyValue(`--zoop-${name}`).trim();
}

/** 토큰 곡선 "cubic-bezier(…)"을 Cytoscape 애니메이션 easing으로 쓴다. Cytoscape는 이 표기를 파싱하지만
 *  타입 정의에는 매개변수형 문자열이 없어 캐스팅한다. */
export function easingVar(name: "standard" | "enter-expressive") {
  return (cssVar(`motion-easing-${name}`) || "ease-in-out") as cytoscape.Css.TransitionTimingFunction;
}

export function msVar(name: string) {
  return Number.parseFloat(cssVar(`motion-duration-${name}`)) || 0;
}

/** 라벨 LOD 단계. 배율이 바뀔 때마다 스타일을 다시 입히지 않도록 단계가 바뀔 때만 갱신한다. */
export interface Lod {
  /** 모델 좌표 글자 크기 배수(화면 글자를 13px로 유지) */
  scale: number;
  nodeLabels: boolean;
  edgeLabels: boolean;
  badges: boolean;
}

const BASE_FONT = 13;
// 화면 글자가 13px 아래로 작아지지 않게 배율에 반비례해 키우되 이 배율보다 작아지면 라벨을 숨긴다.
const NODE_LABEL_MIN_ZOOM = 0.55;
const EDGE_LABEL_MIN_ZOOM = 0.95;
// 선이 많으면 확대해도 강조된(호버·선택) 간선의 요약만 보인다.
const EDGE_LABEL_BUDGET = 160;
// 배지 숫자가 화면에서 13px 아래로 작아지지 않도록 배지도 배율에 반비례해 키우고, 이 배율 아래에서는 숨긴다.
const BADGE_MIN_ZOOM = 0.8;
/** 배지 지름(모델 좌표, 배율 1 기준). 숫자는 지름의 0.56배라 24px이면 13.4px. */
const BADGE_SIZE = 24;

export function lodFor(zoom: number, edgeCount: number): Lod {
  return {
    scale: Math.ceil((1 / Math.min(1, Math.max(0.1, zoom))) * 20) / 20,
    nodeLabels: zoom >= NODE_LABEL_MIN_ZOOM,
    edgeLabels: zoom >= EDGE_LABEL_MIN_ZOOM && edgeCount <= EDGE_LABEL_BUDGET,
    badges: zoom >= BADGE_MIN_ZOOM,
  };
}

/** 연결 없는 사건 묶음의 모델 크기: 기업처럼 축소해도 화면에서 48px(누르는 영역 44px 이상)을 지켜 개수 글자가 읽힌다. */
export function bundleSizeAt(zoom: number, isMobile: boolean) {
  return Math.max(isMobile ? 56 : 52, 48 * lodFor(zoom, 0).scale);
}

export function buildStyle(isMobile: boolean, lod: Lod): StylesheetJson {
  const font = getComputedStyle(document.documentElement).getPropertyValue("--font-sans").trim();
  const fontSize = BASE_FONT * lod.scale;
  const companySize = Math.max(isMobile ? 72 : 64, 44 * lod.scale);
  const issueSize = isMobile ? 36 : 32;
  const bundleSize = bundleSizeAt(1 / lod.scale, isMobile);
  const badge = BADGE_SIZE * lod.scale;
  const labelBackground = {
    "text-background-color": cssVar("surface-base"),
    "text-background-opacity": 0.92,
    "text-background-padding": "2px",
    "text-background-shape": "roundrectangle",
  } as const;
  return [
    {
      selector: "node",
      style: {
        shape: "ellipse",
        label: lod.nodeLabels ? "data(caption)" : "",
        "font-family": font,
        "font-size": fontSize,
        "font-weight": 500,
        color: cssVar("text-primary"),
        "text-valign": "bottom",
        "text-margin-y": 5 * lod.scale,
        "text-wrap": "wrap",
        "text-max-width": `${180 * lod.scale}px`,
        ...labelBackground,
        "background-color": "data(fill)",
        "background-fit": "contain",
        "background-clip": "node",
        "border-width": 0,
        "overlay-opacity": 0,
        "transition-property": "opacity",
        "transition-duration": msVar("normal"),
      },
    },
    { selector: "node[glyph]", style: { "background-image": "data(glyph)", "background-width": "100%", "background-height": "100%" } },
    { selector: 'node[kind = "company"]', style: { label: "data(caption)", width: companySize, height: companySize, "font-weight": 600 } },
    { selector: 'node[kind = "company"][?isFocus]', style: { width: companySize + 12, height: companySize + 12 } },
    {
      selector: 'node[kind = "issue"]',
      style: {
        width: issueSize, height: issueSize, "background-width": "56%", "background-height": "56%",
        // 수동 줄바꿈만 적용해 캡션이 세 줄 이상으로 늘어나지 않게 한다.
        "text-max-width": "1000px", "line-height": 1.25,
      },
    },
    {
      selector: 'node[kind = "bundle"]',
      style: {
        label: "data(caption)", width: bundleSize, height: bundleSize, "font-weight": 600,
        "background-width": "72%", "background-height": "72%",
        // 겹쳐 쌓인 사건 더미: 바깥 이중 테두리(색 대신 모양 신호)
        "border-width": 5 * lod.scale, "border-style": "double", "border-color": cssVar("graph-node-issue"),
      },
    },
    ...(lod.badges
      ? [
          {
            selector: "node[badge]",
            style: {
              // 첫 층은 번개, 둘째 층은 근거 수 배지(노드 밖으로 걸쳐 그린다).
              "background-image": (ele: cytoscape.NodeSingular) => [ele.data("glyph"), ele.data("badge")],
              "background-width": (ele: cytoscape.NodeSingular) => ["56%", `${badge * ele.data("badgeAspect")}px`],
              "background-height": ["56%", `${badge}px`],
              "background-position-x": ["50%", "100%"],
              "background-position-y": ["50%", "0%"],
              "background-offset-x": [0, badge * 0.45],
              "background-offset-y": [0, -badge * 0.45],
              "background-clip": ["node", "none"],
              "background-image-containment": ["inside", "over"],
              "bounds-expansion": badge,
            },
          } as unknown as StylesheetJson[number],
        ]
      : []),
    // 배경과 대비가 3:1보다 낮은 상징색(예: 다크 테마의 검정 로고색)은 얇은 테두리로 윤곽을 보장한다.
    { selector: "node[?lowContrast]", style: { "border-width": 1.5, "border-color": cssVar("border-control") } },
    // 보유·관심은 색이 아니라 테두리 모양으로 구별한다: 보유 실선, 관심 점선, 둘 다 이중선. 캡션에도 글자로 적는다.
    { selector: "node[mark]", style: { "border-width": 3, "border-color": cssVar("graph-node-mark") } },
    { selector: 'node[mark = "watch"]', style: { "border-style": "dashed" } },
    { selector: 'node[mark = "both"]', style: { "border-width": 7, "border-style": "double" } },
    {
      selector: "edge",
      style: {
        "curve-style": "bezier",
        // 같은 두 노드 사이 여러 선은 요약이 겹치지 않게 곡선 간격을 넓힌다.
        "control-point-step-size": 64,
        width: 2,
        "line-color": cssVar("graph-edge-involves"),
        "target-arrow-color": cssVar("graph-edge-involves"),
        "target-arrow-shape": "triangle",
        "arrow-scale": 0.8,
        label: lod.edgeLabels ? "data(short)" : "",
        "font-family": font,
        "font-size": fontSize,
        color: cssVar("graph-edge-label"),
        "text-rotation": "autorotate",
        "text-margin-y": -8 * lod.scale,
        "text-wrap": "none",
        "text-overflow-wrap": "anywhere",
        "line-height": 1.2,
        ...labelBackground,
        "overlay-opacity": 0,
        "transition-property": "opacity, width",
        "transition-duration": msVar("fast"),
      },
    },
    {
      selector: 'edge[relationType = "STRUCTURALLY_RELATED_TO"]',
      style: {
        "line-color": cssVar("graph-edge-structurally-related"),
        "target-arrow-color": cssVar("graph-edge-structurally-related"),
        "line-style": "dashed",
        "line-dash-pattern": [6, 3],
      },
    },
    {
      selector: 'edge[relationType = "FOLLOWS"]',
      style: { "line-color": cssVar("graph-edge-follows"), "target-arrow-color": cssVar("graph-edge-follows"), width: 1.5 },
    },
    {
      selector: 'edge[relationType = "SHARES_ISSUE"]',
      style: {
        "line-color": cssVar("graph-edge-shares-issue"),
        "line-style": "dotted",
        "line-dash-pattern": [2, 3],
        width: 1.5,
        "target-arrow-shape": "none",
      },
    },
    // 강조(호버한 노드의 이웃, 선택의 이웃)는 배율과 관계없이 노드 캡션을 보인다. 간선 요약은 .labelled만.
    { selector: "node.emph", style: { label: "data(caption)", "z-index": 20 } },
    { selector: "edge.emph", style: { width: 3, "z-index": 10 } },
    { selector: "edge.labelled", style: { label: "data(short)", "z-index": 15 } },
    { selector: "edge.quiet", style: { label: "" } },
    // 호버·선택한 간선은 말줄임 없이 전체 요약을 줄바꿈해 보인다.
    { selector: "edge.hover", style: { label: "data(summary)", "text-wrap": "wrap", "text-max-width": `${160 * lod.scale}px`, "z-index": 40 } },
    {
      selector: "node.focused",
      style: {
        label: "data(caption)",
        "font-weight": 700,
        "outline-width": 3,
        "outline-color": cssVar("graph-focus-ring"),
        "outline-offset": 3,
        "outline-opacity": 1,
        "z-index": 30,
      },
    },
    { selector: "edge.focused", style: { label: "data(summary)", "text-wrap": "wrap", "text-max-width": `${160 * lod.scale}px`, width: 4, "z-index": 30 } },
    { selector: ".faded", style: { opacity: 0.35, label: "" } },
    { selector: ".dimmed", style: { opacity: Number(cssVar("graph-dimmed-opacity")) || 0.22, label: "" } },
    // 경로 규칙은 호버가 붙이는 .quiet보다 뒤에 둬 요약이 사라지지 않게 한다.
    { selector: "node.path", style: { label: "data(caption)", "z-index": 25 } },
    { selector: "edge.path", style: { label: "data(summary)", "text-wrap": "wrap", "text-max-width": `${160 * lod.scale}px`, width: 4, "z-index": 25 } },
    { selector: ".focus-hidden, .filter-hidden", style: { display: "none" } },
    { selector: "node.entering", style: { opacity: 0 } },
  ];
}
