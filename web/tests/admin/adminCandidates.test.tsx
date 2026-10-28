import {
  act,
  fireEvent,
  screen,
  waitFor,
  within,
} from '@testing-library/react';
import { beforeEach, describe, expect, test } from 'vitest';
import AdminProtectedRoute from '@/components/admin/common/AdminProtectedRoute';
import PipelineReview from '@/components/admin/pipeline/PipelineReview';
import { useAdminSessionStore } from '@/stores/useAdminSessionStore';
import type { AdminSession } from '@/types/admin';
import {
  apiError,
  createFakeServer,
  deferred,
  json,
  type FakeServer,
} from '../support/fakeServer';
import { renderRoutes } from '../support/renderRoutes';
import {
  CANDIDATE,
  CANDIDATES,
  candidate,
  candidateDetail,
  onOverview,
} from '../support/adminPipeline';

// A-ADM-03 후보 탭 (FS067-01·FS067-02). 합성 계약 픽스처만 쓴다.
const session: AdminSession = {
  authenticated: true,
  expired: false,
  expiredReason: null,
  admin: {
    id: 'a1',
    email: 'admin@zoop.test',
    displayName: '관리자',
    role: 'operator',
  },
  expiresAt: '2099-01-01T00:00:00Z',
  idleExpiresAt: '2099-01-01T00:00:00Z',
  idleTimeoutSeconds: 1800,
  absoluteTimeoutSeconds: 28800,
  csrfToken: 'test-admin-csrf',
};
const counts = { ALLOW: 7, HOLD: 3, REJECT: 2, inactive: 2 };
let server: FakeServer;
function open(path = '/admin/pipeline?tab=candidates') {
  return renderRoutes(
    [
      {
        element: <AdminProtectedRoute />,
        children: [{ path: '/admin/pipeline', element: <PipelineReview /> }],
      },
      { path: '/admin/login', element: <p>관리자 로그인</p> },
    ],
    path,
  );
}
const listCalls = () => server.calls('GET', CANDIDATES);

beforeEach(() => {
  useAdminSessionStore.getState().setSession(session);
  server = createFakeServer();
  onOverview(server);
  server.on('GET', '/api/v1/admin/graph/versions', () =>
    json({
      items: [],
      activations: [],
      activeVersionId: null,
      nextCursor: null,
    }),
  );
  server.on('GET', CANDIDATES, () =>
    json({
      items: [
        candidate('cand-1'),
        candidate('cand-2', {
          title: null,
          active: false,
          companies: [],
          decision: {
            id: 1,
            targetType: 'candidate',
            targetId: 'cand-2',
            decision: 'reject',
            reason: '중복',
            adminEmail: 'admin@zoop.test',
            decidedAt: '2026-10-27T05:00:00Z',
            revision: 1,
            origin: 'admin',
          },
        }),
      ],
      nextCursor: null,
      counts,
      asOf: '2026-10-28T01:00:00Z',
    }),
  );
  server.on('GET', CANDIDATE, ({ params }) =>
    json(candidateDetail(params.candidateId)),
  );
});

describe('A-ADM-03 후보 탭 · 67', () => {
  test('보류 후보를 기본으로 판정 수와 함께 보여 주고, 없는 값은 대체 문구로 둔다', async () => {
    open();

    const table = await screen.findByRole('table', { name: '후보 목록' });
    expect(listCalls()[0].query.get('status')).toBe('HOLD');
    const status = screen.getByRole('group', { name: '판정 상태' });
    expect(
      within(status)
        .getByRole('button', { name: '보류 3' })
        .getAttribute('aria-pressed'),
    ).toBe('true');
    expect(within(status).getByRole('button', { name: '통과 7' })).toBeTruthy();
    expect(within(status).getByRole('button', { name: '폐기 2' })).toBeTruthy();
    const rows = within(table).getAllByRole('row');
    expect(rows[1].textContent).toContain('삼성전자, 미국 공장 증설');
    expect(rows[1].textContent).toContain('표시 안 함');
    expect(rows[2].textContent).toContain('사건 없는 관계 후보');
    expect(rows[2].textContent).toContain('비활성');
    expect(rows[2].textContent).toContain('거부');
    expect(screen.getByText(/비활성 2건/)).toBeTruthy();
  });

  test('후보를 고르면 원문 인용·연결 관계·검증 판정을 보여 주고 주소에 남긴다. 결정 버튼은 아직 없다', async () => {
    const { user, location } = open();

    await user.click(
      await screen.findByRole('button', { name: '삼성전자, 미국 공장 증설' }),
    );
    expect(location()).toBe('/admin/pipeline?tab=candidates&candidate=cand-1');
    const aside = screen.getByRole('complementary', { name: '후보 상세' });
    expect(
      await within(aside).findByText('삼성전자가 미국 공장을 증설한다'),
    ).toBeTruthy();
    expect(aside.textContent).toContain('연합뉴스');
    expect(aside.textContent).toContain('공개 대상이 아니에요');
    expect(aside.textContent).toContain('보류 사유');
    expect(aside.textContent).toContain('출처가 하나뿐이에요');
    expect(
      within(aside).getByRole('table', { name: '연결 관계' }).textContent,
    ).toContain('직접 관련');
    expect(
      within(aside).getByRole('table', { name: '검증 판정' }).textContent,
    ).toContain('출처 부족');
    expect(
      within(aside)
        .getByRole('link', { name: '원문 기사 ↗' })
        .getAttribute('rel'),
    ).toBe('noopener noreferrer');
    expect(aside.textContent).toContain('허용·거부 결정은 준비 중이에요');
    expect(
      within(aside).queryByRole('button', { name: /허용|거부/ }),
    ).toBeNull();

    await user.click(
      within(aside).getByRole('button', { name: '후보 상세 닫기' }),
    );
    expect(location()).toBe('/admin/pipeline?tab=candidates');
  });

  test('주소의 후보를 바로 열고, 검증되지 않은 인용은 원문 대신 안내한다', async () => {
    server.on('GET', CANDIDATE, ({ params }) =>
      json(
        candidateDetail(params.candidateId, {
          evidence: [
            {
              articleId: 'art-1',
              articleVersion: 'v1',
              start: 0,
              end: 4,
              quote: null,
              articleTitle: null,
              url: null,
            },
          ],
          history: [
            {
              id: 3,
              targetType: 'candidate',
              targetId: params.candidateId,
              decision: 'allow',
              reason: '공시 확인',
              adminEmail: 'admin@zoop.test',
              decidedAt: '2026-10-27T05:00:00Z',
              revision: 2,
              origin: 'admin',
            },
          ],
        }),
      ),
    );
    open('/admin/pipeline?tab=candidates&status=all&candidate=cand-9');

    const aside = screen.getByRole('complementary', { name: '후보 상세' });
    expect(
      await within(aside).findByText('인용 원문을 확인할 수 없어요.'),
    ).toBeTruthy();
    expect(aside.textContent).toContain('cand-9');
    expect(aside.textContent).toContain('허용 · admin@zoop.test');
    expect(aside.textContent).toContain('공시 확인');
    await screen.findByRole('table', { name: '후보 목록' });
    expect(listCalls()[0].query.has('status')).toBe(false);
  });

  test('필터를 바꾸면 주소에 남기고 커서 없이 첫 쪽부터 다시 읽는다', async () => {
    server.on('GET', CANDIDATES, ({ query }) =>
      json({
        items: [candidate(query.has('cursor') ? 'cand-next' : 'cand-1')],
        nextCursor: query.has('cursor') ? null : 'signed-cursor',
        counts,
        asOf: '2026-10-28T01:00:00Z',
      }),
    );
    const { user, location } = open();

    await screen.findByRole('table', { name: '후보 목록' });
    await user.click(screen.getByRole('button', { name: '더 보기' }));
    await screen.findAllByRole('button', { name: '삼성전자, 미국 공장 증설' });
    expect(listCalls()[1].query.get('cursor')).toBe('signed-cursor');

    fireEvent.change(screen.getByRole('combobox', { name: '검수 결정' }), {
      target: { value: 'none' },
    });
    fireEvent.change(screen.getByRole('combobox', { name: '사용자 그래프' }), {
      target: { value: 'false' },
    });
    fireEvent.change(screen.getByRole('combobox', { name: '후보 상태' }), {
      target: { value: 'true' },
    });
    await user.click(screen.getByRole('button', { name: /^통과/ }));
    expect(location()).toBe(
      '/admin/pipeline?tab=candidates&decision=none&published=false&active=true&status=ALLOW',
    );
    await screen.findByRole('table', { name: '후보 목록' });
    const last = listCalls().at(-1)!;
    expect(last.query.get('status')).toBe('ALLOW');
    expect(last.query.get('decision')).toBe('none');
    expect(last.query.get('published')).toBe('false');
    expect(last.query.get('active')).toBe('true');
    expect(last.query.has('cursor')).toBe(false);
  });

  test('검색어는 바로 주소에 남기고 잠시 뒤 요청한다', async () => {
    const { user, location } = open();
    await screen.findByRole('table', { name: '후보 목록' });

    await user.type(
      screen.getByRole('searchbox', { name: '후보 검색' }),
      '삼성',
    );
    expect(location()).toBe(
      '/admin/pipeline?tab=candidates&q=%EC%82%BC%EC%84%B1',
    );
    await waitFor(() =>
      expect(listCalls().at(-1)!.query.get('q')).toBe('삼성'),
    );
    expect(listCalls().some((call) => call.query.get('q') === '삼')).toBe(
      false,
    );
  });

  test('목록을 불러오지 못하면 오류와 다시 시도를 보여 준다', async () => {
    server.on('GET', CANDIDATES, () => apiError(503, 'SOURCE_UNAVAILABLE'));
    open();

    expect(
      await screen.findByText('후보 목록을 불러오지 못했어요'),
    ).toBeTruthy();
  });

  test('다른 탭에 다녀와도 후보 탭을 다시 읽지 않고, 관리자 세션이 바뀌면 이전 목록을 숨긴다', async () => {
    const { user } = open();
    await screen.findByRole('table', { name: '후보 목록' });

    await user.click(screen.getByRole('tab', { name: '그래프 버전' }));
    await user.click(screen.getByRole('tab', { name: '후보' }));
    expect(listCalls()).toHaveLength(1);
    expect(screen.getByRole('table', { name: '후보 목록' })).toBeTruthy();

    const pending = deferred<Response>();
    server.on('GET', CANDIDATES, () => pending.promise);
    act(() => {
      useAdminSessionStore.getState().setSession(session);
    });
    expect(screen.queryByRole('table', { name: '후보 목록' })).toBeNull();
    expect(screen.getByText('후보를 불러오고 있어요')).toBeTruthy();
  });
});
