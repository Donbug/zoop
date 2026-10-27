import { useCallback } from 'react';
import { act, fireEvent, render, screen } from '@testing-library/react';
import { afterEach, beforeEach, describe, expect, test, vi } from 'vitest';
import { useAsyncData } from '@/hooks/useAsyncData';
import { useCursorPages } from '@/hooks/useCursorPages';
import { useAdminRefresh } from '@/hooks/useAdminRefresh';
import { createFakeServer, deferred, json } from '../support/fakeServer';

type Page = { items: string[]; nextCursor: string | null };
async function read(path: string) {
  const response = await fetch(path);
  if (!response.ok) throw new Error('갱신 실패');
  return response.json() as Promise<Page>;
}
function Panel({
  owner = 'a',
  editing = false,
  hiddenEditing = false,
  interval = 10000,
  pages = false,
}) {
  const load = useCallback(() => read(`/data/${owner}`), [owner]);
  const loadPages = useCallback(
    (cursor?: string) =>
      read(`/pages/${owner}${cursor ? `?cursor=${cursor}` : ''}`),
    [owner],
  );
  const one = useAsyncData(load);
  const many = useCursorPages(loadPages);
  const result = pages ? many : one;
  useAdminRefresh(result.reload, interval);
  return (
    <>
      {editing && (
        <div hidden={hiddenEditing}>
          <form data-admin-editing="true" aria-label="변경 사유" />
        </div>
      )}
      <p>{result.status}</p>
      <p>{(pages ? many.items : one.data?.items)?.join(',')}</p>
      {result.refreshError && <p role="alert">이전 결과 유지</p>}
      <button onClick={() => result.reload()}>다시 읽기</button>
      <button onClick={many.loadMore}>더 보기</button>
    </>
  );
}
const flush = async () => {
  await act(async () => {
    await Promise.resolve();
  });
};
const tick = async (ms = 10000) => {
  await act(async () => {
    await vi.advanceTimersByTimeAsync(ms);
  });
};

describe('A-ADM-01~05 관리자 주기 갱신', () => {
  let server: ReturnType<typeof createFakeServer>;
  beforeEach(() => {
    vi.useFakeTimers();
    server = createFakeServer();
    server.on('GET', '/data/:owner', ({ params }) =>
      json({ items: [params.owner], nextCursor: null }),
    );
    server.on('GET', '/pages/:owner', () =>
      json({ items: ['first'], nextCursor: 'old' }),
    );
    Object.defineProperty(document, 'visibilityState', {
      configurable: true,
      value: 'visible',
    });
  });
  afterEach(() => {
    vi.unstubAllGlobals();
    vi.useRealTimers();
  });

  test('10초 갱신 중 이전 결과 유지·중복 요청 방지·오류 뒤 복구', async () => {
    render(<Panel />);
    await flush();
    const pending = deferred<Response>();
    server.on('GET', '/data/a', () => pending.promise);
    await tick();
    await tick();
    expect(screen.getByText('a')).toBeTruthy();
    expect(screen.getByText('success')).toBeTruthy();
    expect(server.requests.filter((r) => r.path === '/data/a')).toHaveLength(2);
    pending.resolve(json({}, 500));
    await flush();
    expect(screen.getByRole('alert').textContent).toContain('이전 결과');
    server.on('GET', '/data/a', () =>
      json({ items: ['new'], nextCursor: null }),
    );
    await tick();
    expect(screen.getByText('new')).toBeTruthy();
    expect(screen.queryByRole('alert')).toBeNull();
  });
  test('숨겨진 문서·열린 폼에서 멈추고 요청 중 열린 폼에도 도착한 목록을 적용하지 않아요', async () => {
    const view = render(<Panel />);
    await flush();
    Object.defineProperty(document, 'visibilityState', {
      configurable: true,
      value: 'hidden',
    });
    await tick();
    expect(server.requests.filter((r) => r.path === '/data/a')).toHaveLength(1);
    Object.defineProperty(document, 'visibilityState', {
      configurable: true,
      value: 'visible',
    });
    view.rerender(<Panel editing />);
    await tick();
    expect(server.requests.filter((r) => r.path === '/data/a')).toHaveLength(1);
    view.rerender(<Panel />);
    const pending = deferred<Response>();
    server.on('GET', '/data/a', () => pending.promise);
    await tick();
    view.rerender(<Panel editing />);
    pending.resolve(json({ items: ['should not replace'], nextCursor: null }));
    await flush();
    expect(screen.getByText('a')).toBeTruthy();
    expect(screen.queryByText('should not replace')).toBeNull();
  });
  test('5초 간격·회원 변경의 늦은 응답 차단·수동 읽기는 loading·언마운트 정리', async () => {
    const view = render(<Panel interval={5000} />);
    await flush();
    const pending = deferred<Response>();
    server.on('GET', '/data/a', () => pending.promise);
    await tick(5000);
    view.rerender(<Panel owner="b" interval={5000} />);
    await flush();
    pending.resolve(json({ items: ['old owner'], nextCursor: null }));
    await flush();
    expect(screen.getByText('b')).toBeTruthy();
    expect(screen.queryByText('old owner')).toBeNull();
    server.on('GET', '/data/b', () => deferred<Response>().promise);
    fireEvent.click(screen.getByText('다시 읽기'));
    expect(screen.getByText('loading')).toBeTruthy();
    view.unmount();
    const count = server.requests.length;
    await tick();
    expect(server.requests).toHaveLength(count);
  });
  test('커서 목록은 새 커서로 이미 읽은 쪽 수만큼 갱신하고 기존 목록·오류를 유지해요', async () => {
    server.on('GET', '/pages/a', ({ query }) =>
      json({
        items: [query.has('cursor') ? 'second' : 'first'],
        nextCursor: query.has('cursor') ? null : 'old',
      }),
    );
    render(<Panel pages />);
    await flush();
    fireEvent.click(screen.getByText('더 보기'));
    await flush();
    expect(screen.getByText('first,second')).toBeTruthy();
    const pending = deferred<Response>();
    server.on('GET', '/pages/a', ({ query }) =>
      query.has('cursor')
        ? json({ items: ['new second'], nextCursor: null })
        : pending.promise,
    );
    await tick();
    expect(screen.getByText('first,second')).toBeTruthy();
    pending.resolve(json({ items: ['new first'], nextCursor: 'fresh' }));
    await flush();
    expect(screen.getByText('new first,new second')).toBeTruthy();
    expect(server.requests.at(-1)?.query.get('cursor')).toBe('fresh');
    server.on('GET', '/pages/a', () => json({}, 500));
    await tick();
    expect(screen.getByText('new first,new second')).toBeTruthy();
    expect(screen.getByRole('alert')).toBeTruthy();
  });
  test('조회 조건이 바뀌면 이전 조건의 갱신 쪽 수를 가져오지 않고 첫 쪽부터 읽어요', async () => {
    server.on('GET', '/pages/a', ({ query }) =>
      json({
        items: [query.has('cursor') ? 'second' : 'first'],
        nextCursor: query.has('cursor') ? null : 'old',
      }),
    );
    const view = render(<Panel pages />);
    await flush();
    fireEvent.click(screen.getByText('더 보기'));
    await flush();
    await tick();
    server.on('GET', '/pages/b', () =>
      json({ items: ['new owner'], nextCursor: 'next' }),
    );
    view.rerender(<Panel pages owner="b" />);
    await flush();
    expect(screen.getByText('new owner')).toBeTruthy();
    expect(server.calls('GET', '/pages/b')).toHaveLength(1);
  });
  test('A-ADM-03 hidden 조상 안의 편집 폼은 주기 갱신을 막지 않아요', async () => {
    render(<Panel editing hiddenEditing />);
    await flush();
    server.on('GET', '/data/a', () =>
      json({ items: ['숨은 폼 갱신'], nextCursor: null }),
    );
    await tick();
    expect(server.calls('GET', '/data/a')).toHaveLength(2);
    expect(screen.getByText('숨은 폼 갱신')).toBeTruthy();
  });
  test.each([false, true])(
    'A-ADM-03 응답 도착 시 숨은 폼만 있으면 결과를 적용해요 (cursor=%s)',
    async (pages) => {
      const view = render(<Panel pages={pages} />);
      await flush();
      const pending = deferred<Response>();
      server.on('GET', pages ? '/pages/a' : '/data/a', () => pending.promise);
      await tick();
      view.rerender(<Panel pages={pages} editing hiddenEditing />);
      pending.resolve(json({ items: ['도착한 결과'], nextCursor: null }));
      await flush();
      expect(screen.getByText('도착한 결과')).toBeTruthy();
    },
  );
});
