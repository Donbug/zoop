import type { BriefingGraphBasis } from '@/types/briefing';

/** Known publication states are notices; transport failures remain retryable errors. */
export class BriefingGraphUnavailableError extends Error {
  readonly reason: string;

  constructor(basis: BriefingGraphBasis) {
    super(basis.message ?? '이 회차의 그래프를 제공할 수 없습니다.');
    this.name = 'BriefingGraphUnavailableError';
    this.reason = basis.unavailableReason ?? basis.status;
  }
}
