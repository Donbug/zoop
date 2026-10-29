import { createContext, useContext } from 'react';
import { track } from '@/util/track';

export const BriefingTelemetryContext = createContext<{
  roundId: string | null;
  viewId: string;
} | null>(null);

export function useBriefingIssueTracking(roundId: string, eventId: string) {
  const context = useContext(BriefingTelemetryContext);
  return () => {
    if (context?.roundId !== roundId) return;
    track({
      type: 'briefing_issue_open',
      targetId: eventId,
      roundId,
      viewId: context.viewId,
    });
  };
}
