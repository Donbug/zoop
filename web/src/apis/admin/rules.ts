import { adminCall } from '@/apis/admin/auth';
import { ApiError } from '@/apis/auth/ApiService';
import type { RuleList, RuleSwitchResponse } from '@/types/admin/rules';

const RULES = '/api/v1/admin/pipeline/rules';
// A-ADM-03 listPublicationRules: signed opaque cursor, not prototype offset.
export function listPublicationRules(cursor?: string) {
  const query = new URLSearchParams({ limit: '50' });
  if (cursor) query.set('cursor', cursor);
  return adminCall<RuleList>(`${RULES}?${query}`, 'GET');
}
// setPublicationRule uses admin CSRF. The contract has no Idempotency-Key.
export async function setPublicationRule(
  id: string,
  enabled: boolean,
  reason: string,
) {
  const result = await adminCall<RuleSwitchResponse>(
    `${RULES}/${encodeURIComponent(id)}`,
    'PUT',
    { enabled, reason },
  );
  if (result.rule.id !== id || result.rule.enabled !== enabled)
    throw new ApiError(
      200,
      'INVALID_RESPONSE',
      '요청한 규칙 상태와 응답이 일치하지 않습니다.',
    );
  return result;
}
