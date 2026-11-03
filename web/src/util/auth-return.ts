import type { LoginLocationState } from '@/types/auth';

const socialReturnKey = 'zoop.auth.socialReturn';

/** D-AUT-01 A5: preserve an app path, never an external or authentication URL. */
function safeReturnPath(value: unknown): string | null {
  if (
    typeof value !== 'string' ||
    !value.startsWith('/') ||
    value.startsWith('//') ||
    value.includes('\\') ||
    Array.from(value).some((char) => {
      const code = char.charCodeAt(0);
      return code < 32 || code === 127;
    })
  )
    return null;
  try {
    const url = new URL(value, 'https://zoop.invalid');
    if (
      url.origin !== 'https://zoop.invalid' ||
      ['/login', '/signup'].includes(url.pathname)
    )
      return null;
    return value;
  } catch {
    return null;
  }
}

export function fromPath(state: LoginLocationState | null): string | null {
  const from = state?.from;
  return safeReturnPath(
    from?.pathname
      ? `${from.pathname}${from.search ?? ''}${from.hash ?? ''}`
      : null,
  );
}

export function clearSocialReturn() {
  try {
    sessionStorage.removeItem(socialReturnKey);
  } catch {
    // Cookie authentication still works when tab storage is unavailable.
  }
}

export function saveSocialReturn(from: string | null) {
  try {
    const path = safeReturnPath(from);
    if (path) sessionStorage.setItem(socialReturnKey, path);
    else sessionStorage.removeItem(socialReturnKey);
  } catch {
    // No return path is required to begin social authorization.
    clearSocialReturn();
  }
}

export function consumeSocialReturn(): string | null {
  try {
    const saved = sessionStorage.getItem(socialReturnKey);
    sessionStorage.removeItem(socialReturnKey);
    return safeReturnPath(saved);
  } catch {
    // A path that could not be consumed safely must not be used.
    clearSocialReturn();
    return null;
  }
}
