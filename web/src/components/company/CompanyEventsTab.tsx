import PageSection from '@/components/common/PageSection';
import EmptyState from '@/components/common/EmptyState';

// D-COM-01b / 05 / 06
// TODO: 기간·차트·시간 버킷·asOf를 연동한다. 가격과 사건의 시간 겹침을 인과로 표시하지 않는다.
export default function CompanyEventsTab() {
  return (
    <PageSection title="사건·시점 탐색">
      <EmptyState message="준비 중입니다." />
    </PageSection>
  );
}
