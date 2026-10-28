import type {
  CandidateGraphState,
  CandidateStatus,
} from '@/types/admin/pipeline';

// A-ADM-03 후보 표시 이름. 프로토타입 admin/labels.tsx(candidateStatusSpec·issueGraphDbSpec)를 옮겼다.

export const candidateStatusLabel: Record<CandidateStatus, string> = {
  ALLOW: '통과',
  HOLD: '보류',
  REJECT: '폐기',
};

export const decisionLabel: Record<'allow' | 'reject', string> = {
  allow: '허용',
  reject: '거부',
};

/** 활성 공개 버전 기준 상태. 별도 GraphDB 투영이 아니다. */
export const candidateGraphLabel: Record<CandidateGraphState, string> = {
  reflected: '사용자에게 보여요',
  excluded: '공개됐지만 지금은 숨겨져 있어요',
  pending: '승인했지만 아직 공개 버전에 없어요',
  not_stored: '공개 대상이 아니에요',
  unknown: '확인할 수 없어요',
};

const relationLabels: Record<string, string> = {
  INVOLVES: '직접 관련',
  STRUCTURALLY_RELATED_TO: '구조적 관련',
  FOLLOWS: '후속 사건',
  SHARES_ISSUE: '사건 공유',
};
/** 모르는 관계 유형은 원래 이름 그대로 */
export const relationLabel = (type: string) => relationLabels[type] ?? type;
