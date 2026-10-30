import BriefingOperations from '@/components/admin/briefings/BriefingOperations';

// A-ADM-04 브리핑 운영 (/admin/briefings)
export default function AdminBriefingsPage({
  readOnly = true,
}: {
  readOnly?: boolean;
}) {
  return (
    <div data-screen-id="A-ADM-04">
      <BriefingOperations readOnly={readOnly} />
    </div>
  );
}
