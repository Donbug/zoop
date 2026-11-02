import { useCallback, useEffect, useRef, useState } from 'react';
import { listBriefingRounds } from '@/apis/briefing/briefing';
import type { BriefingEdition, BriefingRoundRef } from '@/types/briefing';
import { FOCUS_RING } from './briefingStyles';
import { LoadingSpinner } from '@/components/common/LoadingIndicator';

const EDITION_BUTTON = `min-h-10 min-w-[88px] whitespace-nowrap rounded-full border border-zoop-line bg-zoop-paper px-4 text-caption font-semibold text-zoop-ink transition-colors aria-pressed:border-zoop-ink aria-pressed:bg-zoop-ink aria-pressed:text-zoop-paper disabled:cursor-not-allowed disabled:opacity-50 max-sm:flex-1 ${FOCUS_RING}`;
const LABELS = { morning: '출근', evening: '퇴근' };
const EDITIONS = ['morning', 'evening'] as const;
type Availability = 'published' | 'suspended' | 'absent' | 'unknown';

// History is ordered by scheduledAt descending. A cursor may split one day's two editions.
function dayComplete(
  rounds: BriefingRoundRef[],
  cursor: string | null,
  date: string,
) {
  return (
    cursor === null ||
    rounds.some((r) => r.date < date) ||
    EDITIONS.every((edition) =>
      rounds.some((r) => r.date === date && r.edition === edition),
    )
  );
}
function chooseEdition(
  rounds: BriefingRoundRef[],
  date: string,
  preferred: BriefingEdition,
) {
  const day = rounds.filter((r) => r.date === date);
  return (
    day.find((r) => r.edition === preferred && r.status === 'published')
      ?.edition ??
    day.find((r) => r.status === 'published')?.edition ??
    day.find((r) => r.edition === preferred)?.edition ??
    day[0]?.edition ??
    preferred
  );
}

const CONTROL = `h-[38px] rounded-[3px] border-[0.667px] border-zoop-line bg-zoop-paper px-3 text-caption text-zoop-ink max-sm:w-full ${FOCUS_RING}`;

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
  edition,
  onChange,
}: {
  date: string;
  edition: BriefingEdition;
  onChange: (date: string, edition: BriefingEdition) => void;
}) {
  const [state, setState] = useState<State>({
    rounds: [],
    nextCursor: null,
    loading: true,
    error: false,
  });

  const [selection, setSelection] = useState<{
    day: string;
    origin: string;
  } | null>(null);
  const routeKey = `${date}:${edition}`;
  const selecting = selection?.origin === routeKey ? selection.day : null;
  const selectionId = useRef(0);
  const pending = useRef(false);
  const mounted = useRef(true);
  const cursors = useRef(new Set<string>());
  const load = useCallback(async (cursor?: string) => {
    if (pending.current) return;
    pending.current = true;
    setState((old) => ({ ...old, loading: true, error: false }));
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
      return page;
    } catch {
      if (mounted.current)
        setState((old) => ({ ...old, loading: false, error: true }));
    } finally {
      pending.current = false;
    }
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

  useEffect(
    () => () => {
      selectionId.current += 1;
    },
    [date, edition],
  );

  async function selectDate(next: string) {
    const request = ++selectionId.current;
    setSelection({ day: next, origin: routeKey });
    let rounds = state.rounds;
    let cursor = state.nextCursor;
    const target =
      next || [...rounds].sort((a, b) => b.date.localeCompare(a.date))[0]?.date;
    // Complete the selected day before deciding that its other edition is absent.
    while (target && cursor && !dayComplete(rounds, cursor, target)) {
      const page = await load(cursor);
      if (!page || !mounted.current || request !== selectionId.current) break;
      rounds = [
        ...new Map([...rounds, ...page.items].map((r) => [r.id, r])).values(),
      ];
      cursor = page.nextCursor;
    }
    if (!mounted.current || request !== selectionId.current) return;
    onChange(next, target ? chooseEdition(rounds, target, edition) : edition);
    setSelection(null);
  }

  const complete =
    (!state.loading || state.rounds.length > 0) &&
    !(state.error && state.rounds.length === 0) &&
    date &&
    dayComplete(state.rounds, state.nextCursor, date);
  const availability = Object.fromEntries(
    EDITIONS.map((kind) => [
      kind,
      state.rounds.find((r) => r.date === date && r.edition === kind)?.status ??
        (complete ? 'absent' : 'unknown'),
    ]),
  ) as Record<BriefingEdition, Availability>;
  const notices = date
    ? EDITIONS.map((kind) =>
        availability[kind] === 'suspended'
          ? `${LABELS[kind]} 브리핑은 제공이 중단되었습니다.`
          : '',
      ).filter(Boolean)
    : [];

  const unknownNotice =
    date &&
    (availability.morning === 'unknown' || availability.evening === 'unknown')
      ? state.error
        ? '회차 이력을 불러오지 못해 발행 여부를 확인할 수 없습니다.'
        : state.loading
          ? '발행 회차를 확인하고 있어요.'
          : '아직 불러오지 않은 이력이 있어 일부 회차의 발행 여부를 확인할 수 없습니다.'
      : '';
  const message =
    selecting !== null
      ? '선택한 날짜의 발행 회차를 확인하고 있어요.'
      : [...notices, unknownNotice].filter(Boolean).join(' ');

  const dateControl =
    state.error && state.rounds.length === 0 ? (
      <div className="flex flex-col gap-1 max-sm:w-full">
        <label className="sr-only" htmlFor="briefing-date">
          날짜
        </label>
        <input
          id="briefing-date"
          type="date"
          value={selecting ?? date}
          disabled={selecting !== null}
          onChange={(event) => void selectDate(event.target.value)}
          className={CONTROL}
        />
        <p className="text-caption text-zoop-muted">
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
    ) : null;

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

  const historyControl = (
    <div className="flex flex-wrap items-center gap-2 max-sm:w-full">
      <label className="sr-only" htmlFor="briefing-date">
        발행일
      </label>
      <select
        id="briefing-date"
        value={selecting ?? date}
        disabled={state.loading || selecting !== null}
        onChange={(event) => void selectDate(event.target.value)}
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
          disabled={state.loading || selecting !== null}
          onClick={() => void load(state.nextCursor ?? undefined)}
          className={`shrink-0 text-caption text-zoop-muted underline underline-offset-4 hover:text-zoop-ink disabled:opacity-60 ${FOCUS_RING}`}
        >
          {state.loading ? (
            <>
              <LoadingSpinner size="sm" />
              <span className="sr-only">회차를 불러오고 있어요</span>
            </>
          ) : (
            '이전 회차 더 보기'
          )}
        </button>
      )}
      {state.error && state.rounds.length > 0 && (
        <p role="alert" className="text-caption text-zoop-alert">
          이전 회차를 불러오지 못했어요.
        </p>
      )}
    </div>
  );
  return (
    <div
      className="flex flex-wrap items-center gap-2.5 max-sm:w-full max-sm:items-stretch"
      aria-busy={selecting !== null}
    >
      {dateControl ?? historyControl}
      <div
        role="group"
        aria-label="출근·퇴근 발행 회차"
        aria-describedby={message ? 'briefing-round-availability' : undefined}
        className="flex flex-wrap gap-2 max-sm:w-full"
      >
        {EDITIONS.map((kind) => (
          <button
            key={kind}
            type="button"
            aria-pressed={edition === kind}
            disabled={selecting !== null || availability[kind] === 'absent'}
            onClick={() => {
              selectionId.current += 1;
              onChange(date, kind);
            }}
            className={EDITION_BUTTON}
          >
            {LABELS[kind]}
            {availability[kind] === 'absent'
              ? ' · 미발행'
              : availability[kind] === 'suspended'
                ? ' · 중단'
                : ''}
          </button>
        ))}
      </div>
      {message && (
        <p
          id="briefing-round-availability"
          role="status"
          className="w-full text-caption text-zoop-muted"
          aria-live="polite"
        >
          {(state.loading || selecting !== null) && (
            <LoadingSpinner size="sm" />
          )}{' '}
          {message}
        </p>
      )}
    </div>
  );
}
