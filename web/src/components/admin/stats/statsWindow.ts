import type { StatsWindow } from '@/types/admin/insights';

// 통계·선호도 화면의 집계 기간(7일·30일·전체). 주소의 window 값을 읽는다.

export const windowOptions: { value: StatsWindow; label: string }[] = [
  { value: '7d', label: '7일' },
  { value: '30d', label: '30일' },
  { value: 'all', label: '전체' },
];

export function parseWindow(
  value: string | null,
  fallback: StatsWindow = '7d',
): StatsWindow {
  return value === '7d' || value === '30d' || value === 'all'
    ? value
    : fallback;
}
