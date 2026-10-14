import MarketIndicators from '@/components/briefing/MarketIndicators';
import BriefingIssueList from '@/components/briefing/BriefingIssueList';
import BriefingComparison from '@/components/briefing/BriefingComparison';
import GraphIcon from '@/components/graph/GraphIcon';
import { useRouteQuery } from '@/hooks/useRouteQuery';
import type { BriefingEdition } from '@/types/briefing';

export default function BriefingPage() {
  const { params, updateQuery } = useRouteQuery();
  const edition: BriefingEdition =
    params.get('edition') === 'evening' ? 'evening' : 'morning';
  const date = params.get('date') ?? '';
  const label = edition === 'morning' ? '출근' : '퇴근';
  return (
    <section
      className="briefing-page"
      data-screen-id={edition === 'morning' ? 'D-BRF-01' : 'D-BRF-02'}
    >
      <h1 className="briefing-page-title">
        <GraphIcon name="briefing" size={24} />
        브리핑
      </h1>
      <p className="briefing-kicker">
        시장의 주요 변화와 내 종목 주변 사건을 한눈에 확인하세요.
      </p>

      <div className="briefing-controls" aria-label="브리핑 회차 선택">
        <label className="sr-only" htmlFor="briefing-date">
          날짜
        </label>
        <input
          id="briefing-date"
          className="briefing-date"
          type="date"
          value={date}
          onChange={(event) => updateQuery({ date: event.target.value })}
        />
        <div className="briefing-editions">
          <button
            type="button"
            aria-pressed={edition === 'morning'}
            onClick={() => updateQuery({ edition: 'morning' })}
          >
            ☼ 출근
          </button>
          <button
            type="button"
            aria-pressed={edition === 'evening'}
            onClick={() => updateQuery({ edition: 'evening' })}
          >
            ◔ 퇴근
          </button>
        </div>
      </div>

      <article className="briefing-card" aria-labelledby="briefing-card-title">
        <header className="briefing-card-header">
          <div>
            <h2 id="briefing-card-title">{label} 브리핑</h2>
            <p>{date || '날짜를 선택해 주세요'} · 회차 데이터 연결 준비 중</p>
          </div>
          <span className="briefing-status">준비 중</span>
        </header>
        <MarketIndicators />
        <BriefingIssueList />
        {edition === 'evening' && <BriefingComparison />}
      </article>
    </section>
  );
}
