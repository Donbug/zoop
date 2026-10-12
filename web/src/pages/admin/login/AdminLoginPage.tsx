import PageShell from '@/components/common/PageShell';

import { Link } from 'react-router-dom';
import EmptyState from '@/components/common/EmptyState';

export default function AdminLoginPage() {
  return (
    <PageShell title="관리자 로그인">
      {/* TODO: 독립 관리자 세션 API와 입력 폼 연결. 회원 토큰을 재사용하지 않는다. */}
      <EmptyState message="관리자 로그인을 준비하고 있습니다." />
      <Link to="/login" className="text-emerald-700 underline">
        회원 로그인으로
      </Link>
    </PageShell>
  );
}
