import type { StageStatus } from '@/types/admin/briefings';
import type { AuditEntry, MemberStatus } from '@/types/admin/members';
import type {
  DashboardGraphDbStatus,
  DashboardJobStatus,
  DashboardRoundStatus,
} from '@/types/admin/dashboard';

// 관리자 화면의 상태 이름. 프로토타입 관리자 화면(labels.ts)과 같은 이름을 쓴다.

export const editionLabel = { morning: '출근', evening: '퇴근' } as const;

export const roundStatusLabel: Record<DashboardRoundStatus, string> = {
  scheduled: '예정',
  missing: '지연(회차 없음)',
  generating: '생성 중',
  verifying: '검증 중',
  published: '발행됨',
  failed: '실패',
  suspended: '제공 중단',
};

export const jobStatusLabel: Record<DashboardJobStatus, string> = {
  queued: '대기',
  running: '실행 중',
  succeeded: '성공',
  failed: '실패',
  cancelled: '취소됨',
};

export const jobKindLabel: Record<string, string> = {
  'flush-graph': 'GraphDB 반영 재시도',
  'retry-model-errors': '모델 오류 재처리',
  'ingest-run': '신규 기사 처리',
};

export const graphDbStatusLabel: Record<DashboardGraphDbStatus, string> = {
  reflected: '반영됨',
  pending: '반영 대기',
  mismatch: '불일치',
  unavailable: '확인 불가',
};

export const stageStatusLabel: Record<StageStatus, string> = {
  pending: '대기',
  running: '진행 중',
  done: '완료',
  failed: '실패',
  skipped: '건너뜀',
};

export const aiSourceLabel: Record<string, string> = {
  measured: 'BFF 실측',
  'job-runner': '작업 러너',
  'ledger-db': '작업 원장',
  document: '문서 기록',
};

export const policyGroupLabel: Record<string, string> = {
  'strict-web': '엄격(웹 검증)',
  'relaxed-no-web': '완화(웹 검증 없음)',
  'admin-job': '관리자 작업',
};

export const memberStatusLabel: Record<MemberStatus, string> = {
  active: '정상',
  blocked: '차단됨',
};

/** 가입 방식. 소셜 제공자는 이름만 보여 준다. */
export function signupMethodLabel(method: string) {
  if (method === 'email') return '이메일';
  if (method === 'social:mock') return '소셜(개발용 모의)';
  return `소셜(${method.replace(/^social:/, '')})`;
}

export const auditOutcomeLabel: Record<AuditEntry['outcome'], string> = {
  ok: '완료',
  denied: '거부됨',
  failed: '실패',
};

export const auditActionLabel: Record<string, string> = {
  'auth.login': '로그인',
  'admin.provision': '관리자 계정 생성',
  'auth.login_failed': '로그인 실패',
  'auth.logout': '로그아웃',
  'review.decide': '검수 결정',
  'review.rule': '검수 규칙 전환',
  'graph.publish': '그래프 게시',
  // 백엔드가 실제로 남기는 그래프 전환 동작 코드(#275). 감사 로그 동작 필터도 이 값으로 조회한다.
  'graph.version.activate': '그래프 버전 전환',
  'graph.seed': '그래프 최초 등록',
  'job.create': '작업 실행',
  'job.retry': '작업 재시도',
  'job.cancel': '작업 취소',
  'job.recover': '작업 복구',
  'briefing.generate': '브리핑 생성',
  'briefing.reprocess': '브리핑 재처리',
  'briefing.correct': '브리핑 정정',
  'briefing.suspend': '브리핑 제공 중단',
  'briefing.resume': '브리핑 제공 재개',
  'transcript.view': 'AI 대화록 열람',
  'member.block': '회원 차단',
  'member.unblock': '회원 차단 해제',
};
