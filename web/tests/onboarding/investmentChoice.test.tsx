import { screen, waitFor } from '@testing-library/react';
import { describe, expect, test } from 'vitest';
import InvestmentStatusPage from '@/pages/onboarding/investment/InvestmentStatusPage';
import { settingsBody } from '../support/fixtures';
import {
  apiError,
  createFakeServer,
  deferred,
  json,
  type FakeServer,
} from '../support/fakeServer';
import { renderRoutes } from '../support/renderRoutes';

const SETTINGS = '/api/v1/me/settings';

function openInvestment() {
  return renderRoutes(
    [{ path: '/onboarding', element: <InvestmentStatusPage /> }],
    '/onboarding',
  );
}

function acceptSave(server: FakeServer) {
  server.on('PUT', SETTINGS, ({ body }) => {
    const update = body as { version: number; investor: boolean };
    return json(
      settingsBody({ investor: update.investor, version: update.version + 1 }),
    );
  });
}

const investingButton = () =>
  screen.findByRole('button', { name: /지금 주식에 투자하고 있어요/ });
const notInvestingButton = () =>
  screen.findByRole('button', { name: /아직 투자하지 않아요/ });

describe('D-ONB-01 투자 여부 선택', () => {
  test('투자 중을 고르면 investor를 저장하고 가상 계좌 연결로 간다', async () => {
    const server = createFakeServer();
    server.on('GET', SETTINGS, () => json(settingsBody()));
    acceptSave(server);
    const { user, location } = openInvestment();

    await user.click(await investingButton());

    await waitFor(() => expect(location()).toBe('/onboarding/account'));
    expect(server.calls('PUT', SETTINGS)[0].body).toEqual({
      version: 1,
      investor: true,
    });
  });

  test('투자하지 않음을 고르면 관심 종목 선택으로 간다', async () => {
    const server = createFakeServer();
    server.on('GET', SETTINGS, () => json(settingsBody()));
    acceptSave(server);
    const { user, location } = openInvestment();

    await user.click(await notInvestingButton());

    await waitFor(() => expect(location()).toBe('/onboarding/watchlist'));
    expect(server.calls('PUT', SETTINGS)[0].body).toEqual({
      version: 1,
      investor: false,
    });
  });

  test('저장된 답이 있으면 그 답을 고른 상태로 보여 준다', async () => {
    const server = createFakeServer();
    server.on('GET', SETTINGS, () => json(settingsBody({ investor: false })));
    openInvestment();

    expect((await notInvestingButton()).getAttribute('aria-pressed')).toBe(
      'true',
    );
    expect((await investingButton()).getAttribute('aria-pressed')).toBe(
      'false',
    );
  });

  test('저장 중에는 안내를 보이고 다시 고르지 못하게 막는다', async () => {
    const server = createFakeServer();
    server.on('GET', SETTINGS, () => json(settingsBody()));
    const response = deferred<Response>();
    server.on('PUT', SETTINGS, () => response.promise);
    const { user, location } = openInvestment();

    await user.click(await investingButton());

    expect(await screen.findByText('선택을 저장하고 있어요')).toBeTruthy();
    expect((await investingButton()).hasAttribute('disabled')).toBe(true);
    expect((await notInvestingButton()).hasAttribute('disabled')).toBe(true);
    await user.click(await notInvestingButton());
    expect(server.calls('PUT', SETTINGS)).toHaveLength(1);

    response.resolve(json(settingsBody({ investor: true, version: 2 })));
    await waitFor(() => expect(location()).toBe('/onboarding/account'));
  });

  test('저장에 실패하면 머물러 고른 답을 두고, 다시 시도해 성공하면 이동한다', async () => {
    const server = createFakeServer();
    let stored = settingsBody();
    server.on('GET', SETTINGS, () => json(stored));
    server.on('PUT', SETTINGS, () => {
      // 다른 곳에서 먼저 저장해 버전이 올라간 상황
      stored = settingsBody({ version: 2 });
      return apiError(409, 'version_conflict');
    });
    const { user, location } = openInvestment();

    await user.click(await notInvestingButton());

    const alert = await screen.findByRole('alert');
    expect(alert.textContent).toContain('선택을 저장하지 못했어요');
    expect(location()).toBe('/onboarding');
    expect((await notInvestingButton()).getAttribute('aria-pressed')).toBe(
      'true',
    );

    acceptSave(server);
    // 실패 뒤 최신 설정(version)을 다시 읽어 둔다.
    await waitFor(() => expect(server.calls('GET', SETTINGS)).toHaveLength(2));
    await user.click(screen.getByRole('button', { name: '다시 시도' }));

    await waitFor(() => expect(location()).toBe('/onboarding/watchlist'));
    const puts = server.calls('PUT', SETTINGS);
    expect(puts).toHaveLength(2);
    expect(puts[1].body).toEqual({ version: 2, investor: false });
  });

  test('설정을 불러오지 못하면 안내하고, 다시 시도해 성공하면 고를 수 있다', async () => {
    const server = createFakeServer();
    server.on('GET', SETTINGS, () => apiError(503, 'SOURCE_UNAVAILABLE'));
    const { user } = openInvestment();

    expect((await screen.findByRole('alert')).textContent).toContain(
      '설정을 불러오지 못했어요',
    );
    expect(screen.queryByRole('button', { name: /투자/ })).toBeNull();

    server.on('GET', SETTINGS, () => json(settingsBody()));
    await user.click(screen.getByRole('button', { name: '다시 시도' }));

    expect(await investingButton()).toBeTruthy();
  });
});
