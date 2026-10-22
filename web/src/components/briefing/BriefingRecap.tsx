import { useEffect, useState } from 'react';
import { Link } from 'react-router-dom';
import { getBriefingRecap } from '@/apis/briefing/briefing';
import type {
  BriefingRecap as Recap,
  BriefingResponse,
} from '@/types/briefing';
import { briefingTime } from '@/util/briefingTime';
import BriefingItemDetails from './BriefingItemDetails';
import BriefingReadingSection from './BriefingReadingSection';
import {
  BODY,
  EMPTY,
  FOCUS_RING,
  NOTE,
  SECTION,
  SECTION_TITLE,
} from './briefingStyles';

// D-BRF-01·02: 과거 내용을 새 핵심 이슈·새 전망으로 취급하지 않는 별도 복기 영역.
export default function BriefingRecap({
  round,
  compact,
}: {
  round: BriefingResponse;
  compact: boolean;
}) {
  const [attempt, setAttempt] = useState(0);
  const key = `${round.id}:${round.graphVersion}:${round.dataAsOf}:${attempt}`;
  const [state, setState] = useState<{
    key: string;
    recap?: Recap;
    error?: boolean;
  }>();
  useEffect(() => {
    let active = true;
    getBriefingRecap(round).then(
      (recap) => {
        if (active) setState({ key, recap });
      },
      () => {
        if (active) setState({ key, error: true });
      },
    );
    return () => {
      active = false;
    };
  }, [round, key]);
  const current = state?.key === key ? state : undefined;
  const previous = current?.recap?.previous;
  return (
    <section className={SECTION} aria-labelledby="briefing-recap-title">
      <h3 id="briefing-recap-title" className={SECTION_TITLE}>
        새 핵심 이슈 없음 · 이전 브리핑 복기
      </h3>
      <p className={BODY}>
        확인한 자료 범위에서 이번 선정 기준을 충족한 새 핵심 이슈가 없습니다.
      </p>
      <p className={NOTE}>
        시장 전체에 새 소식이 없다는 뜻은 아닙니다. 아래 내용은 과거 발행본이며
        이번 회차에 다시 평가한 전망이 아닙니다.
      </p>
      {!current && (
        <p className={NOTE} role="status">
          고정된 이전 브리핑을 확인하고 있어요.
        </p>
      )}
      {current?.error && (
        <p className={EMPTY} role="alert">
          이전 브리핑의 복기 내용을 불러오지 못했어요.{' '}
          <button
            type="button"
            className={`underline ${FOCUS_RING}`}
            onClick={() => setAttempt((value) => value + 1)}
          >
            복기 다시 확인
          </button>
        </p>
      )}
      {current?.recap && !previous && (
        <p className={NOTE}>{current.recap.message}</p>
      )}
      {previous && (
        <>
          <p className={`${NOTE} mt-3`}>
            이전 발행: {previous.date}{' '}
            {previous.edition === 'morning' ? '출근' : '퇴근'} · 데이터 기준{' '}
            {briefingTime(previous.dataAsOf)}
          </p>
          <ol className="mt-3 space-y-4">
            {previous.items.slice(0, 3).map((item) => (
              <li key={item.eventId}>
                <BriefingReadingSection
                  compact={compact}
                  title={`이전 이슈 · ${item.title}`}
                >
                  <h4 className="text-sm font-bold">{item.title}</h4>
                  <p className={BODY}>
                    {'text' in item.summary
                      ? item.summary.text
                      : item.summary.reason}
                  </p>
                  <BriefingItemDetails
                    roundId={previous.id}
                    graphVersion={previous.graphVersion}
                    item={item}
                  />
                </BriefingReadingSection>
              </li>
            ))}
          </ol>
          <Link
            className={`mt-3 inline-block text-xs font-semibold underline ${FOCUS_RING}`}
            to={`/briefing?date=${previous.date}&edition=${previous.edition}&reading=full`}
          >
            이전 브리핑 전문·관전 조건 확인
          </Link>
        </>
      )}
    </section>
  );
}
