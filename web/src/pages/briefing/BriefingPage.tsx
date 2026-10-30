import { useAuth } from '@/hooks/useAuth';
import PublishedBriefing from '@/components/briefing/PublishedBriefing';
import BriefingRoundPicker from '@/components/briefing/BriefingRoundPicker';
import { FOCUS_RING } from '@/components/briefing/briefingStyles';
import GraphIcon from '@/components/graph/GraphIcon';
import { useRouteQuery } from '@/hooks/useRouteQuery';
import type { BriefingEdition } from '@/types/briefing';
import { selectMemberId, useAuthStore } from '@/stores/useAuthStore';
import { useScreenView } from '@/util/track';

const EDITION_BUTTON = `min-w-[76px] whitespace-nowrap rounded-[2px] text-xs font-semibold text-zoop-muted aria-pressed:bg-zoop-paper aria-pressed:text-zoop-ink aria-pressed:shadow-[0_0_0_0.5px_#1a1a1a14] max-sm:flex-1 ${FOCUS_RING}`;

// D-BRF-01 출근 · D-BRF-02 퇴근 브리핑 (/briefing). 날짜·회차는 주소(?date=&edition=)에 남는다.
export default function BriefingPage() {
  useScreenView('briefing');
  const { params, updateQuery } = useRouteQuery();
  const auth = useAuth();
  const memberId = useAuthStore(selectMemberId);
  const revision = useAuthStore((s) => s.sessionRevision);
  const edition: BriefingEdition =
    params.get('edition') === 'evening' ? 'evening' : 'morning';
  const reading = params.get('reading');
  const compact = reading !== 'full';
  const date = params.get('date') ?? '';
  // FS036: 공통 / 내 종목 기준. 주소(?view=personal)에 남는다.
  const personal = params.get('view') === 'personal';
  return (
    <section
      className="mx-auto w-full max-w-[1040px] text-zoop-ink"
      data-screen-id={edition === 'morning' ? 'D-BRF-01' : 'D-BRF-02'}
    >
      <h1 className="flex items-center gap-2.5 text-[28px] font-[750] tracking-[-0.045em]">
        <GraphIcon name="briefing" size={24} />
        브리핑
      </h1>
      <p className="mt-1.5 text-xs text-zoop-muted">
        시장의 주요 변화와 내 종목 주변 사건을 한눈에 확인하세요.
      </p>

      {auth.failed && (
        <p role="alert" className="mt-3 text-xs text-zoop-muted">
          로그인 상태를 확인하지 못해 공통 브리핑을 표시합니다.{' '}
          <button type="button" className={FOCUS_RING} onClick={auth.retry}>
            로그인 상태 다시 확인
          </button>
        </p>
      )}
      <div
        className="mt-5 flex items-center gap-2.5 max-sm:flex-col max-sm:items-stretch"
        aria-label="브리핑 회차 선택"
      >
        <BriefingRoundPicker
          date={date}
          edition={edition}
          onChange={(next, nextEdition) =>
            updateQuery({ date: next || null, edition: nextEdition })
          }
        />
      </div>

      <div
        role="group"
        aria-label="브리핑 기준"
        className="mt-3 inline-flex h-8 rounded-[3px] border-[0.667px] border-zoop-line bg-zoop-soft p-[3px]"
      >
        <button
          type="button"
          aria-pressed={!personal}
          onClick={() => updateQuery({ view: null })}
          className={`px-3 ${EDITION_BUTTON}`}
        >
          공통
        </button>
        <button
          type="button"
          aria-pressed={personal}
          onClick={() => updateQuery({ view: 'personal' })}
          className={`px-3 ${EDITION_BUTTON}`}
        >
          개인화 브리핑
        </button>
      </div>

      <div
        className="mt-3 flex items-center gap-2"
        role="group"
        aria-label="브리핑 읽기 방식"
      >
        <span className="mr-auto text-[11px] text-zoop-muted">
          {compact ? '핵심 이슈 중심' : '전체 분석과 근거'}
        </span>
        <button
          type="button"
          aria-pressed={compact}
          className={`min-h-11 border border-zoop-line px-3 ${EDITION_BUTTON}`}
          onClick={() => updateQuery({ reading: 'compact' })}
        >
          간단히
        </button>
        <button
          type="button"
          aria-pressed={!compact}
          className={`min-h-11 border border-zoop-line px-3 ${EDITION_BUTTON}`}
          onClick={() => updateQuery({ reading: 'full' })}
        >
          전체 보기
        </button>
      </div>

      <PublishedBriefing
        key={`${date}:${edition}:${memberId ?? 'public'}:${revision}`}
        date={date}
        edition={edition}
        personal={personal}
        compact={compact}
      />
    </section>
  );
}
