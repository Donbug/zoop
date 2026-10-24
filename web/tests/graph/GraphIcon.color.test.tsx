import { render } from '@testing-library/react';
import { expect, it } from 'vitest';
import GraphIcon from '@/components/graph/GraphIcon';

it.each(['sidebar', 'globe', 'personal'])(
  'D-GRP-01/01b %s follows the text color in both themes and selection states',
  (name) => {
    const view = render(
      <button>
        <GraphIcon name={name} inheritColor />내 종목
      </button>,
    );
    for (const theme of ['light', 'dark']) {
      for (const selected of [false, true]) {
        view.rerender(
          <button
            data-theme={theme}
            aria-pressed={selected}
            className={selected ? 'text-zoop-paper' : 'text-zoop-ink'}
          >
            <GraphIcon name={name} inheritColor />내 종목
          </button>,
        );
        const icon = view.container.querySelector('svg')!;
        expect(icon.getAttribute('stroke')).toBe('currentColor');
        expect(icon.getAttribute('aria-hidden')).toBe('true');
        expect(icon.getAttribute('style')).toBeNull();
        expect(icon.querySelectorAll('path').length).toBeGreaterThan(0);
        expect(icon.querySelector('[stroke]')).toBeNull();
      }
    }
  },
);

it('D-GRP-01 leaves other existing asset icons unchanged', () => {
  const { container } = render(<GraphIcon name="info" />);
  expect(container.querySelector('img')?.getAttribute('src')).toBe(
    '/graph-assets/info.svg',
  );
});
