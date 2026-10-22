import { adminCall } from '@/apis/admin/auth';
import type {
  GraphVersionActivated,
  GraphVersionList,
} from '@/types/admin/graphVersions';

// A-ADM-03 그래프 버전 (FS059). 전환은 관리자 CSRF·Idempotency-Key가 필요하고, 사유는 감사 로그에 남는다.

const VERSIONS = '/api/v1/admin/graph/versions';

/** listGraphVersions: 공개 그래프 버전(최신 먼저)·현재 표시 버전·전환 이력. 불투명 커서 */
export function listGraphVersions(cursor?: string) {
  const query = cursor ? `?cursor=${encodeURIComponent(cursor)}` : '';
  return adminCall<GraphVersionList>(`${VERSIONS}${query}`, 'GET');
}

/**
 * activateGraphVersion: 이미 있는 공개 버전을 사용자에게 보이는 버전으로 바꾼다.
 * expectedActiveVersionId는 관리자가 화면에서 본 현재 버전이다. 그 사이 다른 관리자가 바꿨으면 409로 거절된다.
 */
export function activateGraphVersion(
  versionId: string,
  reason: string,
  expectedActiveVersionId: string | null,
  idempotencyKey: string,
) {
  return adminCall<GraphVersionActivated>(
    `${VERSIONS}/${encodeURIComponent(versionId)}/activate`,
    'POST',
    { reason, expectedActiveVersionId },
    { 'Idempotency-Key': idempotencyKey },
  );
}
