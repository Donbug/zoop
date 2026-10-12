import { useParams } from 'react-router-dom';
import PageShell from '@/components/common/PageShell';
import CompanySidebar from '@/components/company/CompanySidebar';
import CompanyOverview from '@/components/company/CompanyOverview';
import CompanyEventsTab from '@/components/company/CompanyEventsTab';
import CompanyDocumentsTab from '@/components/company/CompanyDocumentsTab';
import CompanyInfoTab from '@/components/company/CompanyInfoTab';
import CompanyRelationGraph from '@/components/company/CompanyRelationGraph';
import { useRouteQuery } from '@/hooks/useRouteQuery';
import type { CompanyTabOption } from '@/types/company';

const tabs: CompanyTabOption[] = [
  { value: 'events', label: '사건' },
  { value: 'documents', label: '문서' },
  { value: 'info', label: '기업 정보' },
];

export default function CompanyDetailPage() {
  const { id } = useParams();
  const { params, updateQuery } = useRouteQuery();
  const tab = tabs.some((item) => item.value === params.get('tab'))
    ? params.get('tab')
    : 'events';
  return (
    <PageShell title="기업 상세">
      <div className="grid gap-6 lg:grid-cols-[14rem_1fr_20rem]">
        <CompanySidebar />
        <div className="min-w-0 space-y-6" key={id}>
          {/* 기업 전환 시 이 영역의 사건/버킷 로컬 상태를 초기화한다. */}
          <CompanyOverview />
          <nav aria-label="기업 상세 보기" className="flex gap-4">
            {tabs.map((item) => (
              <button
                key={item.value}
                type="button"
                aria-pressed={tab === item.value}
                onClick={() => updateQuery({ tab: item.value })}
              >
                {item.label}
              </button>
            ))}
          </nav>
          {tab === 'events' && <CompanyEventsTab />}
          {tab === 'documents' && <CompanyDocumentsTab />}
          {tab === 'info' && <CompanyInfoTab />}
        </div>
        <CompanyRelationGraph />
      </div>
    </PageShell>
  );
}
