import { expect, it } from 'vitest';
import { companyLogo } from '@/util/company-logo';
import { createMockGraph } from '@/mocks/graph/response';
import { toG6Data } from '@/components/graph/graph-model';

it('D-GRP-01 resolves all fixture company logos to existing local files', () => {
  const assets = Object.keys(
    import.meta.glob('/public/graph-assets/*.{svg,png}'),
  );
  for (const id of [
    'KRX:005930',
    'KRX:000660',
    'NASDAQ:NVDA',
    'NYSE:TSM',
    'NASDAQ:ASML',
    'KRX:042700',
    'NASDAQ:AMD',
  ]) {
    const path = companyLogo(id, null);
    expect(path).toBeTruthy();
    expect(assets).toContain(`/public${path}`);
  }
  expect(companyLogo('unknown', null)).toBeNull();
  expect(companyLogo('NASDAQ:NVDA', '/custom.svg')).toBe('/custom.svg');
});

it('D-GRP-01 renders logos even when the API supplies null', () => {
  const graph = createMockGraph({ mode: 'all', personalFilter: 'all' });
  for (const node of graph.nodes) node.logoUrl = null;
  const result = toG6Data(graph, 1245, 705);
  const samsung = result.nodes?.find((node) => node.id === 'KRX:005930');
  expect(samsung?.style?.iconSrc).toBe('/graph-assets/samsung.svg');
  expect(samsung?.style?.iconText).toBeUndefined();
  expect(samsung?.style?.iconWidth).toBe(Number(samsung?.style?.size));
  expect(samsung?.style?.iconHeight).toBe(samsung?.style?.iconWidth);
  expect(samsung?.style?.iconRadius).toBe(
    Number(samsung?.style?.iconWidth) / 2,
  );
  expect(samsung?.style?.labelFontSize).toBe(17.2);
});
