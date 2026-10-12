import PageShell from '@/components/common/PageShell';
import AuditLogTable from '@/components/admin/audit/AuditLogTable';

export default function AdminAuditPage() {
  return (
    <PageShell title="감사 로그">
      <AuditLogTable />
    </PageShell>
  );
}
