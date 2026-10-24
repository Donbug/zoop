import { useEffect, useRef, useState } from 'react';
import { useAuthStore } from '@/stores/useAuthStore';
import { useNavigate } from 'react-router-dom';
import {
  acceptMemberSession,
  isMemberSession,
  loadSession,
  memberDestination,
} from '@/apis/auth/member-session';
import { ApiError } from '@/apis/auth/ApiService';
import type { MemberSession } from '@/types/auth/session';

/**
 * 로그인 뒤 돌아갈 주소. 지도는 D-AUT-01대로 시장 전체 지도에서 시작하므로, 지도 주소는
 * 시장 전체(mode 생략 또는 mode=all)일 때만 그대로 돌아간다(예: 기업 패널의 '로그인 후 관심 추가'). 그 밖의 지도 주소는 기본 도착지로 보낸다.
 */
function returnPath(from: string | null | undefined) {
  if (!from || from === '/') return null;
  if (!from.startsWith('/?')) return from;
  const mode = new URLSearchParams(from.slice(2)).get('mode');
  return mode === null || mode === 'all' ? from : null;
}

export function useAuthCompletion() {
  const navigate = useNavigate();
  const active = useRef(true);
  const locked = useRef(false);
  const [busy, setBusy] = useState(false);
  const [recovering, setRecovering] = useState(false);
  const [error, setError] = useState<string | null>(null);
  useEffect(() => {
    active.current = true;
    return () => {
      active.current = false;
    };
  }, []);
  async function run(
    request?: () => Promise<MemberSession>,
    expectedEmail?: string,
    from?: string | null,
  ) {
    if (locked.current) return;
    locked.current = true;
    setBusy(true);
    setError(null);
    let created = !request;
    const revision = useAuthStore.getState().sessionRevision;
    try {
      if (request) {
        const response = await request();
        created = true;
        if (!active.current) return;
        if (revision !== useAuthStore.getState().sessionRevision)
          throw new ApiError(0, 'SESSION_CHANGED', '계정이 변경되었어요.');
        acceptMemberSession(response);
      }
      const verified = await loadSession(true);
      if (!active.current) return;
      if (
        !isMemberSession(verified) ||
        (expectedEmail &&
          verified.user.email.toLowerCase() !== expectedEmail.toLowerCase())
      )
        throw new ApiError(
          401,
          'MEMBER_SESSION_REQUIRED',
          '회원 로그인이 필요해요.',
        );
      const confirmedRevision = useAuthStore.getState().sessionRevision;
      const destination = await memberDestination(verified);
      if (confirmedRevision !== useAuthStore.getState().sessionRevision)
        throw new ApiError(0, 'SESSION_CHANGED', '계정이 변경되었어요.');
      if (active.current)
        navigate(
          (verified.setup.completed && returnPath(from)) || destination,
          { replace: true },
        );
    } catch (e) {
      if (!active.current) return;
      const code = e instanceof ApiError ? e.code : 'REQUEST_FAILED';
      const uncertain =
        request &&
        e instanceof ApiError &&
        (e.status === 0 || (e.status >= 200 && e.status < 300));
      setRecovering(Boolean(created || uncertain));
      setError(
        created || uncertain
          ? '계정 상태와 이동할 화면을 확인하지 못했어요. 다시 확인해 주세요.'
          : code,
      );
    } finally {
      locked.current = false;
      if (active.current) setBusy(false);
    }
  }
  return { busy, recovering, error, run };
}
