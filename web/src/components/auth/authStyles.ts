// D-AUT-01·02 인증 화면이 함께 쓰는 Tailwind 클래스(팀 규칙: 스타일은 Tailwind CSS 4).
// 색은 #169 시각 기준의 zoop 토큰(src/index.css @theme)만 쓴다.

export const focusRing =
  'focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-zoop-ink';

export const authHeading = 'text-2xl font-bold text-zoop-ink';

export const authLabel = 'text-[11px] font-semibold text-zoop-muted';

export const authInput = `mb-2 h-[46px] w-full rounded-[3px] border-[0.667px] border-zoop-line bg-zoop-paper px-3 text-[13px] text-zoop-ink focus:border-zoop-ink disabled:opacity-60 ${focusRing}`;

export const authPrimaryButton = `mt-4 flex h-[50px] w-full items-center justify-center gap-2 rounded-[3px] bg-zoop-ink px-4 text-[13px] font-bold text-zoop-paper disabled:cursor-progress disabled:opacity-60 ${focusRing}`;

/** 다른 시작 방법(회원가입·소셜·둘러보기) */
export const authSecondaryButton = `flex h-[50px] w-full items-center justify-center gap-2 rounded-[3px] border-[0.667px] border-zoop-line bg-zoop-paper px-4 text-[13px] font-semibold text-zoop-ink hover:bg-zoop-wash aria-disabled:cursor-not-allowed aria-disabled:opacity-60 disabled:cursor-not-allowed disabled:opacity-60 ${focusRing}`;

export const authSmallButton = `self-start rounded-[3px] border-[0.667px] border-zoop-line bg-zoop-paper px-3 py-1.5 text-xs font-semibold text-zoop-ink hover:bg-zoop-wash disabled:cursor-not-allowed disabled:opacity-60 ${focusRing}`;

export const authLink = `text-xs text-zoop-muted underline underline-offset-4 hover:text-zoop-ink ${focusRing}`;

export const authAlert = 'text-xs leading-6 text-[#b42318]';

export const authStatus = 'text-xs text-zoop-muted';

export const authNote = 'text-[11px] leading-relaxed text-zoop-muted';
