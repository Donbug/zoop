import { panelStyles as ui } from '@/components/common/detail-panel-styles';
import type { EventDetail } from '@/types/map/event';
import { formatEventTime } from './event-format';

// D-GRP-02 · gap 27. Port of node-panel.tsx's ordered follows list.
export default function EventLinkedDetails({ event }: { event: EventDetail }) {
  if (event.metadata.failures.some((failure) => failure.section === 'follows'))
    return null;
  const follows = [
    ...event.follows.previous.map((issue) => ({
      ...issue,
      direction: '앞선 사건',
    })),
    ...event.follows.next.map((issue) => ({
      ...issue,
      direction: '이어진 사건',
    })),
  ];
  if (!follows.length) return null;
  return (
    <section className={ui.section} aria-label="앞뒤로 이어진 사건">
      <h3>앞뒤로 이어진 사건</h3>
      <ul className={ui.list}>
        {follows.map((issue) => (
          <li key={`${issue.direction}-${issue.id}`}>
            <p className="text-zoop-ink">{issue.title}</p>
            <p className={ui.muted}>
              {issue.direction} ·{' '}
              {formatEventTime(issue.eventTime, issue.timePrecision)}
            </p>
          </li>
        ))}
      </ul>
    </section>
  );
}
