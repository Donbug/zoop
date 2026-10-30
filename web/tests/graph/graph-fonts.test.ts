import { afterEach, expect, test, vi } from 'vitest';
import {
  GRAPH_FONTS,
  graphText,
  loadGraphFonts,
} from '@/components/graph/graph-fonts';

afterEach(() => {
  vi.useRealTimers();
  Reflect.deleteProperty(document, 'fonts');
});

function stubFonts(load: (font: string, text: string) => Promise<unknown>) {
  Object.defineProperty(document, 'fonts', {
    configurable: true,
    value: { ready: Promise.resolve(), load: vi.fn(load) },
  });
  return document.fonts.load as unknown as ReturnType<typeof vi.fn>;
}

test('graphText collects every character the canvas draws', () => {
  const text = graphText({
    nodes: [
      {
        id: 'a',
        style: {
          labelText: '삼성전자',
          iconText: '삼',
          badges: [{ text: 'ϟ2' }, { text: '보유' }],
        },
      },
    ],
    edges: [
      { id: 'e', source: 'a', target: 'a', style: { labelText: '공유' } },
    ],
  });
  for (const char of '삼성전자ϟ2보유공0123456789') expect(text).toContain(char);
  expect(new Set(text).size).toBe(text.length);
});

test('loadGraphFonts requests each canvas font for the drawn text', async () => {
  const load = stubFonts(async () => []);
  await loadGraphFonts('삼성');
  expect(load.mock.calls).toEqual(
    GRAPH_FONTS.map((family) => [`16px "${family}"`, '삼성']),
  );
});

test('loadGraphFonts never holds the map back on a slow or failing font', async () => {
  vi.useFakeTimers();
  stubFonts(() => new Promise(() => {}));
  const slow = loadGraphFonts('삼성');
  await vi.advanceTimersByTimeAsync(3000);
  await expect(slow).resolves.toBeUndefined();
  vi.useRealTimers();
  stubFonts(() => Promise.reject(new Error('network')));
  await expect(loadGraphFonts('삼성')).resolves.toBeUndefined();
});

test('graphText includes full labels drawn after the shortened labelText', () => {
  const text = graphText(
    { nodes: [{ id: 'i', style: { labelText: '반도체 수출…' } }] },
    ['반도체 수출 규제 강화 발표'],
  );
  for (const char of '규제강화발표') expect(text).toContain(char);
});
