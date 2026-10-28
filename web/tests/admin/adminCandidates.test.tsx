import { act, screen, waitFor, within } from '@testing-library/react';
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
    expect(rows[1].textContent).toContain('표시 안 됨·확인 못 함');
    expect(rows[2].textContent).toContain('사건 없는 관계 후보');
    expect(rows[2].textContent).toContain('비활성');
    expect(rows[2].textContent).toContain('거부');
    expect(screen.getByText(/비활성 2건/)).toBeTruthy();
  });

  test('후보를 고르면 원문 인용·연결 관계·검증 판정과 관계별 결정 버튼을 보여 주고 주소에 남긴다', async () => {
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
    expect(
      (
        within(aside).getByRole('button', {
          name: '삼성전자 → 미국 공장 증설 관계 승인',
        }) as HTMLButtonElement
      ).disabled,
    ).toBe(false);
    expect(
      (
        within(aside).getByRole('button', {
          name: '삼성전자 → 미국 공장 증설 관계 거부',
        }) as HTMLButtonElement
      ).disabled,
    ).toBe(false);

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

    await user.click(screen.getByRole('button', { name: '규칙 대상만' }));
    await user.click(screen.getByRole('button', { name: /^통과/ }));
    expect(location()).toBe(
      '/admin/pipeline?tab=candidates&rule=true&status=ALLOW',
    );
    await screen.findByRole('table', { name: '후보 목록' });
    const last = listCalls().at(-1)!;
    expect(last.query.get('status')).toBe('ALLOW');
    expect(last.query.get('rule')).toBe('true');
    expect(last.query.has('cursor')).toBe(false);

    await user.click(screen.getByRole('button', { name: '모든 후보' }));
    expect(location()).toBe('/admin/pipeline?tab=candidates&status=ALLOW');
    await waitFor(() =>
      expect(listCalls().at(-1)!.query.has('rule')).toBe(false),
    );
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

describe('A-ADM-03 후보 결정 · 67 (decideAnalysisCandidate)', () => {
  const DECISION = `${CANDIDATE}/decision`;
  const approve = '삼성전자 → 미국 공장 증설 관계 승인';
  const reject = '삼성전자 → 미국 공장 증설 관계 거부';

  async function openDetail() {
    const view = open('/admin/pipeline?candidate=cand-1');
    const aside = screen.getByRole('complementary', { name: '후보 상세' });
    await within(aside).findByRole('button', { name: approve });
    return { ...view, aside };
  }

  test('사유를 받아 상세에서 본 관계 revision·AI 원천과 함께 승인을 보내고, 상세와 목록을 다시 읽는다', async () => {
    server.on('POST', DECISION, () =>
      json({
        candidateId: 'cand-1',
        decision: 'approved',
        revision: 2,
        publicChanged: false,
      }),
    );
    const { user, aside } = await openDetail();
    const listBefore = listCalls().length;

    await user.click(within(aside).getByRole('button', { name: approve }));
    const form = within(aside).getByRole('form', { name: '관계 승인' });
    expect(form.textContent).toContain('승인해도 바로 공개되지 않고');
    await user.click(within(form).getByRole('button', { name: '승인하기' }));
    expect(within(form).getByRole('alert').textContent).toContain(
      '사유를 1~500자로 입력해 주세요.',
    );
    expect(server.calls('POST', DECISION)).toHaveLength(0);

    server.on('GET', CANDIDATE, ({ params }) =>
      json(
        candidateDetail(params.candidateId, {
          relations: [
            {
              ...candidateDetail().relations[0],
              revision: 2,
              decision: {
                id: 9,
                targetType: 'relation',
                targetId: 'rel-1',
                decision: 'allow',
                reason: '공시 확인',
                adminEmail: 'admin@zoop.test',
                decidedAt: '2026-10-28T02:00:00Z',
                revision: 2,
                origin: 'admin',
              },
            },
          ],
        }),
      ),
    );
    await user.type(within(form).getByLabelText('승인 사유'), ' 공시 확인 ');
    await user.click(within(form).getByRole('button', { name: '승인하기' }));

    const [call] = server.calls('POST', DECISION);
    expect(call.params.candidateId).toBe('cand-1');
    expect(call.body).toEqual({
      decision: 'allow',
      reason: '공시 확인',
      relationId: 'rel-1',
      expectedRevision: 1,
      expectedSourceVersion: 'src-v3',
      expectedSourceRevision: 'r1',
    });
    expect(call.headers.get('Idempotency-Key')).toBeTruthy();
    expect(call.headers.get('X-CSRF-Token')).toBe('test-admin-csrf');
    expect(
      await within(aside).findByText(
        '관계를 승인했어요. 다음 그래프 버전을 만들 때 반영돼요.',
      ),
    ).toBeTruthy();
    await waitFor(() =>
      expect(
        within(aside).getByRole('table', { name: '연결 관계' }).textContent,
      ).toContain('허용'),
    );
    expect(within(aside).queryByRole('button', { name: approve })).toBeNull();
    expect(listCalls().length).toBeGreaterThan(listBefore);
  });

  test('그 사이 관계가 바뀌었으면(409) 사유를 남긴 채 상세를 새로 읽으라고 알린다', async () => {
    server.on('POST', DECISION, () => apiError(409, 'REVISION_CONFLICT'));
    const { user, aside } = await openDetail();

    await user.click(within(aside).getByRole('button', { name: reject }));
    const form = within(aside).getByRole('form', { name: '관계 거부' });
    await user.type(within(form).getByLabelText('거부 사유'), '오보');
    await user.click(within(form).getByRole('button', { name: '거부하기' }));

    expect((await within(form).findByRole('alert')).textContent).toContain(
      '관계 상태나 AI 원천이 바뀌었어요.',
    );
    expect(await within(form).findByText(/상세를 새로 읽었어요/)).toBeTruthy();
    expect(
      (within(form).getByLabelText('거부 사유') as HTMLTextAreaElement).value,
    ).toBe('오보');
    expect(server.calls('POST', DECISION)[0].body).toMatchObject({
      decision: 'reject',
      relationId: 'rel-1',
    });
    // 409면 상세를 다시 읽는다(1-3·2-6).
    await waitFor(() => expect(server.calls('GET', CANDIDATE)).toHaveLength(2));
  });

  test('다시 읽은 관계를 그 사이 다른 관리자가 결정했으면 폼을 닫고 알린다', async () => {
    server.on('POST', DECISION, () => {
      server.on('GET', CANDIDATE, ({ params }) => {
        const base = candidateDetail(params.candidateId);
        return json({
          ...base,
          relations: [
            ...base.relations.map((relation) => ({
              ...relation,
              revision: 2,
              decision: {
                id: 9,
                targetType: 'relation',
                targetId: relation.relationId,
                decision: 'allow' as const,
                reason: '확인',
                adminEmail: 'other@zoop.test',
                decidedAt: '2026-10-28T05:00:00Z',
                revision: 2,
                origin: 'admin',
              },
            })),
            // 다른 관계는 아직 결정하지 않았다.
            {
              ...base.relations[0],
              relationId: 'rel-2',
              target: '반도체 수출 규제',
            },
          ],
        });
      });
      return apiError(409, 'REVISION_CONFLICT');
    });
    const { user, aside } = await openDetail();

    await user.click(within(aside).getByRole('button', { name: reject }));
    const form = within(aside).getByRole('form', { name: '관계 거부' });
    await user.type(within(form).getByLabelText('거부 사유'), '오보');
    await user.click(within(form).getByRole('button', { name: '거부하기' }));

    expect(
      await within(aside).findByText(/그 사이 고른 관계가 결정됐거나/),
    ).toBeTruthy();
    expect(within(aside).queryByRole('form', { name: '관계 거부' })).toBeNull();
    // #393 리뷰 2: 선택이 풀려 다른 관계를 바로 고를 수 있다.
    const other = within(aside).getByRole('button', {
      name: '삼성전자 → 반도체 수출 규제 관계 거부',
    }) as HTMLButtonElement;
    expect(other.disabled).toBe(false);
    await user.click(other);
    expect(within(aside).getByRole('form', { name: '관계 거부' })).toBeTruthy();
    expect(
      within(aside).queryByText(/그 사이 고른 관계가 결정됐거나/),
    ).toBeNull();
  });

  // #393 리뷰 1: 새 상세가 오기 전이나 다시 읽기에 실패하면 예전 revision으로 보내지 않는다.
  test('409 뒤 상세를 다시 읽는 동안·실패하면 보내기를 막고 다시 읽기를 제공한다', async () => {
    server.on('POST', DECISION, () => {
      server.on('GET', CANDIDATE, () => apiError(503, 'SOURCE_UNAVAILABLE'));
      return apiError(409, 'REVISION_CONFLICT');
    });
    const { user, aside } = await openDetail();

    await user.click(within(aside).getByRole('button', { name: reject }));
    const form = within(aside).getByRole('form', { name: '관계 거부' });
    await user.type(within(form).getByLabelText('거부 사유'), '오보');
    await user.click(within(form).getByRole('button', { name: '거부하기' }));

    const retry = await within(form).findByRole('button', {
      name: '다시 읽기',
    });
    expect(within(form).getByText(/상세를 새로 읽지 못했어요/)).toBeTruthy();
    expect(
      (
        within(form).getByRole('button', {
          name: '거부하기',
        }) as HTMLButtonElement
      ).disabled,
    ).toBe(true);
    expect(within(form).queryByText(/상세를 새로 읽었어요/)).toBeNull();

    let release!: () => void;
    server.on('GET', CANDIDATE, async ({ params }) => {
      await new Promise<void>((resolve) => {
        release = resolve;
      });
      return json(candidateDetail(params.candidateId));
    });
    await user.click(retry);
    expect(
      await within(form).findByText(/상세를 새로 읽고 있어요/),
    ).toBeTruthy();
    expect(
      (
        within(form).getByRole('button', {
          name: '거부하기',
        }) as HTMLButtonElement
      ).disabled,
    ).toBe(true);
    release();
    expect(await within(form).findByText(/상세를 새로 읽었어요/)).toBeTruthy();
    expect(
      (
        within(form).getByRole('button', {
          name: '거부하기',
        }) as HTMLButtonElement
      ).disabled,
    ).toBe(false);
    expect(
      (within(form).getByLabelText('거부 사유') as HTMLTextAreaElement).value,
    ).toBe('오보');
  });

  test.each([
    ['ALLOW', true, false, null],
    ['REJECT', true, true, '폐기 판정 후보는 결정할 수 없어요.'],
    ['HOLD', false, true, '비활성 후보는 결정할 수 없어요.'],
  ] as const)(
    '%s 판정(active=%s)이면 승인할 수 없고, 거부 불가=%s',
    async (status, active, rejectDisabled, note) => {
      server.on('GET', CANDIDATE, ({ params }) =>
        json(candidateDetail(params.candidateId, { status, active })),
      );
      open('/admin/pipeline?candidate=cand-1');
      const aside = screen.getByRole('complementary', { name: '후보 상세' });
      const allowButton = (await within(aside).findByRole('button', {
        name: approve,
      })) as HTMLButtonElement;
      expect(allowButton.disabled).toBe(true);
      expect(
        (
          within(aside).getByRole('button', {
            name: reject,
          }) as HTMLButtonElement
        ).disabled,
      ).toBe(rejectDisabled);
      if (note) expect(aside.textContent).toContain(note);
    },
  );
});

describe('A-ADM-03 후보 공개 표시 · #379 리뷰', () => {
  test('그래프 버전을 바꾸면 필터·고른 후보를 그대로 두고 목록과 상세를 다시 읽는다', async () => {
    const VERSIONS = '/api/v1/admin/graph/versions';
    const ACTIVATE = `${VERSIONS}/:versionId/activate`;
    const graphVersion = (id: string, active: boolean) => ({
      id,
      sequence: id === 'v2' ? 2 : 1,
      kind: 'snapshot',
      createdAt: '2026-10-21T03:00:00Z',
      createdBy: 'importer',
      reason: null,
      sourceLabel: '합성',
      policyVersion: null,
      issueCount: 1,
      relationCount: 1,
      articleCount: 1,
      candidateCount: 1,
      sha256: 'a'.repeat(64),
      bytes: 1,
      active,
      activatedAt: null,
      graphDb: { status: 'reflected', pendingJobsAtCreation: 0, note: null },
    });
    let active = 'v2';
    server.on('GET', VERSIONS, () =>
      json({
        activeVersionId: active,
        items: [
          graphVersion('v2', active === 'v2'),
          graphVersion('v1', active === 'v1'),
        ],
        activations: [],
        nextCursor: null,
      }),
    );
    server.on('POST', ACTIVATE, () => {
      active = 'v1';
      return json({
        activeVersionId: 'v1',
        previousActiveVersionId: 'v2',
        idempotent: false,
      });
    });
    const { user, location } = open(
      '/admin/pipeline?tab=versions&rule=true&candidate=cand-1',
    );
    await screen.findByRole('table', { name: '그래프 버전 목록' });
    await waitFor(() => expect(server.calls('GET', CANDIDATE)).toHaveLength(1));
    const lists = listCalls().length;

    await user.click(screen.getByRole('button', { name: 'v1로 전환' }));
    const form = screen.getByRole('form', { name: '그래프 버전 전환' });
    await user.type(
      within(form).getByLabelText('전환 사유(감사 로그에 남아요)'),
      '되돌림',
    );
    await user.click(within(form).getByRole('button', { name: 'v1로 전환' }));
    await screen.findByText('v1로 바꿨어요.');

    await waitFor(() => expect(server.calls('GET', CANDIDATE)).toHaveLength(2));
    expect(listCalls().length).toBeGreaterThan(lists);
    expect(listCalls().at(-1)?.query.get('rule')).toBe('true');
    expect(location()).toBe(
      '/admin/pipeline?tab=versions&rule=true&candidate=cand-1',
    );
  });

  test('공개 여부를 확인하지 못한 후보는 비공개로 단정하지 않는다', async () => {
    server.on('GET', CANDIDATE, ({ params }) =>
      json(candidateDetail(params.candidateId, { graphDb: 'unknown' })),
    );
    open('/admin/pipeline?candidate=cand-1');

    const table = await screen.findByRole('table', { name: '후보 목록' });
    expect(within(table).getAllByRole('row')[1].textContent).toContain(
      '표시 안 됨·확인 못 함',
    );
    expect(screen.getByText(/공개 여부를 확인하지 못한/)).toBeTruthy();
    const aside = screen.getByRole('complementary', { name: '후보 상세' });
    const relations = await within(aside).findByRole('table', {
      name: '연결 관계',
    });
    expect(aside.textContent).not.toContain('표시 안 함');
    expect(relations.textContent).toContain('확인할 수 없어요');
  });

  test('검수 이력에 결정 대상(후보·관계 id)과 판정 회차를 보이고, 관계 표에 관계 id를 보인다', async () => {
    const decision = {
      id: 3,
      decision: 'reject' as const,
      reason: '근거 부족',
      adminEmail: 'admin@zoop.test',
      decidedAt: '2026-10-27T05:00:00Z',
      origin: 'admin',
    };
    server.on('GET', CANDIDATE, ({ params }) =>
      json(
        candidateDetail(params.candidateId, {
          history: [
            {
              ...decision,
              targetType: 'relation',
              targetId: 'rel-1',
              revision: 2,
            },
            {
              ...decision,
              id: 4,
              targetType: 'candidate',
              targetId: 'cand-1',
              revision: 1,
            },
          ],
        }),
      ),
    );
    open('/admin/pipeline?candidate=cand-1');

    const aside = screen.getByRole('complementary', { name: '후보 상세' });
    const relations = await within(aside).findByRole('table', {
      name: '연결 관계',
    });
    expect(relations.textContent).toContain('rel-1 · 회차 1');
    expect(aside.textContent).toContain('관계 rel-1 · 판정 회차 2');
    expect(aside.textContent).toContain('후보 cand-1 · 판정 회차 1');
  });
});
