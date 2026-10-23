import { render, screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { MemoryRouter } from 'react-router-dom';
import { expect, it } from 'vitest';
import BriefingRoundIssuePanel from '@/components/graph/BriefingRoundIssuePanel';
import { createFakeServer, json } from '../support/fakeServer';

const basis = {
  roundId: 'saved-round',
  date: '2026-10-08',
  edition: 'morning',
  status: 'available',
  graphVersion: 'reconstructed-version',
  graphOrigin: 'reconstructed',
};
const item = {
  rank: 1,
  eventId: 'saved-event',
  title: '저장된 실제 이슈',
  reason: '저장된 선정 이유',
  summary: { text: '발행본에 저장한 문안' },
  evidenceCount: 1,
};
function setup() {
  const server = createFakeServer();
  server.on('GET', '/api/v1/briefings/:id/graph', () => json(basis));
  server.on('GET', '/api/v1/briefings', () =>
    json({
      id: basis.roundId,
      status: 'published',
      graphVersion: null,
      items: [item],
    }),
  );
  render(
    <MemoryRouter>
      <BriefingRoundIssuePanel
        roundId={basis.roundId}
        eventId={item.eventId}
        graphVersion={basis.graphVersion}
        onClose={() => undefined}
      />
    </MemoryRouter>,
  );
  return server;
}
it('shows the preserved round text and cites original evidence without replacing its null graphVersion', async () => {
  const server = setup();
  server.on('GET', '/api/v1/briefings/:round/items/:event', () =>
    json({
      roundId: basis.roundId,
      eventId: item.eventId,
      title: item.title,
      summary: item.summary,
      selectionReason: item.reason,
      claims: [],
      companies: [],
      limitations: [],
      metadata: {
        graphVersion: null,
        asOf: '2026-10-08T00:20:00Z',
        partial: false,
        failures: [],
      },
      evidence: [
        {
          id: 'saved-evidence',
          quote: '원문 그대로 인용',
          documentId: 'saved-doc',
          documentVersion: 'saved-version',
          title: '저장한 원문',
          publisher: '원 발행자',
          url: 'https://example.invalid/source',
          publishedAt: '2026-10-07T20:00:00Z',
          quoteVerified: true,
          sourceKind: 'news',
          bodyContext: null,
        },
      ],
    }),
  );
  expect(await screen.findByText('발행본에 저장한 문안')).toBeTruthy();
  expect(screen.getByText(/지도는 재구성본/)).toBeTruthy();
  await userEvent.click(
    screen.getByRole('button', { name: '핵심 이슈 1 근거 보기' }),
  );
  expect(await screen.findByText('원문 그대로 인용')).toBeTruthy();
  expect(
    screen.getByRole('link', { name: '원래 브리핑 보기' }).getAttribute('href'),
  ).toContain('2026-10-08');
});
it('does not substitute another publication when the date/edition points to a different round', async () => {
  const server = setup();
  server.on('GET', '/api/v1/briefings', () =>
    json({ id: 'another-round', status: 'published', items: [item] }),
  );
  expect(await screen.findByRole('alert')).toBeTruthy();
  expect(screen.queryByText('발행본에 저장한 문안')).toBeNull();
});
