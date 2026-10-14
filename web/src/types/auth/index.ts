// GET /api/v1/auth/session · POST /api/v1/auth/login · POST /api/v1/auth/guest
// (docs/api/openapi.yaml SessionResponse). 세션은 HttpOnly 쿠키(zoop_session)로 서버가 관리한다.

export type Member = {
  id: string;
  email: string;
  displayName: string;
};

export type SessionKind = 'anonymous' | 'guest' | 'member';

export type SetupState = {
  completed: boolean;
  tutorialCompleted: boolean;
};

export type Session = {
  authenticated: boolean;
  kind: SessionKind;
  user: Member | null;
  setup: SetupState | null;
  /** 쿠키 인증 쓰기 요청의 X-CSRF-Token. 세션이 없으면 null */
  csrfToken: string | null;
  expiresAt: string | null;
};

export type LoginRequest = {
  email: string;
  password: string;
};

/** 앱을 연 직후 세션을 확인하기 전은 checking이다. */
export type SessionStatus = 'checking' | 'ready' | 'error';

export type AuthState = {
  status: SessionStatus;
  sessionRevision: number;
  session: Session | null;
  /** 회원 세션일 때만 값이 있다. */
  member: Member | null;
  /** 회원의 초기 설정 완료 여부. 회원이 아니면 null */
  onboardingCompleted: boolean | null;
  setSession: (session: Session) => void;
  setStatus: (status: SessionStatus) => void;
  clearSession: () => void;
};

export type LoginLocationState = {
  from?: {
    pathname?: string;
    search?: string;
    hash?: string;
  };
};
