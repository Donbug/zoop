import type { MemberSettings } from '@/types/settings';

export const metadata = {
  source: 'test',
  asOf: '2026-10-12T00:00:00Z',
  graphVersion: null,
  requestId: 'req-test',
  partial: false,
  failures: [],
};

/** SettingsResponse 본문(목표 계약 그대로, ApiResponse 래퍼 없음) */
export function settingsBody(overrides: Partial<MemberSettings> = {}) {
  return {
    mode: 'watchlist',
    watchlistIds: [],
    tutorialCompleted: false,
    completed: false,
    investor: null,
    version: 1,
    ...overrides,
    metadata,
  };
}
