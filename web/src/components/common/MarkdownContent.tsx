import type { ReactNode } from 'react';

function inline(text: string): ReactNode[] {
  const nodes: ReactNode[] = [];
  const pattern =
    /(\*\*[^*]+\*\*|__[^_]+__|`[^`]+`|\*[^*]+\*|_[^_]+_|\[[^\]]+\]\([^)]+\))/g;
  let offset = 0;
  for (const match of text.matchAll(pattern)) {
    const index = match.index ?? 0;
    if (index > offset) nodes.push(text.slice(offset, index));
    const token = match[0];
    if (token.startsWith('**') || token.startsWith('__'))
      nodes.push(<strong key={index}>{token.slice(2, -2)}</strong>);
    else if (token.startsWith('`'))
      nodes.push(
        <code key={index} className="rounded bg-gray-100 px-1">
          {token.slice(1, -1)}
        </code>,
      );
    else if (token.startsWith('*') || token.startsWith('_'))
      nodes.push(<em key={index}>{token.slice(1, -1)}</em>);
    else {
      const link = /^\[([^\]]+)\]\(([^)]+)\)$/.exec(token);
      const href = link?.[2];
      if (link && href && /^(https?:|mailto:)/i.test(href))
        nodes.push(
          <a
            key={index}
            href={href}
            target="_blank"
            rel="noreferrer"
            className="underline"
          >
            {link[1]}
          </a>,
        );
      else nodes.push(token);
    }
    offset = index + token.length;
  }
  if (offset < text.length) nodes.push(text.slice(offset));
  return nodes;
}

function tableCells(line: string): string[] {
  return line
    .trim()
    .replace(/^\|/, '')
    .replace(/\|$/, '')
    .split('|')
    .map((cell) => cell.trim());
}

/** Safe, deliberately small Markdown renderer for D-AUT-02 terms from the API. */
export default function MarkdownContent({
  source,
  headingOffset = 0,
}: {
  source: string;
  /** D-AUT-02 F3: embed a document below the page heading; visual styles stay unchanged. */
  headingOffset?: 0 | 1 | 2 | 3 | 4 | 5;
}) {
  const lines = source.replace(/\r\n?/g, '\n').split('\n');
  const blocks: ReactNode[] = [];
  let index = 0;
  while (index < lines.length) {
    const line = lines[index];
    if (!line.trim()) {
      index += 1;
      continue;
    }
    if (
      line.includes('|') &&
      index + 1 < lines.length &&
      /^\s*\|?\s*:?-{3,}:?\s*(\|\s*:?-{3,}:?\s*)+\|?\s*$/.test(lines[index + 1])
    ) {
      const headers = tableCells(line);
      const alignments = tableCells(lines[index + 1]).map((cell) =>
        cell.startsWith(':') && cell.endsWith(':')
          ? 'center'
          : cell.endsWith(':')
            ? 'right'
            : 'left',
      );
      index += 2;
      const rows: string[][] = [];
      while (
        index < lines.length &&
        lines[index].includes('|') &&
        lines[index].trim()
      ) {
        rows.push(tableCells(lines[index]));
        index += 1;
      }
      blocks.push(
        <div key={`table-${index}`} className="max-w-full overflow-x-auto">
          <table className="w-full border-collapse text-left">
            <thead>
              <tr>
                {headers.map((cell, column) => (
                  <th
                    key={column}
                    scope="col"
                    className="border border-gray-300 bg-gray-100 px-2 py-1 font-semibold"
                    style={{ textAlign: alignments[column] }}
                  >
                    {inline(cell)}
                  </th>
                ))}
              </tr>
            </thead>
            <tbody>
              {rows.map((row, rowIndex) => (
                <tr key={rowIndex}>
                  {headers.map((_, column) => (
                    <td
                      key={column}
                      className="border border-gray-300 px-2 py-1 align-top"
                      style={{ textAlign: alignments[column] }}
                    >
                      {inline(row[column] ?? '')}
                    </td>
                  ))}
                </tr>
              ))}
            </tbody>
          </table>
        </div>,
      );
      continue;
    }
    const heading = /^(#{1,6})\s+(.+)$/.exec(line);
    if (heading) {
      const level = heading[1].length;
      const Tag = `h${Math.min(6, level + headingOffset)}` as
        'h1' | 'h2' | 'h3' | 'h4' | 'h5' | 'h6';
      blocks.push(
        <Tag key={index} className="font-semibold text-zoop-ink">
          {inline(heading[2])}
        </Tag>,
      );
      index += 1;
      continue;
    }
    const list = /^\s*([-*+]\s+|\d+[.)]\s+)/.exec(line);
    if (list) {
      const ordered = /^\s*\d/.test(line);
      const items: ReactNode[] = [];
      while (
        index < lines.length &&
        /^\s*([-*+]\s+|\d+[.)]\s+)/.test(lines[index])
      ) {
        const item = /^\s*(?:[-*+]\s+|\d+[.)]\s+)(.*)$/.exec(lines[index]);
        items.push(<li key={index}>{inline(item?.[1] ?? '')}</li>);
        index += 1;
      }
      blocks.push(
        ordered ? (
          <ol key={index} className="list-decimal pl-5">
            {items}
          </ol>
        ) : (
          <ul key={index} className="list-disc pl-5">
            {items}
          </ul>
        ),
      );
      continue;
    }
    const paragraph = [line.trim()];
    index += 1;
    while (
      index < lines.length &&
      lines[index].trim() &&
      !/^(#{1,6})\s+/.test(lines[index]) &&
      !/^\s*([-*+]\s+|\d+[.)]\s+)/.test(lines[index])
    ) {
      paragraph.push(lines[index].trim());
      index += 1;
    }
    blocks.push(<p key={index}>{inline(paragraph.join(' '))}</p>);
  }
  return <div className="space-y-2">{blocks}</div>;
}
