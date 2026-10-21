import { useEffect, useRef, useState } from 'react';
import type { GraphNode } from '@/types/map/graph';
import { panelStyles as ui } from '@/components/common/detail-panel-styles';
export default function IsolatedIssuesPanel({
  issues,
  onSelect,
  onClose,
}: {
  issues: GraphNode[];
  onSelect: (id: string) => void;
  onClose: () => void;
}) {
  const heading = useRef<HTMLHeadingElement>(null);
  const [query, setQuery] = useState('');
  useEffect(() => {
    heading.current?.focus();
  }, []);
  const filtered = issues
    .filter((issue) =>
      issue.label.toLocaleLowerCase().includes(query.toLocaleLowerCase()),
    )
    .sort((a, b) => (b.eventTime ?? '').localeCompare(a.eventTime ?? ''));
  return (
    <aside
      className={ui.shell}
      aria-labelledby="isolated-title"
      onKeyDown={(event) => {
        if (event.key === 'Escape') {
          event.stopPropagation();
          onClose();
        }
      }}
    >
      <header className={ui.header}>
        <div className="flex items-center justify-between gap-2">
          <h2
            id="isolated-title"
            ref={heading}
            tabIndex={-1}
            className={ui.title}
          >
            연결 없는 사건 {issues.length}건
          </h2>
          <button
            className={ui.close}
            onClick={onClose}
            aria-label="연결 없는 사건 닫기"
          >
            ×
          </button>
        </div>
      </header>
      <div className={ui.scroll}>
        <section className={ui.section}>
          <p>
            현재 조회한 그래프에서 연결선이 확인되지 않은 사건입니다. 전체
            데이터에 관계가 없다는 뜻은 아닙니다.
          </p>
          <label className="mt-3 block">
            사건 검색
            <input
              className="mt-1 w-full rounded-panel border border-panel-line p-2"
              value={query}
              onChange={(event) => setQuery(event.target.value)}
            />
          </label>
          <ul className={ui.list}>
            {filtered.map((issue) => (
              <li key={issue.id}>
                <button
                  className="w-full text-left"
                  onClick={() => onSelect(issue.id)}
                >
                  {issue.label}
                </button>
                <p className={ui.muted}>
                  {issue.eventTime ?? '발생 시각 미상'}
                </p>
              </li>
            ))}
          </ul>
          {!filtered.length && <p role="status">해당하는 사건이 없습니다.</p>}
        </section>
      </div>
    </aside>
  );
}
