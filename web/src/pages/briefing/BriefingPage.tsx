import PageShell from '@/components/common/PageShell';
import MarketIndicators from '@/components/briefing/MarketIndicators';
import BriefingIssueList from '@/components/briefing/BriefingIssueList';
import BriefingComparison from '@/components/briefing/BriefingComparison';
import { useRouteQuery } from '@/hooks/useRouteQuery';
import type { BriefingEdition } from '@/types/briefing';

export default function BriefingPage() {
  const { params, updateQuery } = useRouteQuery();
  const edition: BriefingEdition =
    params.get('edition') === 'evening' ? 'evening' : 'morning';
  return (
    <PageShell title={edition === 'morning' ? '출근 브리핑' : '퇴근 브리핑'}>
      <div className="flex flex-wrap gap-4">
        <label>
          날짜{' '}
          <input
            type="date"
            value={params.get('date') ?? ''}
            onChange={(event) => updateQuery({ date: event.target.value })}
          />
        </label>
        <button
          type="button"
          aria-pressed={edition === 'morning'}
          onClick={() => updateQuery({ edition: 'morning' })}
        >
          출근
        </button>
        <button
          type="button"
          aria-pressed={edition === 'evening'}
          onClick={() => updateQuery({ edition: 'evening' })}
        >
          퇴근
        </button>
      </div>
      <MarketIndicators />
      <BriefingIssueList />
      {edition === 'evening' && <BriefingComparison />}
    </PageShell>
  );
}
