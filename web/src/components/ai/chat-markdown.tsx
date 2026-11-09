import type { ReactNode } from 'react';

// D-AI-02b · ChatMarkdown이 쓰는 가벼운 마크다운 해석. HTML은 해석하지 않는다.

export type Block =
  | { kind: 'heading'; level: 1 | 2 | 3; text: string }
  | { kind: 'ul'; items: string[] }
  | { kind: 'ol'; start: number; items: string[] }
  | { kind: 'p'; lines: string[] };

const HEADING = /^(#{1,3})\s+(.*)$/;
const BULLET = /^\s*[-*•]\s+(.*)$/;
const ORDERED = /^\s*(\d{1,3})[.)]\s+(.*)$/;

export function parseBlocks(source: string): Block[] {
  const blocks: Block[] = [];
  let paragraph: string[] = [];
  const flush = () => {
    if (paragraph.length) blocks.push({ kind: 'p', lines: paragraph });
    paragraph = [];
  };
  for (const raw of source.replace(/\r\n?/g, '\n').split('\n')) {
    const line = raw.trimEnd();
    if (!line.trim()) {
      flush();
      continue;
    }
    const heading = HEADING.exec(line);
    const bullet = BULLET.exec(line);
    const ordered = ORDERED.exec(line);
    const last = blocks.at(-1);
    if (heading) {
      flush();
      blocks.push({
        kind: 'heading',
        level: heading[1].length as 1 | 2 | 3,
        text: heading[2],
      });
    } else if (bullet) {
      flush();
      const prev = blocks.at(-1);
      if (prev?.kind === 'ul') prev.items.push(bullet[1]);
      else blocks.push({ kind: 'ul', items: [bullet[1]] });
    } else if (ordered) {
      flush();
      const prev = blocks.at(-1);
      if (prev?.kind === 'ol') prev.items.push(ordered[2]);
      else
        blocks.push({
          kind: 'ol',
          start: Number(ordered[1]),
          items: [ordered[2]],
        });
    } else if (
      !paragraph.length &&
      (last?.kind === 'ul' || last?.kind === 'ol') &&
      /^\s{2,}/.test(raw)
    ) {
      // 들여 쓴 줄은 바로 위 목록 항목에 이어 붙인다.
      last.items[last.items.length - 1] += ` ${line.trim()}`;
    } else {
      paragraph.push(line);
    }
  }
  flush();
  return blocks;
}

const INLINE = /(\*\*[^*\n]+\*\*|`[^`\n]+`|\*[^*\s][^*\n]*\*)/g;

export function renderInline(text: string): ReactNode[] {
  return text.split(INLINE).map((part, i) => {
    if (part.startsWith('**') && part.endsWith('**') && part.length > 4)
      return (
        <strong key={i} className="font-semibold text-zoop-ink">
          {part.slice(2, -2)}
        </strong>
      );
    if (part.startsWith('`') && part.endsWith('`') && part.length > 2)
      return (
        <code
          key={i}
          className="rounded bg-zoop-control px-1 py-0.5 font-mono text-[0.9em]"
        >
          {part.slice(1, -1)}
        </code>
      );
    if (part.startsWith('*') && part.endsWith('*') && part.length > 2)
      return <em key={i}>{part.slice(1, -1)}</em>;
    return part;
  });
}
