import { render, screen } from '@testing-library/react';
import { describe, expect, it } from 'vitest';
import ChatMarkdown from '@/components/ai/ChatMarkdown';
import { parseBlocks } from '@/components/ai/chat-markdown';

// D-AI-02b · AI 답변 본문의 가벼운 마크다운

describe('D-AI-02b ChatMarkdown', () => {
  it('splits headings, lists and paragraphs', () => {
    expect(
      parseBlocks('## 요약\n첫 줄\n둘째 줄\n\n- 가\n- 나\n\n1. 하나\n2. 둘'),
    ).toEqual([
      { kind: 'heading', level: 2, text: '요약' },
      { kind: 'p', lines: ['첫 줄', '둘째 줄'] },
      { kind: 'ul', items: ['가', '나'] },
      { kind: 'ol', start: 1, items: ['하나', '둘'] },
    ]);
  });

  it('renders bold, lists and headings as elements, never raw HTML', () => {
    const { container } = render(
      <ChatMarkdown text={'### 사업\n- **반도체**: 메모리\n- <b>TV</b>'} />,
    );
    expect(screen.getByRole('heading', { name: '사업' })).toBeTruthy();
    expect(screen.getByText('반도체').tagName).toBe('STRONG');
    expect(screen.getAllByRole('listitem')).toHaveLength(2);
    // HTML in the answer stays text.
    expect(container.querySelector('b')).toBeNull();
    expect(screen.getByText('<b>TV</b>')).toBeTruthy();
  });

  it('keeps plain text with line breaks as one paragraph', () => {
    const { container } = render(<ChatMarkdown text={'한 줄\n다음 줄'} />);
    expect(container.querySelectorAll('p')).toHaveLength(1);
    expect(container.querySelectorAll('br')).toHaveLength(1);
  });
});
