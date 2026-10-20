import DashboardSummary from '@/components/admin/dashboard/DashboardSummary';

// A-ADM-01 운영 대시보드 (/admin). 관리자 로그인 후 처음 보는 화면이다.
export default function AdminDashboardPage() {
  return (
    <div data-screen-id="A-ADM-01">
      <DashboardSummary />
    </div>
  );
}
