import type { ReactNode } from 'react';
import { Link } from 'react-router-dom';
import type { BriefingItem } from '@/types/briefing';
import BriefingItemDetails from './BriefingItemDetails';
import {
  BODY,
  EMPTY,
  FOCUS_RING,
  NOTE,
  SECTION,
  SECTION_TITLE,
} from './briefingStyles';

// D-BRF-01·02 핵심 이슈 (FS028·FS030). 서버가 고른 최대 3개만 보여 주고, 부족해도 채우지 않는다.
export default function BriefingIssueList({
  items,
  graphHref,
  roundId,
  graphVersion = null,
  renderExtra,
}: {
  items?: BriefingItem[];
  /** D-BRF-04 이 회차 기준 지도 주소. 발행 회차에만 준다. */
  graphHref?: string;
  /** 상세·근거는 이 발행 회차의 저장본만 조회한다. */
  roundId?: string;
  graphVersion?: string | null;
  /** 이슈마다 덧붙일 영역(회차 지도 링크·평가). 발행 회차에만 준다. */
  renderExtra?: (item: BriefingItem) => ReactNode;
}) {
  return (
    <section className={SECTION} aria-labelledby="briefing-issues-title">
      <div className="flex flex-wrap items-start justify-between gap-2">
        <h3 id="briefing-issues-title" className={SECTION_TITLE}>
          핵심 이슈
        </h3>
        {graphHref && (
          <Link
            to={graphHref}
            className={`inline-flex h-7 items-center rounded-[3px] border-[0.667px] border-zoop-line bg-zoop-paper px-2.5 text-[11px] font-semibold hover:bg-zoop-wash ${FOCUS_RING}`}
          >
            이 회차 전체 관계 그래프
          </Link>
        )}
      </div>
      {!items || items.length === 0 ? (
        <p className={EMPTY}>
          {items
            ? '이 회차의 선정 기준을 충족한 핵심 이슈가 없어요.'
            : '이 회차의 핵심 이슈를 준비하고 있어요.'}
        </p>
      ) : (
        <ol>
          {items.slice(0, 3).map((item) => (
            <li
              key={item.eventId}
              className="flex flex-col gap-1.5 border-t-[0.667px] border-zoop-line pt-5 first:border-t-0 first:pt-0 [&+li]:mt-5"
            >
              <p className={NOTE}>
                {item.timePrecision === 'unknown' || !item.eventTime
                  ? '발생 시각 미상'
                  : `발생 ${item.eventTime}`}
              </p>
              <h4 className="text-sm font-bold">
                {item.rank}. {item.title}
              </h4>
              {(item.matchedCompanyIds ?? []).length > 0 && (
                <p className="self-start rounded-full border-[0.667px] border-zoop-ink px-2 py-[2px] text-[10px] font-semibold">
                  내 종목:{' '}
                  {item.companies
                    .filter((company) =>
                      (item.matchedCompanyIds ?? []).includes(company.id),
                    )
                    .map((company) => company.name)
                    .join(', ') || (item.matchedCompanyIds ?? []).join(', ')}
                </p>
              )}
              <p className="text-[11px] text-zoop-muted">
                {item.companies.length
                  ? item.companies.map((company) => company.name).join(', ')
                  : '확인된 기업 없음'}
              </p>
              <p className={BODY}>
                {'text' in item.summary
                  ? item.summary.text
                  : item.summary.reason}
              </p>
              <p className={NOTE}>
                선정 이유: {item.reason} · 근거 {item.evidenceCount}건
              </p>
              {roundId && (
                <BriefingItemDetails
                  key={`${roundId}:${item.eventId}:${graphVersion}`}
                  roundId={roundId}
                  graphVersion={graphVersion}
                  item={item}
                />
              )}
              {renderExtra?.(item)}
            </li>
          ))}
        </ol>
      )}
    </section>
  );
}
