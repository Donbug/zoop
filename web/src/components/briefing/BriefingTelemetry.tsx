import { useEffect, useRef, useState, type ReactNode } from 'react';
import { createIdempotencyKey } from '@/apis/portfolio/portfolio';
import { useAuthStore } from '@/stores/useAuthStore';
import { track } from '@/util/track';
import { Link } from 'react-router-dom';
import {
  BriefingTelemetryContext,
  useBriefingIssueTracking,
} from './briefingTelemetryContext';

// D-BRF-01·02 / FS065: port of briefing-page BriefingView. Only a displayed publication counts.
export default function BriefingTelemetry({
  roundId,
  children,
}: {
  roundId: string | null;
  children: ReactNode;
}) {
  const [viewId] = useState(createIdempotencyKey);
  const revision = useAuthStore((s) => s.sessionRevision);
  const last = useRef<string | null>(null);
  useEffect(() => {
    const key = `${revision}:${roundId}`;
    if (
      !roundId ||
      !useAuthStore.getState().session?.csrfToken ||
      last.current === key
    )
      return;
    last.current = key;
    track({ type: 'briefing_view', targetId: roundId, viewId });
  }, [roundId, revision, viewId]);
  return (
    <BriefingTelemetryContext value={{ roundId, viewId }}>
      {children}
    </BriefingTelemetryContext>
  );
}

export function BriefingIssueMapLink({
  roundId,
  eventId,
  compact,
  to,
  className,
  children,
}: {
  roundId: string;
  eventId: string;
  compact: boolean;
  to: string;
  className: string;
  children: ReactNode;
}) {
  const record = useBriefingIssueTracking(roundId, eventId);
  return (
    <Link
      to={to}
      className={className}
      onClick={() => {
        if (!compact) record();
      }}
    >
      {children}
    </Link>
  );
}
