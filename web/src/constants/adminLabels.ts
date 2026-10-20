import type { StageStatus } from '@/types/admin/briefings';
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
