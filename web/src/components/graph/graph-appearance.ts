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
          // D-GRP-01: selected/related G6 states and impact paths supply
          // their own stronger stroke (3/3.5px, opacity 1). Background links (2/2.2px) stay
          // thinner but keep 3:1 contrast on the map (opacity 0.8: light 3.1, dark 5.1).
          // Follow arrows keep their stronger ink. Dimmed links stay faint so the
          // dimming cover (graph-dimming.ts) never leaves them brighter than before.
          lineWidth: shared ? 2 : 2.2,
          strokeOpacity: dimmed ? 0.2 : follows ? 0.95 : 0.8,
        },
      };
    }),
  };
  // Enlarged labels participate in fitting and collision separation.
  result.nodes = separateNodes(result.nodes ?? []);
  return result;
}
