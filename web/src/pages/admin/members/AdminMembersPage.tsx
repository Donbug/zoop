import PageShell from '@/components/common/PageShell';
import MemberManagement from '@/components/admin/members/MemberManagement';

export default function AdminMembersPage() {
  return (
    <PageShell title="회원 관리">
      <MemberManagement />
    </PageShell>
  );
}
