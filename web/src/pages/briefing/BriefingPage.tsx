import PublishedBriefing from '@/components/briefing/PublishedBriefing';
import { FOCUS_RING } from '@/components/briefing/briefingStyles';
import GraphIcon from '@/components/graph/GraphIcon';
import { useRouteQuery } from '@/hooks/useRouteQuery';
import type { BriefingEdition } from '@/types/briefing';

const EDITION_BUTTON = `min-w-[76px] rounded-[2px] text-xs font-semibold text-zoop-muted aria-pressed:bg-zoop-paper aria-pressed:text-zoop-ink aria-pressed:shadow-[0_0_0_0.5px_#1a1a1a14] max-sm:flex-1 ${FOCUS_RING}`;

// D-BRF-01 출근 · D-BRF-02 퇴근 브리핑 (/briefing). 날짜·회차는 주소(?date=&edition=)에 남는다.
export default function BriefingPage() {
  const { params, updateQuery } = useRouteQuery();
  const edition: BriefingEdition =
    params.get('edition') === 'evening' ? 'evening' : 'morning';
  const date = params.get('date') ?? '';
  return (
    <section
      className="mx-auto w-full max-w-[800px] text-zoop-ink"
      data-screen-id={edition === 'morning' ? 'D-BRF-01' : 'D-BRF-02'}
    >
      <h1 className="flex items-center gap-2.5 text-[28px] font-[750] tracking-[-0.045em]">
        <GraphIcon name="briefing" size={24} />
        브리핑
      </h1>
      <p className="mt-1.5 text-xs text-zoop-muted">
        시장의 주요 변화와 내 종목 주변 사건을 한눈에 확인하세요.
      </p>

      <div
        className="mt-5 flex items-center gap-2.5 max-sm:flex-col max-sm:items-stretch"
        aria-label="브리핑 회차 선택"
      >
        <label className="sr-only" htmlFor="briefing-date">
          날짜
        </label>
        <input
          id="briefing-date"
          className={`h-[38px] rounded-[3px] border-[0.667px] border-zoop-line bg-zoop-paper px-3 text-xs text-zoop-ink max-sm:w-full ${FOCUS_RING}`}
          type="date"
          value={date}
          onChange={(event) => updateQuery({ date: event.target.value })}
        />
        <div className="flex h-[38px] rounded-[3px] border-[0.667px] border-zoop-line bg-zoop-soft p-[3px] max-sm:w-full">
          <button
            type="button"
            aria-pressed={edition === 'morning'}
            onClick={() => updateQuery({ edition: 'morning' })}
            className={EDITION_BUTTON}
          >
            ☼ 출근
          </button>
          <button
            type="button"
            aria-pressed={edition === 'evening'}
            onClick={() => updateQuery({ edition: 'evening' })}
            className={EDITION_BUTTON}
          >
            ◔ 퇴근
          </button>
        </div>
      </div>

      <PublishedBriefing key={date + edition} date={date} edition={edition} />
    </section>
  );
}
