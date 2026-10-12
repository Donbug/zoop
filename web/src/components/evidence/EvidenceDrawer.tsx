import PageSection from '@/components/common/PageSection';
import EmptyState from '@/components/common/EmptyState';
import { useGraphUiStore } from '@/stores/useGraphUiStore';

// D-GRP-05: 실제 모달/모바일 시트, 초점 복원, 근거 API는 후속 구현.
export default function EvidenceDrawer() {
  const target = useGraphUiStore((state) => state.evidenceTarget);
  const close = useGraphUiStore((state) => state.closeEvidence);
  if (!target) return null;
  return (
    <PageSection title="근거 문서">
      <EmptyState message="근거 문서를 준비하고 있습니다." />
      <button type="button" onClick={close} className="mt-3 underline">
        닫기
      </button>
    </PageSection>
  );
}
