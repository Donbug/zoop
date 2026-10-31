import { render, screen } from '@testing-library/react';
import { expect, it } from 'vitest';
import MarkdownContent from '@/components/common/MarkdownContent';

const source = '# 문서 제목\n\n## 하위 제목\n\n###### 마지막 제목';

it('D-AUT-02 F3 preserves standalone Markdown heading levels and styling by default', () => {
  render(<MarkdownContent source={source} />);
  for (const [name, level] of [
    ['문서 제목', 1],
    ['하위 제목', 2],
    ['마지막 제목', 6],
  ] as const) {
    const heading = screen.getByRole('heading', { name, level });
    expect(heading.classList.contains('font-semibold')).toBe(true);
    expect(heading.classList.contains('text-zoop-ink')).toBe(true);
  }
});

it('D-AUT-02 F3 offsets embedded headings without exceeding h6 or changing styles', () => {
  render(<MarkdownContent source={source} headingOffset={1} />);
  expect(screen.queryByRole('heading', { level: 1 })).toBeNull();
  for (const [name, level] of [
    ['문서 제목', 2],
    ['하위 제목', 3],
    ['마지막 제목', 6],
  ] as const) {
    const heading = screen.getByRole('heading', { name, level });
    expect(heading.classList.contains('font-semibold')).toBe(true);
    expect(heading.classList.contains('text-zoop-ink')).toBe(true);
  }
});
