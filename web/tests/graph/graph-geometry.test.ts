import { describe, expect, it } from 'vitest';
import {
  fitFootprint,
  overviewFootprint,
  fitZoom,
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
  it('D-GRP-01 neighborhood fit finds room between opposite-side labels even when minimum zoom does not fit', () => {
    const result = fitZoom(
      [
        {
          x: 0,
          y: 150,
          radius: 1,
          labelWidth: 50,
          labelHeight: 70,
          labelAbove: true,
        },
        { x: 0, y: 0, radius: 1, labelWidth: 50, labelHeight: 70 },
      ],
      { width: 320, height: 80 },
      2.5,
    );
    expect(result.zoom).toBeGreaterThan(0.4);
    expect(result.zoom).toBeLessThan(0.54);
  });
  it('D-GRP-01 selection fit keeps the circles centered and still fits the titles', () => {
    // 2026-11-05: only the whole-map fit centers on titles too; a selection fit
    // keeps its circles in the middle, as before, with title room on both sides.
    const footprints = [
      { x: 0, y: 0, radius: 20, labelWidth: 80, labelHeight: 60 },
      { x: 200, y: 0, radius: 20, labelWidth: 80, labelHeight: 60 },
    ];
    const safe = { width: 400, height: 300 };
    const circles = fitZoom(footprints, safe, 2.5, 'circles');
    expect(circles.center).toEqual([100, 0]);
    const labels = fitZoom(footprints, safe, 2.5);
    expect(labels.center[1]).toBeGreaterThan(0);
    // From the circle center, the radius plus the title below fits in half the height.
    expect(
      20 * circles.zoom + Math.max(1, circles.zoom) * 60,
    ).toBeLessThanOrEqual(safe.height / 2 + 0.001);
  });
  it('D-GRP-01 mobile fit reserves label space at its own node rather than both graph edges', () => {
    const footprints = [
      { x: 0, y: 0, radius: 24, labelWidth: 100, labelHeight: 38 },
      { x: 1000, y: 100, radius: 8, labelWidth: 0, labelHeight: 0 },
    ];
    const result = fitZoom(footprints, { width: 320, height: 430 }, 2.5);
    expect(result.zoom).toBeGreaterThan(0.25);
    const left = -Math.max(24 * result.zoom, 50);
    const right = 1008 * result.zoom;
    expect(right - left).toBeLessThanOrEqual(320.001);
    expect(result.zoom).toBeLessThanOrEqual(2.5);
  });
  it('D-GRP-01 mobile overview fit does not reserve space for hidden issue titles', () => {
    const issue: NodeData = {
      id: 'synthetic-issue',
      data: { kind: 'issue' },
      style: {
        x: 0,
        y: 0,
        size: 8,
        labelText: '합성 검증 긴 사건 제목 '.repeat(30),
      },
    };
    const company: NodeData = {
      id: 'synthetic-company',
      data: { kind: 'company' },
      style: { x: 1000, y: 200, size: 40, labelText: '합성 기업' },
    };
    const overview = [issue, company].map(overviewFootprint);
    expect(overview[0].labelWidth).toBe(0);
    expect(overview[0].labelHeight).toBe(0);
    expect(overview[1].labelWidth).toBeGreaterThan(0);
    const safe = { width: 320, height: 430 };
    const fitted = fitZoom(overview, safe, 2.5);
    const shortIssue = {
      ...issue,
      style: { ...issue.style, labelText: '합성 사건' },
    };
    expect(fitted).toEqual(
      fitZoom([shortIssue, company].map(overviewFootprint), safe, 2.5),
    );
    expect(fitted.zoom).toBeGreaterThan(
      fitZoom(
        [issue, company].map((node) => fitFootprint(node)),
        safe,
        2.5,
      ).zoom,
    );
    expect(fitFootprint(issue).labelHeight).toBeGreaterThan(0);
  });
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
    expect(textWidth(String(node.style?.labelText), 15)).toBeLessThanOrEqual(
      220,
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

describe('D-GRP-01 fit bounds', () => {
  const longTitle = '가'.repeat(40);
  const node = (x: number, labelFontSize: number) =>
    ({
      id: String(x),
      style: {
        x,
        y: 0,
        size: 30,
        labelText: longTitle,
        labelFontSize,
        labelWordWrapWidth: (170 * labelFontSize) / 13,
      },
    }) as NodeData;
  const safe = { width: 300, height: 400 };

  it('does not depend on the zoom-scaled label size, so repeating a fit gives the same zoom', () => {
    const atNormal = fitZoom(
      [node(0, 13), node(120, 13)].map(fitFootprint),
      safe,
      1.8,
    );
    const afterZoomOut = fitZoom(
      [node(0, 26), node(120, 26)].map(fitFootprint),
      safe,
      1.8,
    );
    expect(afterZoomOut.zoom).toBe(atNormal.zoom);
    expect(afterZoomOut.center).toEqual(atNormal.center);
    expect(atNormal.center[0]).toBe(60);
    // The full visible footprint includes the text below the circles.
    expect(atNormal.center[1]).toBeGreaterThan(0);
  });

  it('wraps a long title at the display width instead of measuring it on one line', () => {
    const footprint = fitFootprint(node(0, 13));
    expect(footprint.labelWidth).toBeLessThanOrEqual(170 + 24);
    expect(footprint.labelHeight).toBeGreaterThan(13 * 1.5 * 2);
    // 한 줄 폭(520px)으로 재면 300px 안에서 아주 작게 줄던 경우: 이제 두 노드가 들어가는 배율을 고른다.
    expect(
      fitZoom([node(0, 13), node(120, 13)].map(fitFootprint), safe, 1.8).zoom,
    ).toBeGreaterThan(0.5);
  });
});
