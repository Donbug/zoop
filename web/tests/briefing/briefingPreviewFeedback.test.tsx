import { act, render, screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { describe, expect, it, vi } from 'vitest';
import BriefingPreviewFeedback from '@/components/briefing/BriefingPreviewFeedback';

const target = {
  roundId: 'preview-round',
  resultVersion: 'result-1',
  feature: 'briefing_round' as const,
  targetId: 'preview-round',
};
const up = () => screen.getByRole('button', { name: '회차: 도움이 됐어요' });
const down = () =>
  screen.getByRole('button', { name: '회차: 도움이 안 됐어요' });
const rating = (extra = {}) => ({
  ...target,
  storage: 'local_preview',
  value: 'none',
  reason: null,
  csrfToken: 'test-csrf',
  ...extra,
});
const response = (body: unknown, status = 200) =>
  new Response(JSON.stringify(body), { status });

describe('local preview feedback storage boundary', () => {
  it('restores saved down reason, changes to up and cancels without deleting the target', async () => {
    const user = userEvent.setup();
    let saved = rating({ value: 'down', reason: '선정 이유가 짧아요.' });
    const fetcher = vi.fn(async (_url: unknown, init?: RequestInit) => {
      if (init?.method === 'PUT')
        saved = { ...saved, ...JSON.parse(String(init.body)) };
      return response(saved);
    });
    vi.stubGlobal('fetch', fetcher);
    const view = render(<BriefingPreviewFeedback {...target} subject="회차" />);
    expect(down().hasAttribute('disabled')).toBe(true);
    await waitFor(() =>
      expect(down().getAttribute('aria-pressed')).toBe('true'),
    );
    expect((screen.getByRole('textbox') as HTMLTextAreaElement).value).toBe(
      '선정 이유가 짧아요.',
    );
    await user.clear(screen.getByRole('textbox'));
    await user.type(screen.getByRole('textbox'), '  근거를 더 알고 싶어요.  ');
    await user.click(screen.getByRole('button', { name: '확인' }));
    await waitFor(() => expect(saved.reason).toBe('근거를 더 알고 싶어요.'));
    const put = fetcher.mock.calls.find(
      (call) => call[1]?.method === 'PUT',
    )![1]!;
    expect(put.headers).toMatchObject({ 'X-Preview-CSRF-Token': 'test-csrf' });
    expect(JSON.parse(String(put.body))).toEqual({
      ...target,
      value: 'down',
      reason: '근거를 더 알고 싶어요.',
    });
    view.unmount();
    render(<BriefingPreviewFeedback {...target} subject="회차" />);
    await waitFor(() =>
      expect((screen.getByRole('textbox') as HTMLTextAreaElement).value).toBe(
        '근거를 더 알고 싶어요.',
      ),
    );
    await user.click(up());
    await waitFor(() => expect(up().getAttribute('aria-pressed')).toBe('true'));
    expect(saved.reason).toBeNull();
    expect(screen.queryByRole('textbox')).toBeNull();
    await user.click(up());
    await waitFor(() => expect(saved.value).toBe('none'));
    expect(saved.targetId).toBe(target.targetId);
    expect(up().getAttribute('aria-pressed')).toBe('false');
  });

  it('keeps the last confirmed vote after failure and retries the desired state', async () => {
    const user = userEvent.setup();
    const fetcher = vi
      .fn()
      .mockResolvedValueOnce(response(rating({ value: 'up' })))
      .mockResolvedValueOnce(
        response({ error: { message: '저장하지 못했어요.' } }, 503),
      )
      .mockResolvedValueOnce(response(rating()));
    vi.stubGlobal('fetch', fetcher);
    render(<BriefingPreviewFeedback {...target} subject="회차" />);
    await waitFor(() => expect(up().getAttribute('aria-pressed')).toBe('true'));
    await user.click(up());
    await screen.findByRole('alert');
    expect(up().getAttribute('aria-pressed')).toBe('true');
    await user.click(
      screen.getByRole('button', { name: '같은 평가 다시 저장' }),
    );
    await waitFor(() =>
      expect(up().getAttribute('aria-pressed')).toBe('false'),
    );
    const writes = fetcher.mock.calls.filter(
      (call) => call[1]?.method === 'PUT',
    );
    expect(writes.map((call) => JSON.parse(call[1].body).value)).toEqual([
      'none',
      'none',
    ]);
  });

  it('rejects another version and allows a fresh read before enabling buttons', async () => {
    const user = userEvent.setup();
    vi.stubGlobal(
      'fetch',
      vi
        .fn()
        .mockResolvedValueOnce(response(rating({ resultVersion: 'old' })))
        .mockResolvedValueOnce(response(rating())),
    );
    render(<BriefingPreviewFeedback {...target} subject="회차" />);
    expect(await screen.findByText(/다른 회차·버전/)).toBeTruthy();
    expect(up().hasAttribute('disabled')).toBe(true);
    await user.click(screen.getByRole('button', { name: '내 평가 다시 확인' }));
    await waitFor(() => expect(up().hasAttribute('disabled')).toBe(false));
  });

  it('does not apply a late write to a newly selected round or version', async () => {
    const user = userEvent.setup();
    let resolveWrite!: (response: Response) => void;
    const write = new Promise<Response>((resolve) => {
      resolveWrite = resolve;
    });
    vi.stubGlobal(
      'fetch',
      vi
        .fn()
        .mockResolvedValueOnce(response(rating()))
        .mockImplementationOnce(() => write)
        .mockResolvedValueOnce(response(rating({ resultVersion: 'result-2' }))),
    );
    const view = render(<BriefingPreviewFeedback {...target} subject="회차" />);
    await waitFor(() => expect(up().hasAttribute('disabled')).toBe(false));
    await user.click(up());
    view.rerender(
      <BriefingPreviewFeedback
        {...target}
        resultVersion="result-2"
        subject="회차"
      />,
    );
    await waitFor(() => expect(up().hasAttribute('disabled')).toBe(false));
    await act(async () => {
      resolveWrite(response(rating({ value: 'up' })));
      await write;
    });
    expect(up().getAttribute('aria-pressed')).toBe('false');
  });

  it('serializes first reads so simultaneous cards share one reviewer cookie', async () => {
    let resolveFirst!: (response: Response) => void;
    const first = new Promise<Response>((resolve) => {
      resolveFirst = resolve;
    });
    const issue = {
      ...target,
      feature: 'briefing_issue',
      targetId: 'preview-round/issue-1',
    };
    const fetcher = vi
      .fn()
      .mockImplementationOnce(() => first)
      .mockResolvedValueOnce(response(rating(issue)));
    vi.stubGlobal('fetch', fetcher);
    render(
      <>
        <BriefingPreviewFeedback {...target} subject="회차" />
        <BriefingPreviewFeedback
          {...target}
          feature="briefing_issue"
          targetId={issue.targetId}
          subject="이슈"
        />
      </>,
    );
    await waitFor(() => expect(fetcher).toHaveBeenCalledTimes(1));
    await act(async () => {
      resolveFirst(response(rating()));
      await first;
    });
    await waitFor(() => expect(fetcher).toHaveBeenCalledTimes(2));
    await waitFor(() =>
      expect(
        screen
          .getByRole('button', { name: '이슈: 도움이 됐어요' })
          .hasAttribute('disabled'),
      ).toBe(false),
    );
  });
});
