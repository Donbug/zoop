import { adminCall } from '@/apis/admin/auth';
import type {
  AuditPage,
  MemberDetail,
  MemberFilter,
  MemberList,
  MemberStatusResult,
} from '@/types/admin/members';

// A-ADM-05 회원·접근 관리 · A-ADM-05b 감사 로그.
// 차단·차단 해제는 관리자 CSRF와 Idempotency-Key가 필요하고, 사유는 감사 로그에 남는다.

const MEMBERS = '/api/v1/admin/members';
const member = (memberId: string) =>
  `${MEMBERS}/${encodeURIComponent(memberId)}`;

function query(values: Record<string, string | null | undefined>) {
  const params = new URLSearchParams();
  Object.entries(values).forEach(([key, value]) => {
    if (value) params.set(key, value);
  });
  const text = params.toString();
  return text ? `?${text}` : '';
}

/** listMembers: 상태·검색(가명 id·가린 이메일) 조건과 불투명 커서 */
export function listMembers(filter: MemberFilter, q: string, cursor?: string) {
  return adminCall<MemberList>(
    `${MEMBERS}${query({
      status: filter === 'all' ? null : filter,
      q: q.trim() || null,
      cursor,
    })}`,
    'GET',
  );
}

/** getMemberActivity: 활동 통계와 차단·해제 이력. 조회만으로 상태를 바꾸지 않는다. */
export function getMemberActivity(memberId: string) {
  return adminCall<MemberDetail>(member(memberId), 'GET');
}

/** blockMember: 차단하고 열린 세션을 회수한다. */
export function blockMember(
  memberId: string,
  reason: string,
  idempotencyKey: string,
) {
  return adminCall<MemberStatusResult>(
    `${member(memberId)}/block`,
    'POST',
    { reason },
    { 'Idempotency-Key': idempotencyKey },
  );
}

/** unblockMember: 차단을 푼다. 다시 로그인할 수 있다. */
export function unblockMember(
  memberId: string,
  reason: string,
  idempotencyKey: string,
) {
  return adminCall<MemberStatusResult>(
    `${member(memberId)}/unblock`,
    'POST',
    { reason },
    { 'Idempotency-Key': idempotencyKey },
  );
}

/** listAuditRecords: 운영 감사 기록(최신 먼저, 불투명 커서) */
export function listAuditRecords(
  action: string | null,
  q: string,
  cursor?: string,
) {
  return adminCall<AuditPage>(
    `/api/v1/admin/audit-log${query({ action, q: q.trim() || null, cursor })}`,
    'GET',
  );
}
