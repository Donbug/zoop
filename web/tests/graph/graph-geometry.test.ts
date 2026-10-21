import { describe, expect, it } from 'vitest';
import {
  freeViewport,
  intersects,
  nodeRect,
  separateNodes,
  shortTitle,
  textWidth,
} from '@/components/graph/graph-geometry';
import { toG6Data } from '@/components/graph/graph-model';
import { createMockGraph } from '@/mocks/graph/response';
import type { NodeData } from '@antv/g6';

describe('D-GRP-01/01b · graph readability', () => {
  it('accepts G6-normalized tuple sizes after a real layout', () => {
    const nodes: NodeData[] = [
      { id: 'a', style: { x: 0, y: 0, size: [88, 88], labelText: '기업' } },
      { id: 'b', style: { x: 0, y: 0, size: [52, 52] } },
    ];
    const spaced = separateNodes(nodes);
    expect(
      spaced.every(
        (node) =>
          Number.isFinite(node.style?.x) && Number.isFinite(node.style?.y),
      ),
    ).toBe(true);
    expect(intersects(nodeRect(spaced[0]), nodeRect(spaced[1]), 15)).toBe(
      false,
    );
  });
  it('labels API issues outside the example title list without altering IDs or source titles', () => {
    const graph = createMockGraph({ mode: 'all', personalFilter: 'all' });
    const issue = graph.nodes.find((n) => n.kind === 'issue')!;
    issue.label =
      '새로운 실제 API 사건 제목: 반도체 제조 공정과 공급망 관련 기업들의 공동 투자 발표';
    const title = issue.label;
    const rendered = toG6Data(graph, 1200, 800, issue.id);
    const node = rendered.nodes!.find((n) => n.id === issue.id)!;
    expect(node.style?.labelText).toBeTruthy();
    expect(String(node.style?.labelText)).toContain('…');
    expect(issue.label).toBe(title);
    expect(textWidth(String(node.style?.labelText), 13)).toBeLessThanOrEqual(
      180,
    );
  });
  it('keeps short titles intact and does not split Unicode code points', () => {
    expect(shortTitle('HBM 공급 계약')).toBe('HBM 공급 계약');
    expect(shortTitle('😀'.repeat(40))).not.toContain('\ud83d…');
  });
  it('separates coincident logo, company-name and event-label footprints deterministically', () => {
    const nodes: NodeData[] = Array.from({ length: 90 }, (_, i) => ({
      id: `node-${i}`,
      style: {
        x: 50,
        y: 50,
        size: i % 2 ? 88 : 7,
        labelText: i % 2 ? 'SK하이닉스' : '반도체 공급 계약 발표',
        labelFontSize: 17,
        labelPlacement: i % 2 ? 'bottom' : 'top',
        labelOffsetY: 28,
      },
    }));
    const placed = separateNodes(nodes);
    expect(separateNodes(nodes)).toEqual(placed);
    expect(nodes.every((node) => node.style?.x === 50)).toBe(true);
    const rects = placed.map(nodeRect);
    for (let i = 0; i < rects.length; i++)
      for (let j = i + 1; j < rects.length; j++)
        expect(intersects(rects[i], rects[j], 15)).toBe(false);
  });
  it('fits around legend, minimap and bottom controls', () => {
    const overlays = [
      { x: 20, y: 16, width: 220, height: 300 },
      { x: 980, y: 640, width: 200, height: 140 },
      { x: 20, y: 740, width: 330, height: 40 },
    ];
    const safe = freeViewport(1200, 800, overlays);
    expect(safe.width).toBeGreaterThan(600);
    expect(safe.height).toBeGreaterThan(300);
    overlays.forEach((overlay) =>
      expect(intersects(safe, overlay)).toBe(false),
    );
  });
  it('reserves a portaled mobile detail sheet and clips external panel rectangles', () => {
    const sheet = { x: 0, y: 400, width: 390, height: 400 };
    const safe = freeViewport(390, 800, [
      sheet,
      { x: 400, y: 0, width: 320, height: 800 },
    ]);
    expect(safe.y + safe.height).toBeLessThanOrEqual(388);
    expect(safe.width).toBe(350);
    expect(intersects(safe, sheet)).toBe(false);
  });
});
