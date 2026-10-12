import PageSection from '@/components/common/PageSection';
import EmptyState from '@/components/common/EmptyState';

// PDF 실제 5페이지 하단
// TODO: 정식 명칭·시장·업종·설립·홈페이지를 표시한다.
export default function CompanyInfoTab() {
  return (
    <PageSection title="기업 정보">
      <EmptyState message="준비 중입니다." />
    </PageSection>
  );
}
