// A-ADM-05 회원·접근 관리 · A-ADM-05b 관리자 감사 로그 (docs/api/openapi.yaml admin-members·admin-audit)
// 회원은 가명 id와 가린 이메일로만 온다. 실명·이메일 원문·대화·개인화 결과 원문은 오지 않는다.

export type MemberStatus = 'active' | 'blocked';

export type MemberRow = {
  /** 가명 id, 예: M-3FA9C2D1 */
  id: string;
  emailMasked: string;
  signupMethod: string;
  createdAt: string;
  lastActiveAt: string | null;
  status: MemberStatus;
  activity: {
    sessions: number | null;
    graphSelections: number | null;
    aiQuestions: number | null;
    briefingViews: number | null;
  };
};

export type MemberList = {
  items: MemberRow[];
  nextCursor: string | null;
  counts: { all: number; active: number; blocked: number };
};

export type MemberDetail = {
  member: MemberRow;
  onboardingCompleted: boolean;
  tutorialCompleted: boolean;
  watchlistCount: number;
  holdingCount: number;
  accountConnected: boolean;
  feedbackUp: number;
  feedbackDown: number;
  history: {
    at: string;
    action: 'member.block' | 'member.unblock';
    reason: string | null;
    adminEmail: string | null;
  }[];
};

export type MemberStatusResult = {
  /** 이미 같은 상태였으면 false(같은 요청을 다시 보내도 안전하다) */
  changed: boolean;
  detail: MemberDetail;
};

export type MemberFilter = 'all' | MemberStatus;

export type AuditEntry = {
  id: number;
  at: string;
  actorKind: 'admin' | 'system' | 'anonymous';
  actorId: string;
  actorEmail: string | null;
  action: string;
  targetType: string;
  targetId: string | null;
  reason: string | null;
  outcome: 'ok' | 'denied' | 'failed';
  detail: Record<string, unknown>;
};

export type AuditPage = {
  items: AuditEntry[];
  nextCursor: string | null;
};
