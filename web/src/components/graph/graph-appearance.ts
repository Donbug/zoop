import { createContext } from 'react';
import type { GraphData } from '@antv/g6';
import { separateNodes } from './graph-geometry';

export type GraphAppearance = {
  variant: 'original' | 'improved';
  theme: 'light' | 'dark';
  preview?: boolean;
};
export const defaultAppearance: GraphAppearance = {
  variant: 'original',
  theme: 'light',
};
// Comparisons can override the production map's appearance explicitly.
export const GraphAppearanceContext = createContext<GraphAppearance | null>(
  null,
);
export function appearanceColors(appearance: GraphAppearance) {
  const dark = appearance.theme === 'dark';
  return {
    ink: dark ? '#f5f5f5' : '#1a1a1a',
    paper: dark ? '#262626' : '#ffffff',
    muted: dark ? '#d4d4d4' : '#55554f',
    line: dark ? '#a5a9b1' : '#71757c',
    selected:
      appearance.variant === 'improved'
        ? dark
          ? '#d4d4d8'
          : '#414146'
        : dark
          ? '#f5f5f5'
          : '#1a1a1a',
  };
}
export function styleGraph(
  data: GraphData,
  appearance: GraphAppearance,
): GraphData {
  if (appearance.variant === 'original') return data;
  const dark = appearance.theme === 'dark';
  const colors = appearanceColors(appearance);
  const result: GraphData = {
    ...data,
    nodes: data.nodes?.map((node) => ({
      ...node,
      style: {
        ...node.style,
        size:
          Number(node.style?.size ?? 20) *
          (node.data?.kind === 'company' ? 1.15 : 1.1),
        ...(node.data?.kind === 'company'
          ? {
              iconWidth:
                Number(node.style?.iconWidth ?? node.style?.size ?? 20) * 1.15,
              iconHeight:
                Number(node.style?.iconHeight ?? node.style?.size ?? 20) * 1.15,
              iconRadius: Number(node.style?.iconRadius ?? 0) * 1.15,
              iconFontSize: Number(node.style?.iconFontSize ?? 12) * 1.15,
              shadowColor: dark ? 'rgba(0,0,0,0.35)' : 'rgba(24,24,27,0.14)',
              shadowBlur: 5,
              shadowOffsetY: 2,
            }
          : {}),
        labelFontSize: Number(node.style?.labelFontSize ?? 13) * 1.15,
        labelFontWeight: node.data?.chosen ? 800 : 600,
        fill:
          node.data?.kind === 'company'
            ? node.style?.iconSrc
              ? (node.style?.fill ?? '#ffffff')
              : colors.paper
            : colors.ink,
        stroke: dark ? '#747478' : '#b8b8b6',
        haloStroke: colors.ink,
        labelFill:
          node.data?.kind === 'company' && !node.data?.chosen
            ? colors.muted
            : colors.ink,
        labelBackgroundFill: colors.paper,
        labelBackgroundStroke: dark ? '#6b6b70' : '#bababa',
        // Dimmed nodes fade more on a dark map; keep them legible as context.
        ...(dark && Number(node.style?.opacity ?? 1) < 1
          ? { opacity: 0.38 }
          : {}),
      },
    })),
    edges: data.edges?.map((edge) => {
      const follows = !!edge.style?.endArrow;
      const shared = !!edge.style?.lineDash;
      const dimmed = Number(edge.style?.strokeOpacity) < 0.1;
      return {
        ...edge,
        style: {
          ...edge.style,
          stroke: follows ? colors.ink : dark ? '#a5a9b1' : '#71757c',
          lineWidth: shared ? 1.5 : 1.95,
          strokeOpacity: dimmed ? 0.2 : shared ? 0.75 : 0.95,
        },
      };
    }),
  };
  // Enlarged labels participate in fitting and collision separation.
  result.nodes = separateNodes(result.nodes ?? []);
  return result;
}

/** 화면에서 이름표가 이보다 작아지지 않게 한다(px). 사건은 간선 위 짧은 이름이라 조금 작게 둔다. */
export const MIN_LABEL_PX = { company: 12, issue: 11 } as const;

/**
 * D-GRP-01: 지도를 축소해도 이름표를 읽을 수 있게 화면 기준 최소 크기를 지킨다.
 * 흐리게 처리한(선택과 관련 없는) 노드는 원래 크기를 두어 선택 주변 이름이 먼저 읽히게 한다.
 * 노드 크기·좌표·카메라는 바꾸지 않는다. 원래 크기는 data.labelBase에 남겨 확대 수준이 바뀌면 다시 계산한다.
 */
export function readableLabels(data: GraphData, zoom: number): GraphData {
  if (!(zoom > 0)) return data;
  return {
    ...data,
    nodes: data.nodes?.map((node) => {
      const base = Number(
        node.data?.labelBase ?? node.style?.labelFontSize ?? 13,
      );
      const dimmed = Number(node.style?.opacity ?? 1) < 1;
      const min =
        node.data?.kind === 'company'
          ? MIN_LABEL_PX.company
          : MIN_LABEL_PX.issue;
      return {
        ...node,
        data: { ...node.data, labelBase: base },
        style: {
          ...node.style,
          labelFontSize: dimmed ? base : Math.max(base, min / zoom),
        },
      };
    }),
  };
}
