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
    line: dark ? '#737373' : '#94948f',
    selected:
      appearance.variant === 'improved'
        ? dark
          ? '#a7c7ff'
          : '#315b9d'
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
        labelFontSize: Number(node.style?.labelFontSize ?? 13) * 1.15,
        labelFontWeight: 600,
        fill:
          node.data?.kind === 'company'
            ? (node.style?.fill ?? '#ffffff')
            : colors.ink,
        stroke: colors.ink,
        haloStroke: colors.ink,
        labelFill: node.data?.kind === 'company' ? colors.muted : colors.ink,
        labelBackgroundFill: colors.paper,
        labelBackgroundStroke: dark ? '#737373' : '#1a1a1a',
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
          stroke: follows
            ? dark
              ? '#efa397'
              : '#b04b42'
            : dark
              ? '#c4c9d1'
              : '#606a76',
          lineWidth: shared ? 1.2 : 1.5,
          strokeOpacity: dimmed ? 0.2 : shared ? 0.65 : 0.9,
        },
      };
    }),
  };
  // Enlarged labels participate in fitting and collision separation.
  result.nodes = separateNodes(result.nodes ?? []);
  return result;
}
