import { act, render, screen, waitFor, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { beforeEach, expect, test } from 'vitest';
import {
  MemoryRouter,
  Route,
  Routes,
  useLocation,
  useNavigate,
  useParams,
  useSearchParams,
} from 'react-router-dom';
import CompanyInfoTab from '@/components/company/CompanyInfoTab';
import { useCompanyResource } from '@/hooks/useCompanyResource';
import { companyUrl } from '@/apis/company/company';
import type { Company } from '@/types/company/detail';
import {
  createFakeServer,
  json,
  apiError,
  deferred,
} from './support/fakeServer';
const asOf = '2026-10-05T00:00:00Z';
const company: Company = {
  id: 'fixture-a',
  name: '표시용 가상 기업',
  ticker: null,
  legalName: '가상 법인 정식 명칭',
  market: '가상 시장',
  sector: '가상 업종',
  representative: '가상 대표',
  foundedDate: '2000-02-29',
  websiteUrl: 'https://example.test/company',
  directIssues: [],
  structuralIssues: [],
  summary: null,
  metadata: {
    source: '합성 API',
    asOf,
    graphVersion: 'fixture-v1',
    partial: false,
  },
};
let server: ReturnType<typeof createFakeServer>;
beforeEach(() => {
  server = createFakeServer();
  server.on('GET', '/api/v1/companies/:id', () => json(company));
});
function Harness() {
  const { id = '' } = useParams();
  const [params] = useSearchParams();
  const navigate = useNavigate();
  const location = useLocation();
  const resource = useCompanyResource<Company>(
    companyUrl(id, '', {
      asOf: params.get('asOf'),
      graphVersion: params.get('graphVersion'),
    }),
  );
  return (
    <>
      <CompanyInfoTab resource={resource} />
      <output data-testid="info-url">
        {location.pathname}
        {location.search}
      </output>
      <button
        onClick={() => navigate(`/companies/fixture-b${location.search}`)}
      >
        기업 전환
      </button>
      <button
        onClick={() =>
          navigate(
            `/companies/${id}?asOf=2026-10-06T00%3A00%3A00Z&graphVersion=fixture-v1`,
          )
        }
      >
        시점 전환
      </button>
    </>
  );
}
function open() {
  return render(
    <MemoryRouter
      initialEntries={[
        `/companies/fixture-a?tab=info&period=1w&event=fixture-event&asOf=${encodeURIComponent(asOf)}&graphVersion=fixture-v1`,
      ]}
    >
      <Routes>
        <Route path="/companies/:id" element={<Harness />} />
      </Routes>
    </MemoryRouter>,
  );
}
test('D-COM-03 renders six verified fields and safe website without guessing master timestamps', async () => {
  open();
  await screen.findByText('가상 법인 정식 명칭');
  for (const value of ['가상 시장', '가상 업종', '가상 대표', '2000-02-29'])
    expect(screen.getByText(value)).toBeTruthy();
  const link = screen.getByRole('link', { name: '공식 웹사이트' });
  expect(link.getAttribute('href')).toBe('https://example.test/company');
  expect(link.getAttribute('rel')).toContain('noopener');
  expect(
    screen.getByText(/기업 기준정보의 별도 갱신 시각은 제공되지/),
  ).toBeTruthy();
  expect(server.requests[0].query.get('graphVersion')).toBe('fixture-v1');
  expect(server.requests[0].query.get('asOf')).toBe(asOf);
  expect(screen.getByTestId('info-url').textContent).toContain('tab=info');
});
test('null/blank fields remain missing, never copied from the display name', async () => {
  server.on('GET', '/api/v1/companies/:id', () =>
    json({
      ...company,
      legalName: null,
      market: null,
      sector: null,
      representative: ' ',
      foundedDate: null,
      websiteUrl: null,
    }),
  );
  open();
  await screen.findByText('확인된 기업 기준정보가 없습니다.');
  expect(screen.getAllByText('미제공')).toHaveLength(6);
  expect(screen.queryByText(company.name)).toBeNull();
});
test.each([
  'javascript:alert(1)',
  '/company',
  'https://',
  'https://user:password@example.test',
])('unsafe or invalid homepage %s is never linked', async (websiteUrl) => {
  server.on('GET', '/api/v1/companies/:id', () =>
    json({ ...company, websiteUrl }),
  );
  open();
  await screen.findByText(company.legalName!);
  expect(screen.queryByRole('link', { name: '공식 웹사이트' })).toBeNull();
});
test('loading and network failure recover at the same snapshot', async () => {
  const pending = deferred<Response>();
  server.on('GET', '/api/v1/companies/:id', () => pending.promise);
  open();
  expect(screen.getByText('기업 기준정보를 불러오고 있어요.')).toBeTruthy();
  await act(async () => pending.resolve(apiError(503, 'TEMPORARY')));
  await screen.findByText('기업 기준정보를 불러오지 못했어요.');
  server.on('GET', '/api/v1/companies/:id', () => json(company));
  await userEvent
    .setup()
    .click(screen.getByRole('button', { name: '기업 기준정보 다시 조회' }));
  await screen.findByText(company.legalName!);
  expect(server.requests.at(-1)?.query.get('graphVersion')).toBe('fixture-v1');
});
test('permission denial is distinct from a retryable network outage', async () => {
  server.on('GET', '/api/v1/companies/:id', () =>
    apiError(403, 'UNFAMILIAR_PERMISSION'),
  );
  open();
  await screen.findByText('기업 기준정보를 조회할 권한이 없어요.');
  expect(
    screen.queryByRole('button', { name: '기업 기준정보 다시 조회' }),
  ).toBeNull();
});
test('missing company and unavailable public version are explicit and offer no retry', async () => {
  server.on('GET', '/api/v1/companies/:id', () => apiError(404, 'NOT_FOUND'));
  const missing = open();
  await screen.findByText('기업 기준정보를 찾을 수 없어요.');
  expect(
    screen.queryByRole('button', { name: '기업 기준정보 다시 조회' }),
  ).toBeNull();
  missing.unmount();

  server.on('GET', '/api/v1/companies/:id', () =>
    json({
      ...company,
      metadata: { ...company.metadata, graphVersion: 'other' },
    }),
  );
  open();
  await screen.findByText(
    /선택한 공개 버전의 기업 기준정보를 확인할 수 없어요/,
  );
  expect(
    screen.queryByRole('button', { name: '기업 기준정보 다시 조회' }),
  ).toBeNull();
  expect(screen.queryByText(company.legalName!)).toBeNull();
});

test('F05: a non-retryable provider failure explains itself without retry', async () => {
  server.on('GET', '/api/v1/companies/:id', () =>
    json(
      {
        error: {
          code: 'SOURCE_UNAVAILABLE',
          message: '공급자 인증 실패',
          retryable: false,
        },
      },
      503,
    ),
  );
  open();
  await screen.findByText(/자료 공급원의 설정이나 응답 형식 문제/);
  expect(
    screen.queryByRole('button', { name: '기업 기준정보 다시 조회' }),
  ).toBeNull();
});
test('partial information retains available fields and permits retry', async () => {
  server.on('GET', '/api/v1/companies/:id', () =>
    json({
      ...company,
      market: null,
      metadata: {
        ...company.metadata,
        partial: true,
        failures: [
          { section: 'profile', code: 'PARTIAL', message: '합성 누락 사유' },
        ],
      },
    }),
  );
  open();
  await screen.findByText('합성 누락 사유');
  expect(screen.getByText(company.legalName!)).toBeTruthy();
  expect(
    screen.getByRole('button', { name: '기업 기준정보 다시 조회' }),
  ).toBeTruthy();
});
test.each(['기업 전환', '시점 전환'])(
  '%s hides old profile while pending and ignores old response',
  async (action) => {
    open();
    await screen.findByText(company.legalName!);
    const pending = deferred<Response>();
    server.on('GET', '/api/v1/companies/:id', () => pending.promise);
    await userEvent.setup().click(screen.getByRole('button', { name: action }));
    expect(screen.queryByText(company.legalName!)).toBeNull();
    await waitFor(() => expect(server.requests.length).toBe(2));
    await act(async () =>
      pending.resolve(
        json({
          ...company,
          id: action === '기업 전환' ? 'fixture-b' : company.id,
          legalName: '새 기준 가상 법인',
        }),
      ),
    );
    await screen.findByText('새 기준 가상 법인');
    const region = screen.getByRole('region', { name: '기업 기준정보' });
    expect(within(region).queryByText(company.legalName!)).toBeNull();
  },
);

test('a response for another company is rejected rather than rendered as the requested profile', async () => {
  server.on('GET', '/api/v1/companies/:id', () =>
    json({
      ...company,
      id: 'unrelated-company',
      legalName: '다른 기업 비공개 예시',
    }),
  );
  open();
  await screen.findByText('기업 기준정보를 불러오지 못했어요.');
  expect(screen.queryByText('다른 기업 비공개 예시')).toBeNull();
});

test('a late old-company response cannot overwrite the newly selected company', async () => {
  const pending = deferred<Response>();
  server.on('GET', '/api/v1/companies/:id', ({ params }) =>
    params.id === 'fixture-a'
      ? pending.promise
      : json({ ...company, id: 'fixture-b', legalName: '새 기업 법인명' }),
  );
  open();
  await waitFor(() => expect(server.requests).toHaveLength(1));
  await userEvent.click(screen.getByRole('button', { name: '기업 전환' }));
  await screen.findByText('새 기업 법인명');
  await act(async () => pending.resolve(json(company)));
  expect(screen.queryByText(company.legalName!)).toBeNull();
  expect(screen.getByText('새 기업 법인명')).toBeTruthy();
});
