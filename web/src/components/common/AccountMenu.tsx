import { useEffect, useId, useRef, useState } from 'react';
import { Link, useLocation, useNavigate } from 'react-router-dom';
import { logout } from '@/apis/auth/auth';
import { ApiError, call } from '@/apis/auth/ApiService';
import GraphIcon from '@/components/graph/GraphIcon';
import { useAuth } from '@/hooks/useAuth';
import { useAuthStore } from '@/stores/useAuthStore';
import type { Member } from '@/types/auth';

// D-GRP-01 / D-MY-01 common header · account menu (user decision 2026-10-17).
export default function AccountMenu() {
  const auth = useAuth();
  const revision = useAuthStore((s) => s.sessionRevision);
  if (!auth.isAuthenticated || !auth.member)
    return (
      <Link
        to="/login"
        className="relationship-user min-h-11 min-w-11 justify-center"
        aria-label={auth.isGuest ? '비회원 체험 중 · 로그인' : '로그인'}
        title="로그인"
      >
        <span>
          <GraphIcon name="user" />
        </span>
        {auth.isGuest ? '비회원 체험 중 · 로그인' : '로그인'}
      </Link>
    );
  return (
    <MemberAccountMenu
      key={`${auth.member.id}:${revision}`}
      member={auth.member}
      revision={revision}
    />
  );
}

function MemberAccountMenu({
  member,
  revision,
}: {
  member: Member;
  revision: number;
}) {
  const navigate = useNavigate();
  const location = useLocation();
  const root = useRef<HTMLDivElement>(null);
  const trigger = useRef<HTMLButtonElement>(null);
  const action = useRef<HTMLButtonElement>(null);
  const active = useRef(true);
  const locked = useRef(false);
  const [open, setOpen] = useState(false);
  const [pending, setPending] = useState(false);
  const [linking, setLinking] = useState(false);
  const [failed, setFailed] = useState(false);
  const [linkError, setLinkError] = useState<string | null>(null);
  const socialResult = new URLSearchParams(location.search).get('social');
  const menuId = useId();
  const tooltipId = useId();
  useEffect(() => {
    active.current = true;
    return () => {
      active.current = false;
    };
  }, []);
  useEffect(() => {
    if (!open) return;
    action.current?.focus();
    function outside(event: PointerEvent) {
      if (event.target instanceof Node && !root.current?.contains(event.target))
        setOpen(false);
    }
    document.addEventListener('pointerdown', outside);
    return () => document.removeEventListener('pointerdown', outside);
  }, [open, pending]);

  async function signOut() {
    if (locked.current || useAuthStore.getState().sessionRevision !== revision)
      return;
    locked.current = true;
    setPending(true);
    setFailed(false);
    try {
      await logout();
      // Only this logout's cleared session may navigate. A new member keeps their page.
      const current = useAuthStore.getState();
      if (current.sessionRevision === revision + 1 && !current.session)
        navigate('/login', { replace: true });
    } catch {
      if (
        active.current &&
        useAuthStore.getState().sessionRevision === revision
      )
        setFailed(true);
    } finally {
      locked.current = false;
      if (active.current) setPending(false);
    }
  }
  async function linkSocial(provider: 'google' | 'kakao') {
    if (locked.current || useAuthStore.getState().sessionRevision !== revision)
      return;
    locked.current = true;
    setPending(true);
    setLinking(true);
    setLinkError(null);
    try {
      const result = await call<{ authorizationUrl: string }>(
        `/api/v1/auth/social/${provider}/link/authorize`,
        'POST',
        { returnTo: '/' },
      );
      if (useAuthStore.getState().sessionRevision !== revision) return;
      const url = new URL(result.authorizationUrl);
      const host =
        provider === 'google' ? 'accounts.google.com' : 'kauth.kakao.com';
      if (url.protocol !== 'https:' || url.hostname !== host)
        throw new Error('Invalid authorization URL');
      window.location.assign(url.href);
    } catch (error) {
      if (
        active.current &&
        useAuthStore.getState().sessionRevision === revision
      )
        setLinkError(
          error instanceof ApiError && error.status === 409
            ? '계정을 연결하지 못했어요. 연결된 계정을 확인해 주세요.'
            : '계정 연결을 시작하지 못했어요. 다시 시도해 주세요.',
        );
    } finally {
      locked.current = false;
      if (active.current) {
        setPending(false);
        setLinking(false);
      }
    }
  }
  return (
    <div
      ref={root}
      className="group relative shrink-0 font-panel"
      onBlur={(event) => {
        // Browsers may blur the focused logout action when it becomes disabled.
        // Keep its progress/error visible; an actual outside pointer still closes.
        if (event.relatedTarget === null && locked.current) return;
        if (!event.currentTarget.contains(event.relatedTarget)) setOpen(false);
      }}
      onKeyDown={(event) => {
        if (
          open &&
          event.target !== trigger.current &&
          ['ArrowDown', 'ArrowUp', 'Home', 'End'].includes(event.key)
        ) {
          const items = [
            ...(root.current?.querySelectorAll<HTMLButtonElement>(
              '[role="menuitem"]:not(:disabled)',
            ) ?? []),
          ];
          const index = items.indexOf(
            document.activeElement as HTMLButtonElement,
          );
          const target =
            event.key === 'Home'
              ? 0
              : event.key === 'End'
                ? items.length - 1
                : event.key === 'ArrowDown'
                  ? (index + 1) % items.length
                  : (index - 1 + items.length) % items.length;
          event.preventDefault();
          items[target]?.focus();
        }
        if (event.key === 'Escape' && open) {
          event.preventDefault();
          event.stopPropagation();
          setOpen(false);
          trigger.current?.focus();
        }
      }}
    >
      <button
        ref={trigger}
        type="button"
        aria-label={open ? '계정 메뉴 닫기' : '계정 메뉴 열기'}
        aria-haspopup="menu"
        aria-expanded={open}
        aria-controls={open ? menuId : undefined}
        aria-describedby={open ? undefined : tooltipId}
        className="flex min-h-11 min-w-11 cursor-pointer items-center justify-center gap-1.5 rounded-panel px-1.5 text-xs text-zoop-muted hover:bg-zoop-soft focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-zoop-ink"
        onClick={() => setOpen((value) => !value)}
        onKeyDown={(event) => {
          if (event.key === 'ArrowDown' || event.key === 'ArrowUp') {
            event.preventDefault();
            if (open) action.current?.focus();
            else setOpen(true);
          }
        }}
      >
        <span className="grid size-6 place-items-center rounded-full bg-zoop-soft max-sm:size-7">
          <GraphIcon name="user" />
        </span>
        <span className="max-w-28 truncate max-sm:hidden">
          {member.displayName}
        </span>
        <span className="max-sm:hidden">
          <GraphIcon name="chevron" size={12} />
        </span>
      </button>
      {!open && (
        <span
          id={tooltipId}
          role="tooltip"
          className="pointer-events-none invisible absolute top-full right-0 z-[90] mt-1 whitespace-nowrap rounded-panel bg-zoop-ink px-2 py-1 text-[11px] text-white group-hover:visible group-focus-within:visible"
        >
          계정 메뉴 열기
        </span>
      )}
      {open && (
        <div className="absolute top-full right-0 z-[80] mt-1 w-64 max-w-[calc(100vw-2rem)] rounded-panel border border-panel-line bg-white text-panel-ink shadow-lg">
          <div className="border-b border-panel-line px-4 py-3">
            <p className="truncate text-xs font-semibold">
              {member.displayName}
            </p>
            <p className="mt-1 break-all text-[11px] text-panel-muted">
              {member.email}
            </p>
          </div>
          <div id={menuId} role="menu" aria-label="계정 메뉴" className="p-1">
            {(['google', 'kakao'] as const).map((provider) => (
              <button
                key={provider}
                type="button"
                role="menuitem"
                disabled={pending}
                className="flex min-h-11 w-full items-center rounded-panel px-3 text-left text-xs hover:bg-panel-soft focus-visible:outline-2 disabled:opacity-60"
                onClick={() => void linkSocial(provider)}
              >
                {provider === 'google'
                  ? 'Google 계정 연결'
                  : '카카오 계정 연결'}
              </button>
            ))}
            <button
              ref={action}
              type="button"
              role="menuitem"
              disabled={pending}
              aria-busy={pending}
              className="flex min-h-11 w-full cursor-pointer items-center rounded-panel px-3 text-left text-xs hover:bg-panel-soft focus-visible:bg-panel-soft focus-visible:outline-2 focus-visible:outline-panel-ink disabled:cursor-progress disabled:opacity-60"
              onClick={() => void signOut()}
            >
              {pending && !linking
                ? '로그아웃하고 있어요'
                : failed
                  ? '로그아웃 다시 시도'
                  : '로그아웃'}
            </button>
          </div>
          {failed && (
            <p
              role="alert"
              className="px-4 pb-3 text-xs leading-relaxed text-zoop-alert"
            >
              로그아웃하지 못했어요. 로그인 상태가 유지되고 있어요. 다시 시도해
              주세요.
            </p>
          )}
          {linkError && (
            <p role="alert" className="px-4 pb-3 text-xs text-zoop-alert">
              {linkError}
            </p>
          )}
        </div>
      )}
      {socialResult === 'linked' && (
        <p
          role="status"
          className="absolute right-0 w-64 bg-zoop-paper p-2 text-xs"
        >
          소셜 계정을 연결했어요.
        </p>
      )}
      {(socialResult === 'failed' || socialResult === 'cancelled') && (
        <p
          role="status"
          className="absolute right-0 w-64 bg-zoop-paper p-2 text-xs"
        >
          {socialResult === 'cancelled'
            ? '계정 연결을 취소했어요.'
            : '계정을 연결하지 못했어요. 다시 시도해 주세요.'}
        </p>
      )}
    </div>
  );
}
