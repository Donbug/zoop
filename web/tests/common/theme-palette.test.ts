/// <reference types="node" />
import { readFileSync } from 'node:fs';
import { expect, test } from 'vitest';
import { appearanceColors } from '@/components/graph/graph-appearance';

// Vitest stubs CSS imports; inspect the source tokens rather than that empty module.
const css = readFileSync('src/index.css', 'utf8');

test('D-BRF-01/02 theme: briefing uses the shared page and navigation surfaces', () => {
  const layout = readFileSync('src/components/common/AppLayout.tsx', 'utf8');
  expect(layout).toMatch(/section === 'companies' \|\| section === 'briefing'/);
  expect(layout).toContain('bg-zoop-page!');
  expect(layout).toContain('[&_.relationship-header]:bg-zoop-surface!');
  expect(layout).toContain('[&_.service-bottom-nav]:bg-zoop-surface!');
  const local = readFileSync(
    'src/components/common/briefing-login-surface.css',
    'utf8',
  );
  expect(local).not.toContain('.briefing-login-surface');
});

test('D-BRF-01/02 feedback theme: controls and pressed text use shared surfaces', () => {
  const feedback = readFileSync(
    'src/components/common/FeedbackButtons.tsx',
    'utf8',
  );
  for (const token of [
    'rounded-md',
    'border-zoop-border',
    'bg-zoop-control',
    'bg-zoop-surface',
    'hover:bg-zoop-selected',
    'aria-pressed:text-zoop-on-ink',
  ])
    expect(feedback).toContain(token);
  expect(feedback).not.toMatch(
    /rounded-\[3px\]|border-\[0\.667px\]|bg-zoop-paper|border-zoop-line/,
  );
});

test('D-COM-01/02 theme: section surfaces apply once beneath each workspace column', () => {
  const workspace = readFileSync(
    'src/components/company/CompanyWorkspace.tsx',
    'utf8',
  );
  expect(workspace).not.toContain('[&_section]:bg-zoop-card');
  expect(workspace).toContain('[&>div>section]:bg-zoop-card');
  expect(workspace).toContain('[&>aside>section]:bg-zoop-card');
});

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
