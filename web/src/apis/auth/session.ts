import { call } from './ApiService';
import { API_BASE_URL } from './api-config';
import type { LoginRequest, Session } from '@/types/auth';

// D-AUT-01 인증 API (docs/api/openapi.yaml). 응답은 ApiResponse로 감싸지 않은 SessionResponse다.
// metadata는 화면에서 쓰지 않아 생략한다.

export type SocialProviderId = 'google' | 'kakao';

/** getMemberSession: 지금 쿠키의 세션(회원·비회원·없음)과 초기 설정 상태 */
export function getSession() {
  return call<Session>('/api/v1/auth/session', 'GET', undefined, {
    skipAuth: true,
  });
}

/** logIn: 성공하면 서버가 회원 세션 쿠키를 발급한다. 실패는 401 INVALID_CREDENTIALS 등 */
export function logIn(request: LoginRequest) {
  return call<Session>('/api/v1/auth/login', 'POST', request, {
    skipAuth: true,
  });
}

/** startGuestSession: 비회원 세션을 시작한다. */
export function startGuestSession() {
  return call<Session>('/api/v1/auth/guest', 'POST', undefined, {
    skipAuth: true,
  });
}

/** logOut: 회원 세션을 폐기한다. 세션이 없어도 204다. */
export function logOut() {
  return call<void>('/api/v1/auth/logout', 'POST', undefined, {
    skipAuth: true,
  });
}

/** authorizeSocialLogin은 302로 제공자 인증 화면에 보내므로 fetch가 아니라 페이지 이동으로 시작한다. */
export function socialLoginUrl(provider: SocialProviderId, returnTo: string) {
  const query = new URLSearchParams({ returnTo });
  return `${API_BASE_URL}/api/v1/auth/social/${provider}/authorize?${query}`;
}

import type { SignupBody, SignupTerm } from '@/types/auth/session';
import { ApiError } from './ApiService';
export const signUp = (body: SignupBody) =>
  call<Session>('/api/v1/auth/signup', 'POST', body, { skipAuth: true });
export async function listSignupTerms(): Promise<SignupTerm[]> {
  const terms: SignupTerm[] = [];
  const seen = new Set<string>();
  let cursor: string | null = null;
  do {
    const page: { items: SignupTerm[]; nextCursor: string | null } = await call(
      `/api/v1/auth/terms${cursor ? `?${new URLSearchParams({ cursor })}` : ''}`,
      'GET',
      undefined,
      { skipAuth: true },
    );
    terms.push(...page.items);
    cursor = page.nextCursor;
    if (cursor && seen.has(cursor))
      throw new ApiError(200, 'INVALID_TERMS', '약관을 확인하지 못했어요.');
    if (cursor) seen.add(cursor);
  } while (cursor);
  if (new Set(terms.map((t) => t.id)).size !== terms.length)
    throw new ApiError(200, 'INVALID_TERMS', '약관을 확인하지 못했어요.');
  return terms;
}

export type SocialProvider = { id: SocialProviderId; name: string };

/** listSocialProviders: 서버에 설정된 소셜 로그인 제공자. 설정되지 않은 제공자는 버튼을 두지 않는다. */
export function listSocialProviders() {
  return call<{ items: SocialProvider[]; nextCursor: string | null }>(
    '/api/v1/auth/social/providers',
    'GET',
    undefined,
    { skipAuth: true },
  );
}

/**
 * completeSocialSignup: 소셜 콜백이 검증해 둔 신규 인증(zoop_oauth_pending 쿠키)으로 가입을 마친다.
 * 이메일·제공자는 서버가 보관한 값만 쓰고, 화면은 표시 이름과 약관 동의만 보낸다.
 * 201이면 회원 세션 쿠키가 발급된다. 403은 인증 만료·없음, 409 SOCIAL_LINK_REQUIRED는 같은 이메일 계정이 이미 있음.
 */
export function completeSocialSignup(body: {
  displayName?: string;
  agreements: { id: string; version: string; accepted: boolean }[];
}) {
  return call<Session>('/api/v1/auth/social/signup', 'POST', body, {
    skipAuth: true,
  });
}
