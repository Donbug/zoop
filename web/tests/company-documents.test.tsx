import { act, render, screen, waitFor, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { beforeEach, expect, test } from 'vitest';
import {
  MemoryRouter,
  Route,
  Routes,
  useLocation,
  useNavigate,
} from 'react-router-dom';
import CompanyDocumentPanel from '@/components/company/CompanyDocumentPanel';
import {
  createFakeServer,
  json,
  apiError,
  deferred,
} from './support/fakeServer';
import type { CompanyDocument, Evidence } from '@/types/company/documents';
const companyId = 'KRX:SYNTHETIC',
  asOf = '2026-10-06T03:00:00Z';
const metadata = {
  source: 'synthetic',
  asOf,
  graphVersion: 'v1',
  requestId: 'req-company-documents',
  partial: false,
  failures: [],
};
const doc: CompanyDocument = {
  id: 'doc-a',
  title: '합성 뉴스 A',
  publisher: '합성 출처',
  publishedAt: '2026-10-05T03:00:00Z',
  url: 'https://example.test/source',
  kind: 'news',
  events: [
    { eventId: 'issue-a', title: '합성 사건 A', relationType: 'REPORTS' },
  ],
  quotes: [
    { evidenceId: 'ev-a', quote: '제공된 합성 인용 A', quoteVerified: true },
    { evidenceId: 'ev-b', quote: '제공된 합성 인용 B', quoteVerified: null },
  ],
  sentiment: null,
};
const other: CompanyDocument = {
  ...doc,
  id: 'doc-b',
  title: '합성 공시 B',
  kind: 'disclosure',
  url: null,
  quotes: [],
  events: [
    {
      eventId: 'issue-a',
      title: '합성 사건 A',
      relationType: 'PROVIDES_BACKGROUND',
    },
  ],
};
const evidence: Evidence = {
  id: 'ev-a',
  quote: '상세 합성 근거 인용',
  start: 4,
  end: 14,
  articleId: 'doc-a',
  articleVersion: 'article-v1',
  article: {
    title: '합성 뉴스 A',
    publisher: '합성 출처',
    publishedAt: doc.publishedAt,
    url: null,
  },
  quoteVerified: true,
  eventIds: ['issue-a'],
  metadata,
  sentiment: null,
};
let server: ReturnType<typeof createFakeServer>;
beforeEach(() => {
  server = createFakeServer();
  server.on('GET', '/api/v1/companies/:id/documents', (r) =>
    json({
      items:
        r.query.get('kind') === 'news'
          ? [doc]
          : r.query.get('kind') === 'disclosure'
            ? [other]
            : [doc, other],
      nextCursor: null,
      metadata: { ...metadata, asOf: r.query.get('asOf') ?? asOf },
    }),
  );
  server.on('GET', '/api/v1/evidence/:id', (r) =>
    json({ ...evidence, id: r.params.id }),
  );
});
const base = `?tab=documents&period=1w&asOf=${encodeURIComponent(asOf)}&graphVersion=v1`;
function Controls() {
  const l = useLocation(),
    nav = useNavigate();
  return (
    <>
      <output data-testid="address">
        {l.pathname}
        {l.search}
      </output>
      <button
        onClick={() =>
          nav(`/companies/OTHER${base}&document=doc-a&evidence=ev-a`)
        }
      >
        기업 바꾸기
      </button>
      <button
        onClick={() =>
          nav(
            `/companies/${companyId}?tab=documents&period=1w&asOf=2026-10-05T03%3A00%3A00Z&graphVersion=v1&document=doc-a&evidence=ev-a`,
          )
        }
      >
        시점 바꾸기
      </button>
    </>
  );
}
function open(extra = '') {
  return render(
    <MemoryRouter initialEntries={[`/companies/${companyId}${base}${extra}`]}>
      <Controls />
      <Routes>
        <Route path="/companies/:id" element={<CompanyDocumentPanel />} />
      </Routes>
    </MemoryRouter>,
  );
}
async function selectEvidence() {
  const user = userEvent.setup();
  await user.click(
    within(
      await screen.findByRole('article', { name: '문서 합성 뉴스 A' }),
    ).getByRole('button', { name: '문서 근거 선택 · 2건' }),
  );
  await user.click(screen.getByRole('button', { name: '근거 ev-a 상세' }));
  await screen.findByText('상세 합성 근거 인용');
  return user;
}

test('source/title/time/relationship and unique document counts match contract', async () => {
  open();
  await screen.findByRole('article', { name: '문서 합성 뉴스 A' });
  expect(screen.getByText('제공된 근거 문서 2건')).toBeTruthy();
  expect(
    screen.getByRole('button', { name: '합성 사건 A · 근거 문서 2건' }),
  ).toBeTruthy();
  expect(screen.getByText(/사건을 보도한 자료/)).toBeTruthy();
  expect(screen.getByText(/사건 배경을 제공한 자료/)).toBeTruthy();
  expect(
    screen.getByRole('link', { name: '원문 보기' }).getAttribute('href'),
  ).toBe(doc.url);
  expect(screen.getByText('원문을 제공하지 않는 자료입니다')).toBeTruthy();
});
test('news/disclosure filters retain period, reference time and public version', async () => {
  open();
  const user = userEvent.setup();
  await screen.findByRole('article', { name: '문서 합성 뉴스 A' });
  await user.click(screen.getByRole('button', { name: '공시' }));
  await screen.findByRole('article', { name: '문서 합성 공시 B' });
  expect(
    screen.queryByRole('article', { name: '문서 합성 뉴스 A' }),
  ).toBeNull();
  const request = server
    .calls('GET', '/api/v1/companies/:id/documents')
    .at(-1)!;
  expect(request.query.get('asOf')).toBe(asOf);
  expect(request.query.get('graphVersion')).toBe('v1');
  expect(request.query.get('kind')).toBe('disclosure');
  expect(screen.getByTestId('address').textContent).toContain('period=1w');
});
test('event scope counts documents, not number of quotes; linked issue preserves context', async () => {
  server.on('GET', '/api/v1/companies/:id/documents', () =>
    json({
      items: [
        doc,
        other,
        {
          ...other,
          id: 'doc-c',
          title: '다른 사건 공시',
          events: [{ eventId: 'issue-b', title: '사건 B', relationType: null }],
        },
      ],
      nextCursor: null,
      metadata,
    }),
  );
  open('&event=issue-a&docScope=event');
  await screen.findByText('제공된 근거 문서 2건');
  expect(
    screen.queryByRole('article', { name: '문서 다른 사건 공시' }),
  ).toBeNull();
  await userEvent.click(
    within(screen.getByRole('article', { name: '문서 합성 뉴스 A' })).getByRole(
      'button',
      { name: '합성 사건 A 사건 보기' },
    ),
  );
  expect(screen.getByTestId('address').textContent).toContain('tab=events');
  expect(screen.getByTestId('address').textContent).toContain('event=issue-a');
  expect(screen.getByTestId('address').textContent).toContain('period=1w');
});
test('evidence selection sends exact context and displays verified excerpt metadata', async () => {
  open('&event=issue-a&docScope=event');
  await selectEvidence();
  const req = server.calls('GET', '/api/v1/evidence/:id')[0];
  expect(req.query.get('companyId')).toBe(companyId);
  expect(req.query.get('asOf')).toBe(asOf);
  expect(req.query.get('graphVersion')).toBe('v1');
  expect(screen.getByTestId('address').textContent).toContain('document=doc-a');
  expect(screen.getByTestId('address').textContent).toContain('evidence=ev-a');
  const region = screen.getByRole('region', { name: '선택 근거 상세' });
  expect(within(region).getByText(/원문 대조 확인됨/)).toBeTruthy();
  expect(
    within(region).getByText('원문을 제공하지 않는 자료입니다'),
  ).toBeTruthy();
  await userEvent.click(screen.getByRole('button', { name: '근거 닫기' }));
  expect(screen.queryByText('상세 합성 근거 인용')).toBeNull();
  expect(screen.getByTestId('address').textContent).toContain('document=doc-a');
});
test('document lookup failure retries without masquerading as empty', async () => {
  server.on('GET', '/api/v1/companies/:id/documents', () =>
    apiError(503, 'SOURCE_UNAVAILABLE'),
  );
  open();
  await screen.findByText(/뉴스·공시 조회 실패/);
  expect(screen.queryByText('공개된 뉴스·공시가 없어요.')).toBeNull();
  server.on('GET', '/api/v1/companies/:id/documents', () =>
    json({ items: [doc], nextCursor: null, metadata }),
  );
  await userEvent.click(
    screen.getByRole('button', { name: '뉴스·공시 다시 조회' }),
  );
  await screen.findByRole('article', { name: '문서 합성 뉴스 A' });
});
test('evidence failure retries the same selection and snapshot', async () => {
  server.on('GET', '/api/v1/evidence/:id', () =>
    apiError(503, 'SOURCE_UNAVAILABLE'),
  );
  open('&document=doc-a&evidence=ev-a');
  await screen.findByText(/근거 조회 실패/);
  server.on('GET', '/api/v1/evidence/:id', () => json(evidence));
  await userEvent.click(screen.getByRole('button', { name: '근거 다시 조회' }));
  await screen.findByText('상세 합성 근거 인용');
  expect(server.calls('GET', '/api/v1/evidence/:id')).toHaveLength(2);
  expect(
    server.calls('GET', '/api/v1/evidence/:id')[1].query.get('graphVersion'),
  ).toBe('v1');
});
test('permission/unpublished evidence is distinct from retryable outage', async () => {
  server.on('GET', '/api/v1/evidence/:id', () =>
    apiError(403, 'ACCESS_DENIED'),
  );
  open('&document=doc-a&evidence=ev-a');
  await screen.findByText(/공개할 수 없는 자료입니다/);
  expect(screen.queryByRole('button', { name: '근거 다시 조회' })).toBeNull();
  expect(screen.queryByText('상세 합성 근거 인용')).toBeNull();
});
test('version unavailable never retries as unpinned latest', async () => {
  server.on('GET', '/api/v1/evidence/:id', () =>
    apiError(409, 'VERSION_UNAVAILABLE'),
  );
  open('&document=doc-a&evidence=ev-a');
  await screen.findByText(/근거 조회 실패/);
  await userEvent.click(screen.getByRole('button', { name: '근거 다시 조회' }));
  await waitFor(() =>
    expect(server.calls('GET', '/api/v1/evidence/:id')).toHaveLength(2),
  );
  expect(
    server
      .calls('GET', '/api/v1/evidence/:id')
      .every((r) => r.query.get('graphVersion') === 'v1'),
  ).toBe(true);
});
test('null source fields and unsafe URLs display missing information without HTML execution', async () => {
  server.on('GET', '/api/v1/companies/:id/documents', () =>
    json({
      items: [
        {
          ...doc,
          title: '<script>synthetic</script>',
          publisher: null,
          publishedAt: null,
          url: 'javascript:synthetic()',
        },
      ],
      nextCursor: null,
      metadata,
    }),
  );
  open();
  await screen.findByText('<script>synthetic</script>');
  expect(document.querySelector('article script')).toBeNull();
  expect(screen.queryByRole('link', { name: '원문 보기' })).toBeNull();
  expect(screen.getByText(/출처 미제공/)).toBeTruthy();
  expect(screen.getByText('원문을 제공하지 않는 자료입니다')).toBeTruthy();
});
test('future publication and mismatched evidence article are withheld', async () => {
  server.on('GET', '/api/v1/companies/:id/documents', () =>
    json({
      items: [
        doc,
        { ...other, title: '미래 문서', publishedAt: '2026-10-07T03:00:00Z' },
      ],
      nextCursor: null,
      metadata,
    }),
  );
  server.on('GET', '/api/v1/evidence/:id', () =>
    json({ ...evidence, articleId: 'other-article' }),
  );
  open('&document=doc-a&evidence=ev-a');
  await screen.findByText(/일치하지 않는 근거는 표시하지 않았어요/);
  expect(screen.queryByText('미래 문서')).toBeNull();
  expect(screen.queryByText('상세 합성 근거 인용')).toBeNull();
});
test('partial empty response is not declared zero documents', async () => {
  server.on('GET', '/api/v1/companies/:id/documents', () =>
    json({
      items: [],
      nextCursor: null,
      metadata: { ...metadata, partial: true },
    }),
  );
  open();
  await screen.findByText(/일부 문서 자료를 받지 못했어요/);
  expect(screen.queryByText('공개된 뉴스·공시가 없어요.')).toBeNull();
});
test('all cursor pages preserve snapshot and produce distinct counts', async () => {
  server.on('GET', '/api/v1/companies/:id/documents', (r) =>
    json({
      items: r.query.has('cursor') ? [other] : [doc],
      nextCursor: r.query.has('cursor') ? null : 'page2',
      metadata,
    }),
  );
  open();
  await screen.findByText('제공된 근거 문서 2건');
  expect(server.calls('GET', '/api/v1/companies/:id/documents')).toHaveLength(
    2,
  );
  expect(
    server.calls('GET', '/api/v1/companies/:id/documents')[1].query.get('asOf'),
  ).toBe(asOf);
});
test('company/context change discards delayed old evidence immediately', async () => {
  const pending = deferred<Response>();
  server.on('GET', '/api/v1/evidence/:id', (r) =>
    r.query.get('companyId') === companyId
      ? pending.promise
      : json({ ...evidence, quote: '새 기업 근거' }),
  );
  open('&document=doc-a&evidence=ev-a');
  await waitFor(() =>
    expect(server.calls('GET', '/api/v1/evidence/:id')).toHaveLength(1),
  );
  await userEvent.click(screen.getByRole('button', { name: '기업 바꾸기' }));
  await screen.findByText('새 기업 근거');
  await act(async () =>
    pending.resolve(json({ ...evidence, quote: '이전 기업 근거' })),
  );
  expect(screen.queryByText('이전 기업 근거')).toBeNull();
});
test('selected time change hides delayed old evidence and reloads snapshot', async () => {
  const pending = deferred<Response>();
  server.on('GET', '/api/v1/evidence/:id', (r) =>
    r.query.get('asOf') === asOf
      ? pending.promise
      : json({
          ...evidence,
          quote: '선택 시점 근거',
          metadata: { ...metadata, asOf: '2026-10-05T03:00:00Z' },
        }),
  );
  open('&document=doc-a&evidence=ev-a');
  await waitFor(() =>
    expect(server.calls('GET', '/api/v1/evidence/:id')).toHaveLength(1),
  );
  await userEvent.click(screen.getByRole('button', { name: '시점 바꾸기' }));
  await screen.findByText('선택 시점 근거');
  await act(async () =>
    pending.resolve(json({ ...evidence, quote: '예전 시점 근거' })),
  );
  expect(screen.queryByText('예전 시점 근거')).toBeNull();
});
test('other company sentiment is not borrowed and synthetic results are labeled', async () => {
  server.on('GET', '/api/v1/companies/:id/documents', () =>
    json({
      items: [
        {
          ...doc,
          sentiment: {
            companyId: 'OTHER',
            label: 'positive',
            rationale: '다른 기업 긍정',
            quotes: ['다른 기업에 대한 합성 근거'],
            judgedAt: asOf,
            model: 'synthetic',
            promptVersion: 'v1',
          },
          analysisProvenance: {
            sourceKind: 'synthetic',
            executionMode: 'replay',
            recordingKind: 'authored-test',
          },
        },
      ],
      nextCursor: null,
      metadata,
    }),
  );
  open();
  await screen.findByText('조회 기업과 다른 맥락의 판정은 표시하지 않았어요.');
  expect(screen.queryByText(/다른 기업 긍정/)).toBeNull();
  expect(screen.getByText(/합성 테스트 분석입니다/)).toBeTruthy();
});
test('withheld analysis and no quotes are represented without fabricated summary', async () => {
  server.on('GET', '/api/v1/companies/:id/documents', () =>
    json({
      items: [
        {
          ...doc,
          quotes: [],
          analysisStatus: {
            summary: { status: 'withheld', reason: '근거 확인 중' },
            sentiment: { status: 'not_requested', reason: null },
          },
        },
      ],
      nextCursor: null,
      metadata,
    }),
  );
  open();
  await screen.findByText(/문서 요약 공개 보류/);
  await userEvent.click(
    screen.getByRole('button', { name: '문서 근거 선택 · 0건' }),
  );
  await screen.findByText('제공된 근거 인용이 없어요.');
  expect(screen.queryByText('제공된 합성 인용 A')).toBeNull();
});

test('evidence for another event is withheld in selected-event scope', async () => {
  server.on('GET', '/api/v1/evidence/:id', () =>
    json({ ...evidence, eventIds: ['issue-b'] }),
  );
  open('&event=issue-a&docScope=event&document=doc-a&evidence=ev-a');
  await screen.findByText(/일치하지 않는 근거는 표시하지 않았어요/);
  expect(screen.queryByText('상세 합성 근거 인용')).toBeNull();
});
test('evidence for a future publication is withheld even when requested directly', async () => {
  server.on('GET', '/api/v1/evidence/:id', () =>
    json({
      ...evidence,
      article: { ...evidence.article, publishedAt: '2026-10-07T03:00:00Z' },
    }),
  );
  open('&evidence=ev-a');
  await screen.findByText(/일치하지 않는 근거는 표시하지 않았어요/);
  expect(screen.queryByText('상세 합성 근거 인용')).toBeNull();
});

test('HTTP403 with an unfamiliar error code remains a permission denial', async () => {
  server.on('GET', '/api/v1/evidence/:id', () =>
    apiError(403, 'NEW_PERMISSION_CODE'),
  );
  open('&document=doc-a&evidence=ev-a');
  await screen.findByText(/공개할 수 없는 자료입니다/);
  expect(screen.queryByRole('button', { name: '근거 다시 조회' })).toBeNull();
});
test('direct evidence URL cannot expose an article absent from this company list', async () => {
  server.on('GET', '/api/v1/evidence/:id', () =>
    json({ ...evidence, articleId: 'unrelated-article' }),
  );
  open('&evidence=ev-a');
  await screen.findByText(/선택 기업·문서·사건·시점과 일치하지 않는 근거/);
  expect(screen.queryByText('상세 합성 근거 인용')).toBeNull();
});
test('direct evidence must be an exposed quote of its document', async () => {
  server.on('GET', '/api/v1/evidence/:id', () =>
    json({ ...evidence, id: 'unlisted-evidence' }),
  );
  open('&evidence=unlisted-evidence');
  await screen.findByText(/선택 기업·문서·사건·시점과 일치하지 않는 근거/);
  expect(screen.queryByText('상세 합성 근거 인용')).toBeNull();
});

test('later cursor partial failure is retained and retry keeps the pinned snapshot', async () => {
  server.on('GET', '/api/v1/companies/:id/documents', (request) =>
    json({
      items: request.query.has('cursor') ? [other] : [doc],
      nextCursor: request.query.has('cursor') ? null : 'next',
      metadata: { ...metadata, partial: request.query.has('cursor') },
    }),
  );
  open();
  await screen.findByText(/일부 문서 자료를 받지 못했어요/);
  await userEvent
    .setup()
    .click(screen.getByRole('button', { name: '뉴스·공시 다시 조회' }));
  await waitFor(() =>
    expect(server.calls('GET', '/api/v1/companies/:id/documents').length).toBe(
      4,
    ),
  );
  expect(
    server.requests.every(
      (request) => request.query.get('graphVersion') === 'v1',
    ),
  ).toBe(true);
});

test('evidence from a different public snapshot is withheld despite matching IDs', async () => {
  server.on('GET', '/api/v1/evidence/:id', () =>
    json({
      ...evidence,
      metadata: { ...metadata, asOf: '2026-10-04T03:00:00Z' },
    }),
  );
  open('&document=doc-a&evidence=ev-a');
  await screen.findByText(/선택 기업·문서·사건·시점과 일치하지 않는 근거/);
  expect(screen.queryByText('상세 합성 근거 인용')).toBeNull();
});

test('equivalent snapshot offsets remain the same public instant', async () => {
  server.on('GET', '/api/v1/evidence/:id', () =>
    json({
      ...evidence,
      metadata: { ...metadata, asOf: '2026-10-06T12:00:00+09:00' },
    }),
  );
  open('&document=doc-a&evidence=ev-a');
  await screen.findByText('상세 합성 근거 인용');
});

test('early evidence waits for its document list without a false mismatch error', async () => {
  const pending = deferred<Response>();
  server.on('GET', '/api/v1/companies/:id/documents', () => pending.promise);
  open('&document=doc-a&evidence=ev-a');
  await screen.findByText('근거의 문서 소속을 확인하고 있어요.');
  expect(
    screen.queryByText(/일치하지 않는 근거는 표시하지 않았어요/),
  ).toBeNull();
  expect(screen.queryByText('상세 합성 근거 인용')).toBeNull();
  await act(async () =>
    pending.resolve(json({ items: [doc], nextCursor: null, metadata })),
  );
  await screen.findByText('상세 합성 근거 인용');
});

test('D-COM-01 N-k shows document and judgment times in KST with the shared undetermined label', async () => {
  server.on('GET', '/api/v1/companies/:id/documents', () =>
    json({
      items: [
        {
          ...doc,
          sentiment: {
            companyId,
            label: 'undetermined',
            rationale: '합성 판정 보류 근거',
            quotes: ['합성 근거'],
            judgedAt: asOf,
            model: 'synthetic',
            promptVersion: 'v1',
          },
        },
      ],
      nextCursor: null,
      metadata,
    }),
  );
  open();
  const judged = await screen.findByText(/합성 판정 보류 근거/);
  expect(judged.textContent).toContain('판단 보류');
  expect(judged.textContent).not.toContain('판단 유보');
  expect(judged.textContent).toContain('판정 시각 2026-10-06 12:00 KST');
  expect(screen.getAllByText(/2026-10-05 12:00 KST/).length).toBeGreaterThan(0);
  expect(screen.queryByText(/2026-10-05T03:00:00Z/)).toBeNull();
});
