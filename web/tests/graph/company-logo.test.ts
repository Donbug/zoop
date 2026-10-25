import { expect, it } from 'vitest';
import { companyLogo } from '@/util/company-logo';
import { createMockGraph } from '@/mocks/graph/response';
import { toG6Data } from '@/components/graph/graph-model';
import { styleGraph } from '@/components/graph/graph-appearance';

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
    'KRX:030200',
    'KRX:035420',
    'KRX:035720',
    'NASDAQ:GOOGL',
  ]) {
    const path = companyLogo(id, null);
    expect(path).toBeTruthy();
    expect(assets).toContain(`/public${path}`);
  }
  expect(companyLogo('unknown', null)).toBeNull();
  expect(companyLogo('NASDAQ:NVDA', '/custom.svg')).toBe('/custom.svg');
  expect(companyLogo('KRX:030200', '/old-kt.png')).toBe('/graph-assets/kt.svg');
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
  expect(samsung?.style?.labelFontSize).toBe(19);
  expect(
    result.nodes?.find((node) => node.id === 'KRX:006400')?.style?.iconSrc,
  ).toBe('/graph-assets/samsung.svg');
  expect(
    result.nodes?.find((node) => node.id === 'NASDAQ:MU')?.style?.fill,
  ).toBe('#000000');
  expect(
    result.nodes?.find((node) => node.id === 'NASDAQ:AMZN')?.style?.fill,
  ).toBe('#232f3e');
  for (const node of result.nodes ?? []) {
    if (node.data?.kind !== 'company' || !node.style?.iconSrc) continue;
    const size = Number(node.style.size);
    const icon = Number(node.style.iconWidth);
    // Unpadded symbols fit entirely inside the circle's inscribed square.
    if (Number(node.style.iconRadius) === 0)
      expect(Math.hypot(icon / 2, icon / 2)).toBeLessThan(size / 2);
    expect(node.style.iconHeight).toBe(icon);
  }
});

it.each([
  { theme: 'light' as const, paper: '#ffffff', ink: '#1a1a1a' },
  { theme: 'dark' as const, paper: '#3d3937', ink: '#ffffff' },
])(
  'D-GRP-01 keeps a readable $theme fallback without any logo or brand color',
  ({ theme, paper, ink }) => {
    const root = document.documentElement;
    const previousStyle = root.getAttribute('style');
    const previousTheme = root.getAttribute('data-theme');
    try {
      root.dataset.theme = theme;
      // JSDOM does not load the app stylesheet; use its actual light/dark tokens.
      root.style.setProperty('--color-zoop-paper', paper);
      root.style.setProperty('--color-zoop-ink', ink);
      const graph = createMockGraph({ mode: 'all', personalFilter: 'all' });
      const company = {
        ...graph.nodes.find((node) => node.kind === 'company')!,
        id: 'ORG:UNMAPPED_FIXTURE_COMPANY',
        label: '새로운 기업 (합성)',
        logoUrl: null,
        brandColor: null,
      };
      expect(companyLogo(company.id, company.logoUrl)).toBeNull();
      graph.nodes.push(company);
      const data = toG6Data(graph, 1245, 705);
      for (const variant of ['original', 'improved'] as const) {
        const node = styleGraph(data, { variant, theme }).nodes?.find(
          (node) => node.id === company.id,
        );
        expect(node?.style?.iconSrc).toBeUndefined();
        expect(node?.style?.iconText).toBe('새');
        expect(node?.style?.fill).toBe(
          variant === 'improved' && theme === 'dark' ? '#262626' : paper,
        );
        expect(node?.style?.iconFill).toBe(ink);
        expect(node?.style?.fill).not.toBe(node?.style?.iconFill);
      }
    } finally {
      if (previousStyle === null) root.removeAttribute('style');
      else root.setAttribute('style', previousStyle);
      if (previousTheme === null) root.removeAttribute('data-theme');
      else root.setAttribute('data-theme', previousTheme);
    }
  },
);
