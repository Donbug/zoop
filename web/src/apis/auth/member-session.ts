import { useAuthStore } from '@/stores/useAuthStore';
import { ApiError, call } from './ApiService';
import { getSession } from './session';
import type { MemberSession } from '@/types/auth/session';

export function isMemberSession(
  session: MemberSession | null,
): session is MemberSession & {
  user: NonNullable<MemberSession['user']>;
  setup: NonNullable<MemberSession['setup']>;
} {
  return Boolean(
    session?.authenticated &&
    session.kind === 'member' &&
    session.user?.id &&
    session.user.email &&
    session.setup &&
    typeof session.setup.completed === 'boolean',
  );
}
export function acceptMemberSession(session: MemberSession) {
  if (
    typeof session.authenticated !== 'boolean' ||
    !['anonymous', 'guest', 'member'].includes(session.kind) ||
    (session.kind === 'member' && !isMemberSession(session))
  )
    throw new ApiError(
      200,
      'INVALID_SESSION',
      '세션 응답을 확인하지 못했어요.',
    );
  useAuthStore.getState().setSession(session);
}
let pending: {
  revision: number;
  promise: Promise<MemberSession | null>;
} | null = null;
export function loadSession(force = false): Promise<MemberSession | null> {
  const state = useAuthStore.getState();
  if (!force && state.status === 'ready') return Promise.resolve(state.session);
  if (pending?.revision === state.sessionRevision) return pending.promise;
  const revision = state.sessionRevision;
  useAuthStore.setState({ status: 'checking' });
  const promise = getSession()
    .then((session) => {
      if (useAuthStore.getState().sessionRevision !== revision)
        throw new ApiError(0, 'SESSION_CHANGED', '계정이 변경되었어요.');
      acceptMemberSession(session);
      return session;
    })
    .catch((error) => {
      if (useAuthStore.getState().sessionRevision === revision)
        useAuthStore.setState({ status: 'error' });
      throw error;
    })
    .finally(() => {
      if (pending?.promise === promise) pending = null;
    });
  pending = { revision, promise };
  return promise;
}
/** FS006: an unknown/failed portfolio response is never interpreted as zero holdings. */
export async function memberDestination(
  session: MemberSession,
): Promise<string> {
  if (!isMemberSession(session))
    throw new ApiError(
      401,
      'MEMBER_SESSION_REQUIRED',
      '회원 로그인이 필요해요.',
    );
  if (!session.setup.completed) return '/onboarding';
  const revision = useAuthStore.getState().sessionRevision;
  const [settings, portfolio] = await Promise.all([
    call<{
      watchlistIds: string[];
      metadata?: { partial?: boolean };
    }>('/api/v1/me/settings', 'GET'),
    call<{ holdings: unknown[]; metadata?: { partial?: boolean } }>(
      '/api/v1/portfolio',
      'GET',
    ),
  ]);
  if (revision !== useAuthStore.getState().sessionRevision)
    throw new ApiError(0, 'SESSION_CHANGED', '계정이 변경되었어요.');
  if (
    !Array.isArray(settings.watchlistIds) ||
    !Array.isArray(portfolio.holdings) ||
    settings.metadata?.partial ||
    portfolio.metadata?.partial
  )
    throw new ApiError(
      503,
      'INCOMPLETE_PERSONAL_DATA',
      '종목을 확인하지 못했어요.',
    );
  return settings.watchlistIds.length || portfolio.holdings.length
    ? '/?mode=personal'
    : '/?mode=all';
}
