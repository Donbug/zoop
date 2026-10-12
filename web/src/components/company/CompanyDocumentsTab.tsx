import PageSection from '@/components/common/PageSection';
import EmptyState from '@/components/common/EmptyState';

// D-COM-02
// TODO: 출처·발행 시각·인용을 제공한다. 문서 탭 설명과 일부 프레임이 불일치한다.
export default function CompanyDocumentsTab() {
  return (
    <PageSection title="관련 문서">
      <EmptyState message="준비 중입니다." />
    </PageSection>
  );
}
