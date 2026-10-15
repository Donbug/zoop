// A-ADM-05c 관리자 인증 (docs/api/openapi.yaml AdminSession·AdminInfo·AdminLoginRequest)
// 관리자 세션은 회원 세션과 별개인 HttpOnly 쿠키(zoop_admin_session)이며 회원 세션으로 대신하지 않는다.

export type AdminInfo = {
  id: string;
  email: string;
  displayName: string;
  role: string;
};

/** 유휴(idle) 또는 최대 시간(absolute) 만료 */
export type AdminExpiredReason = 'idle' | 'absolute';

export type AdminSession = {
  authenticated: boolean;
  expired: boolean;
  expiredReason: AdminExpiredReason | null;
  admin: AdminInfo | null;
  expiresAt: string | null;
  idleExpiresAt: string | null;
  idleTimeoutSeconds: number;
  absoluteTimeoutSeconds: number;
  /** 관리자 세션 쓰기 요청의 X-CSRF-Token. 세션이 없으면 null */
  csrfToken: string | null;
};

export type AdminLoginRequest = {
  email: string;
  password: string;
};

export type AdminSessionStatus = 'checking' | 'ready' | 'error';

export type AdminSessionState = {
  status: AdminSessionStatus;
  session: AdminSession | null;
  /** 인증된 관리자일 때만 값이 있다. */
  admin: AdminInfo | null;
  /** 세션이 바뀔 때마다 늘어난다. 늦게 도착한 응답을 버릴 때 쓴다. */
  revision: number;
  setSession: (session: AdminSession) => void;
  setStatus: (status: AdminSessionStatus) => void;
  clearSession: () => void;
};

/** 관리자 로그인 화면으로 보낼 때 함께 넘기는 상태 */
export type AdminLoginLocationState = {
  from?: { pathname?: string; search?: string; hash?: string };
  expiredReason?: AdminExpiredReason | null;
};
