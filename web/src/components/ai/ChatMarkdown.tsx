import type { ReactNode } from 'react';
import { parseBlocks, renderInline } from '@/components/ai/chat-markdown';

// D-AI-02b · AI 답변 본문을 가벼운 마크다운으로 그린다.
// HTML을 그대로 넣지 않고(dangerouslySetInnerHTML 없음) 아래 문법만 React 요소로 바꾼다.
// 제목(#~###), 글머리표(-, *, •), 번호 목록(1.), 굵게(**), 기울임(*), 인라인 코드(`), 문단과 줄바꿈.
// 모르는 문법은 글자 그대로 보여 준다.

const HEADING_CLASS = {
  1: 'text-title-sm font-bold',
  2: 'text-body font-bold',
  3: 'text-body font-semibold',
} as const;

export default function ChatMarkdown({
  text,
  trailing,
}: {
  text: string;
  /** 마지막 블록 끝에 붙일 요소(인용 번호 등) */
  trailing?: ReactNode;
}) {
  const blocks = parseBlocks(text);
  return (
    <div className="flex flex-col gap-3 text-body leading-7 text-zoop-ink wrap-anywhere">
      {blocks.map((block, i) => {
        const tail = i === blocks.length - 1 ? trailing : null;
        if (block.kind === 'heading')
          return (
            <p
              key={i}
              role="heading"
              aria-level={block.level + 3}
              className={`m-0! mt-1! ${HEADING_CLASS[block.level]}`}
            >
              {renderInline(block.text)}
              {tail}
            </p>
          );
        if (block.kind === 'ul')
          return (
            <ul
              key={i}
              className="m-0! flex list-disc flex-col gap-1.5 pl-5 marker:text-zoop-muted"
            >
              {block.items.map((item, j) => (
                <li key={j} className="pl-0.5">
                  {renderInline(item)}
                  {j === block.items.length - 1 && tail}
                </li>
              ))}
            </ul>
          );
        if (block.kind === 'ol')
          return (
            <ol
              key={i}
              start={block.start}
              className="m-0! flex list-decimal flex-col gap-1.5 pl-5 marker:text-zoop-muted"
            >
              {block.items.map((item, j) => (
                <li key={j} className="pl-0.5">
                  {renderInline(item)}
                  {j === block.items.length - 1 && tail}
                </li>
              ))}
            </ol>
          );
        return (
          <p key={i} className="m-0!">
            {block.lines.map((line, j) => (
              <span key={j}>
                {j > 0 && <br />}
                {renderInline(line)}
              </span>
            ))}
            {tail}
          </p>
        );
      })}
    </div>
  );
}
