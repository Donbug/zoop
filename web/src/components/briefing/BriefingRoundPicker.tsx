import { useCallback, useEffect, useRef, useState } from 'react';
import { listBriefingRounds } from '@/apis/briefing/briefing';
import type { BriefingRoundRef } from '@/types/briefing';
import { FOCUS_RING } from './briefingStyles';

const CONTROL = `h-[38px] rounded-[3px] border-[0.667px] border-zoop-line bg-zoop-paper px-3 text-xs text-zoop-ink max-sm:w-full ${FOCUS_RING}`;

type State = {
  rounds: BriefingRoundRef[];
  nextCursor: string | null;
  loading: boolean;
  error: boolean;
};

// D-BRF-01·02 회차 날짜 선택 (FS033·FS035, listBriefingRounds)
// - 발행 이력에 있는 날짜만 고를 수 있다. 비우면 최신 회차를 본다.
// - 이력을 불러오지 못하면 날짜를 직접 고르는 입력으로 바꾼다.
export default function BriefingRoundPicker({
  date,
  onChange,
}: {
  date: string;
  onChange: (date: string) => void;
}) {
  const [state, setState] = useState<State>({
    rounds: [],
    nextCursor: null,
    loading: true,
    error: false,
  });

  const pending = useRef(false);
  const mounted = useRef(true);
  const cursors = useRef(new Set<string>());
  const load = useCallback((cursor?: string) => {
    if (pending.current) return;
    pending.current = true;
    setState((old) => ({ ...old, loading: true, error: false }));
    void (async () => {
      try {
        const page = await listBriefingRounds(cursor);
        if (!mounted.current) return;
        if (
          page.nextCursor &&
          (page.nextCursor === cursor || cursors.current.has(page.nextCursor))
        )
          throw new Error('반복된 이력 커서');
        if (cursor) cursors.current.add(cursor);
        else cursors.current.clear();
        setState((old) => ({
          rounds: [
            ...new Map(
              (cursor ? [...old.rounds, ...page.items] : page.items).map(
                (round) => [round.id, round],
              ),
            ).values(),
          ],
          nextCursor: page.nextCursor,
          loading: false,
          error: false,
        }));
      } catch {
        if (mounted.current)
          setState((old) => ({ ...old, loading: false, error: true }));
      } finally {
        pending.current = false;
      }
    })();
  }, []);

  useEffect(() => {
    mounted.current = true;
    let active = true;
    listBriefingRounds().then(
      (page) => {
        if (active)
          setState({
            rounds: page.items,
            nextCursor: page.nextCursor,
            loading: false,
            error: false,
          });
      },
      () => {
        if (active)
          setState((old) => ({ ...old, loading: false, error: true }));
      },
    );
    return () => {
      active = false;
      mounted.current = false;
    };
  }, []);

  if (state.error && state.rounds.length === 0)
    return (
      <div className="flex flex-col gap-1 max-sm:w-full">
        <label className="sr-only" htmlFor="briefing-date">
          날짜
        </label>
        <input
          id="briefing-date"
          type="date"
          value={date}
          onChange={(event) => onChange(event.target.value)}
          className={CONTROL}
        />
        <p className="text-[10px] text-zoop-muted">
          회차 이력을 불러오지 못해 날짜를 직접 골라요.{' '}
          <button
            type="button"
            onClick={() => load()}
            className={`underline ${FOCUS_RING}`}
          >
            다시 불러오기
          </button>
        </p>
      </div>
    );

  const dates = [...new Set([...state.rounds.map((round) => round.date), date])]
    .filter(Boolean)
    .sort()
    .reverse();
  const editions = (day: string) =>
    state.rounds
      .filter((round) => round.date === day)
      .map((round) =>
        round.edition === 'morning'
          ? round.status === 'suspended'
            ? '출근(중단)'
            : '출근'
          : round.status === 'suspended'
            ? '퇴근(중단)'
            : '퇴근',
      );

  return (
    <div className="flex items-center gap-2 max-sm:w-full">
      <label className="sr-only" htmlFor="briefing-date">
        발행일
      </label>
      <select
        id="briefing-date"
        value={date}
        disabled={state.loading && state.rounds.length === 0}
        onChange={(event) => onChange(event.target.value)}
        className={`${CONTROL} min-w-40`}
      >
        <option value="">최신 회차</option>
        {dates.map((day) => {
          const kinds = editions(day);
          return (
            <option key={day} value={day}>
              {day}
              {kinds.length ? ` · ${kinds.join('·')}` : ''}
            </option>
          );
        })}
      </select>
      {state.nextCursor && (
        <button
          type="button"
          disabled={state.loading}
          onClick={() => load(state.nextCursor ?? undefined)}
          className={`shrink-0 text-[11px] text-zoop-muted underline underline-offset-4 hover:text-zoop-ink disabled:opacity-60 ${FOCUS_RING}`}
        >
          {state.loading ? '불러오고 있어요' : '이전 회차 더 보기'}
        </button>
      )}
      {state.error && state.rounds.length > 0 && (
        <p role="alert" className="text-[10px] text-[#b42318]">
          이전 회차를 불러오지 못했어요.
        </p>
      )}
    </div>
  );
}
