import { expect, test } from 'vitest';
import { appearanceColors } from '@/components/graph/graph-appearance';
import css from '@/index.css?raw';

function tokens(selector: string) {
  const start = css.indexOf(selector);
  const block = css.slice(start, css.indexOf('}', start));
  return Object.fromEntries(
    [...block.matchAll(/--color-([\w-]+):\s*(#[\da-f]{6});/g)].map((match) => [
      match[1],
      match[2],
    ]),
  );
}
function luminance(hex: string) {
  return [1, 3, 5]
    .map((i) => parseInt(hex.slice(i, i + 2), 16) / 255)
    .map((v) => (v <= 0.04045 ? v / 12.92 : ((v + 0.055) / 1.055) ** 2.4))
    .reduce((sum, v, i) => sum + v * [0.2126, 0.7152, 0.0722][i], 0);
}

test('D-COM-01 theme: shared dark text matches the approved briefing palette and canvas', () => {
  const dark = tokens(":root[data-theme='dark']");
  expect([dark['zoop-ink'], dark['zoop-muted'], dark['zoop-faint']]).toEqual([
    '#fafafa',
    '#d4d4d4',
    '#a3a3a3',
  ]);
  expect([
    dark['panel-ink'],
    dark['panel-secondary'],
    dark['panel-muted'],
  ]).toEqual(['#fafafa', '#d4d4d4', '#a3a3a3']);
  const canvas = appearanceColors({ variant: 'improved', theme: 'dark' });
  expect(canvas.ink).toBe(dark['zoop-ink']);
  expect(canvas.muted).toBe(dark['zoop-muted']);
});

test.each(['@theme', ":root[data-theme='dark']"])(
  'D-COM-01 theme: %s text contrasts with each page/panel/card/control state',
  (selector) => {
    const palette = tokens(selector);
    for (const surface of ['page', 'surface', 'card', 'control', 'selected']) {
      const background = palette[`zoop-${surface}`];
      expect(background, surface).toMatch(/^#[\da-f]{6}$/);
      for (const role of ['ink', 'muted', 'faint']) {
        const pair = [
          luminance(palette[`zoop-${role}`]),
          luminance(background),
        ].sort((a, b) => b - a);
        expect(
          (pair[0] + 0.05) / (pair[1] + 0.05),
          `${role} on ${surface}`,
        ).toBeGreaterThanOrEqual(4.5);
      }
    }
    if (selector === '@theme')
      expect([
        palette['zoop-ink'],
        palette['zoop-muted'],
        palette['zoop-faint'],
      ]).toEqual(['#212121', '#212121', '#212121']);
  },
);
