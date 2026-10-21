import AuditLogTable from '@/components/admin/audit/AuditLogTable';

// A-ADM-05b 관리자 감사 로그 (/admin/audit)
export default function AdminAuditPage() {
  return (
    <div data-screen-id="A-ADM-05b">
      <AuditLogTable />
    </div>
  );
}
