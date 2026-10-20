import { adminCall } from '@/apis/admin/auth';
import type { Dashboard } from '@/types/admin/dashboard';

// A-ADM-01 운영 대시보드 (getAdminDashboard). 관리자 세션으로 조회하며, 401이면 관리자 세션만 비운다.
export function getAdminDashboard() {
  return adminCall<Dashboard>('/api/v1/admin/dashboard', 'GET');
}
