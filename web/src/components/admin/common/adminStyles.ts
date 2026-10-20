import { ApiError } from '@/apis/auth/ApiService';

// 관리자 화면의 공통 Tailwind 클래스 묶음과 표기. 색은 @theme zoop 토큰만 쓴다.

export const FOCUS_RING =
  'focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-zoop-ink';
export const BUTTON = `h-8 shrink-0 rounded-[3px] border-[0.667px] border-zoop-line bg-zoop-paper px-3 text-xs font-semibold text-zoop-ink hover:bg-zoop-wash disabled:opacity-60 ${FOCUS_RING}`;
export const TH =
  'border-b-[0.667px] border-zoop-line px-2 py-2 text-left text-[11px] font-medium text-zoop-muted';
export const TD = 'border-b-[0.667px] border-zoop-line px-2 py-2.5 text-xs';
export const LINK = `text-xs font-semibold text-zoop-ink underline underline-offset-4 ${FOCUS_RING}`;

export const count = (value: number) => value.toLocaleString('ko-KR');

const percent = new Intl.NumberFormat('ko-KR', {
  style: 'percent',
  maximumFractionDigits: 1,
});
/** 0..1 비율을 '40.5%'로 */
export const formatPercent = (rate: number) => percent.format(rate);

/** 관리자 조회 실패 문구. 401은 AdminProtectedRoute가 로그인으로 보내므로 따로 다루지 않는다. */
export function adminErrorMessage(error: Error) {
  if (error instanceof ApiError) {
    if (error.status === 403 || error.code === 'ACCESS_DENIED')
      return '이 화면을 볼 권한이 없어요. 관리자 권한을 확인해 주세요.';
    if (error.code === 'MASKING_FAILED')
      return '개인정보 가림 처리에 실패했어요. 잠시 후 다시 시도해 주세요.';
    if (error.code === 'AUDIT_UNAVAILABLE')
      return '감사 로그 서버에 연결하지 못했어요. 잠시 후 다시 시도해 주세요.';
    if (error.code === 'SOURCE_UNAVAILABLE' || error.status === 503)
      return '집계 서버에 연결하지 못했어요.';
    if (error.status === 422 || error.code === 'INVALID_REQUEST')
      return '조회 조건을 확인해 주세요.';
  }
  return '잠시 후 다시 시도해 주세요.';
}
