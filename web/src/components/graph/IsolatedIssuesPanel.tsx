import { useEffect, useRef, useState } from 'react';
import type { GraphNode } from '@/types/map/graph';
import { panelStyles as ui } from '@/components/common/detail-panel-styles';
import { eventTimeText } from '@/util/event-time';
import { getEvent } from '@/apis/graph/events';
import type { EventContext, EventDetail } from '@/types/map/event';
// D-GRP-01/02 M15: keep unknown event precision last; fetch basis only on request.
export default function IsolatedIssuesPanel({
  issues,
  onSelect,
  onClose,
  onEvidence,
  context = {},
}: {
  issues: GraphNode[];
  onSelect: (id: string) => void;
  onClose: () => void;
  onEvidence?: (event: EventDetail) => void;
  context?: EventContext;
}) {
  const heading = useRef<HTMLHeadingElement>(null);
  const [query, setQuery] = useState('');
  const [pending, setPending] = useState<string | null>(null);
  const [error, setError] = useState('');
  const active = useRef(false);
  useEffect(() => {
    active.current = true;
    heading.current?.focus();
    return () => {
      active.current = false;
    };
  }, []);
  async function evidence(id: string) {
    if (pending) return;
    setPending(id);
    setError('');
    try {
      const event = await getEvent(id, context);
      if (active.current) onEvidence?.(event);
    } catch {
      if (active.current)
        setError('근거를 불러오지 못했어요. 다시 시도해 주세요.');
    } finally {
      if (active.current) setPending(null);
    }
  }
  const filtered = issues
    .filter((issue) =>
      issue.label.toLocaleLowerCase().includes(query.toLocaleLowerCase()),
    )
    .sort((a, b) => {
      const knownA = eventTimeText(a.eventTime, a.timePrecision)
        ? a.eventTime
        : null;
      const knownB = eventTimeText(b.eventTime, b.timePrecision)
        ? b.eventTime
        : null;
      return knownA && knownB
        ? knownB.localeCompare(knownA)
        : knownA
          ? -1
          : knownB
            ? 1
            : 0;
    });
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
                  {eventTimeText(issue.eventTime, issue.timePrecision) ??
                    '발생 시각 미상'}
                </p>
                {onEvidence && (
                  <button
                    type="button"
                    className={`${ui.button} mt-1`}
                    disabled={pending !== null || issue.evidenceCount === 0}
                    onClick={() => void evidence(issue.id)}
                    aria-label={`${issue.label} 근거 보기`}
                  >
                    {pending === issue.id
                      ? '근거 확인 중'
                      : issue.evidenceCount !== null
                        ? `근거 ${issue.evidenceCount}건 보기`
                        : '근거 보기'}
                  </button>
                )}
              </li>
            ))}
          </ul>
          {!filtered.length && <p role="status">해당하는 사건이 없습니다.</p>}
          {error && <p role="alert">{error}</p>}
        </section>
      </div>
    </aside>
  );
}
