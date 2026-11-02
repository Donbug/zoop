import { act, render, screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { MemoryRouter } from 'react-router-dom';
import { beforeEach, expect, it } from 'vitest';
import SavedResultFeedback from '@/components/common/SavedResultFeedback';
import { useAuthStore } from '@/stores/useAuthStore';
import { createFakeServer, deferred, json } from '../support/fakeServer';

function signIn(id = 'synthetic-member') {
  useAuthStore.getState().setSession({
    authenticated: true,
    kind: 'member',
    user: { id, email: 'synthetic@example.test', displayName: '합성 회원' },
    setup: { completed: true, tutorialCompleted: true },
    csrfToken: 'synthetic-csrf',
    expiresAt: null,
  });
}
const props = {
  feature: 'chatbot_answer' as const,
  targetId: 'synthetic-message',
  targetVersion: 'synthetic-version',
  subject: '이 AI 답변',
};
beforeEach(() => {
  useAuthStore.getState().clearSession();
  signIn();
});
it('waits for the exact saved version before voting and restores the current vote', async () => {
  const server = createFakeServer(),
    read = deferred<Response>();
  let writes = 0;
  server.on('GET', '/api/v1/feedback', () => read.promise);
  server.on('PUT', '/api/v1/feedback', ({ body }) => {
    writes++;
    return json({ ...props, ...(body as object), reason: null });
  });
  render(
    <MemoryRouter>
      <SavedResultFeedback {...props} />
    </MemoryRouter>,
  );
  expect(screen.queryByRole('button', { name: /도움이 됐어요/ })).toBeNull();
  await act(async () =>
    read.resolve(
      json({
        items: [{ ...props, value: 'up', reason: null }],
        nextCursor: null,
      }),
    ),
  );
  const button = await screen.findByRole('button', { name: /도움이 됐어요/ });
  expect(button.getAttribute('aria-pressed')).toBe('true');
  await userEvent.click(button);
  await waitFor(() => expect(writes).toBe(1));
  expect(button.getAttribute('aria-pressed')).toBe('false');
});
it('a late response for a previous account never restores that account vote', async () => {
  const server = createFakeServer(),
    old = deferred<Response>();
  let reads = 0;
  server.on('GET', '/api/v1/feedback', () =>
    ++reads === 1 ? old.promise : json({ items: [], nextCursor: null }),
  );
  render(
    <MemoryRouter>
      <SavedResultFeedback {...props} />
    </MemoryRouter>,
  );
  await waitFor(() => expect(reads).toBe(1));
  act(() => signIn('another-synthetic-member'));
  await screen.findByRole('button', { name: /도움이 됐어요/ });
  await act(async () =>
    old.resolve(
      json({
        items: [{ ...props, value: 'up', reason: null }],
        nextCursor: null,
      }),
    ),
  );
  expect(
    screen
      .getByRole('button', { name: /도움이 됐어요/ })
      .getAttribute('aria-pressed'),
  ).toBe('false');
});
it('a mismatched version shows an error and cannot overwrite the current result vote', async () => {
  const server = createFakeServer();
  server.on('GET', '/api/v1/feedback', () =>
    json({
      items: [
        {
          ...props,
          feature: 'news_summary',
          targetVersion: 'different-version',
          value: 'down',
          reason: '합성',
        },
      ],
      nextCursor: null,
    }),
  );
  render(
    <MemoryRouter>
      <SavedResultFeedback {...props} feature="news_summary" />
    </MemoryRouter>,
  );
  await screen.findByRole('alert');
  expect(screen.queryByRole('button', { name: /도움이 됐어요/ })).toBeNull();
});
