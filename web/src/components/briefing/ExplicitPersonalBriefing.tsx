import { useEffect, useRef, useState } from 'react';
import { Link, useLocation } from 'react-router-dom';
import { call } from '@/apis/auth/ApiService';
import { selectMemberId, useAuthStore } from '@/stores/useAuthStore';
import type { BriefingItemDetail, BriefingResponse } from '@/types/briefing';
import IssueCentricBriefing from './IssueCentricBriefing';
import BriefingItemDetails from './BriefingItemDetails';
import {
  CARD,
  EMPTY,
  FOCUS_RING,
  NOTE,
  PRIMARY_BUTTON,
} from './briefingStyles';

type Options = {
  companies: { id: string; name: string }[];
  selectedIds: string[];
  importedBasis?: string;
};
export type Result = {
  roundId: string;
  dataAsOf: string;
  status: string;
  analysisStatus: string;
  eligibleCount: number;
  matchingCount: number;
  minimumShortfall: number;
  pendingAnalysisCount: number;
  choice: {
    companyIds: string[];
    maxIssues: number;
    minIssues: number;
    perCompanyLimit: number;
  };
  presentation: BriefingResponse;
  verifiedPresentation?: BriefingResponse;
  selectionVersion: string;
  details: Record<string, BriefingItemDetail>;
  tracking: {
    issueId: string;
    title: string;
    previousRoundId: string;
    nextCheck: string;
    status: string;
  }[];
};
type Generation = {
  id: string;
  status: string;
  selectionVersion: string;
  attempt?: number;
  selection?: Result;
  outcome?: {
    withheld?: { issueId: string; reason: string }[];
    newCalls?: number;
  };
};
const activeGeneration = (g?: Generation) =>
  !!g && ['queued', 'running'].includes(g.status);
/** D-BRF-01/02: explicit choice first. No account import, selection or paid generation on mount. */
export default function ExplicitPersonalBriefing({
  round,
  compact,
}: {
  round: BriefingResponse;
  compact: boolean;
}) {
  const location = useLocation();
  const memberId = useAuthStore(selectMemberId);
  const revision = useAuthStore((s) => s.sessionRevision);
  const email = useAuthStore((s) => s.member?.email);
  const [options, setOptions] = useState<Options>();
  const [selected, setSelected] = useState<string[]>([]);
  const [search, setSearch] = useState('');
  const [max, setMax] = useState(3),
    [min, setMin] = useState(0),
    [per, setPer] = useState(3);
  const [result, setResult] = useState<Result>();
  const [generation, setGeneration] = useState<Generation>();
  const [error, setError] = useState('');
  const [busy, setBusy] = useState(false);
  const [editing, setEditing] = useState(true);
  const current = useRef(0);
  useEffect(() => {
    const pending = current;
    const version = ++pending.current;
    if (memberId)
      call<Options>('/api/v1/briefings/personalization/options', 'GET')
        .then((value) => {
          if (current.current === version) setOptions(value);
        })
        .catch(() => {
          if (current.current === version)
            setError('종목 목록을 불러오지 못했어요.');
        });
    return () => {
      pending.current++;
    };
  }, [memberId, revision]);
  const validSession = () =>
    useAuthStore.getState().sessionRevision === revision &&
    useAuthStore.getState().member?.id === memberId;
  async function importMine() {
    setBusy(true);
    setError('');
    try {
      const value = await call<Options>(
        '/api/v1/briefings/personalization/options?importMine=true',
        'GET',
      );
      if (!validSession()) return;
      setSelected(value.selectedIds.slice(0, 20));
      setOptions(value);
      if (!value.selectedIds.length)
        setError(
          '불러올 보유·관심 종목이 없습니다. 아래에서 직접 선택해 주세요.',
        );
    } catch {
      if (validSession())
        setError(
          '보유·관심 종목을 불러오지 못했어요. 직접 선택할 수 있습니다.',
        );
    } finally {
      if (validSession()) setBusy(false);
    }
  }
  function acceptSelection(
    value: Result,
    ids: string[],
    expectedVersion?: string,
  ) {
    if (
      value.roundId !== round.id ||
      Date.parse(value.dataAsOf) !== Date.parse(round.dataAsOf ?? '') ||
      JSON.stringify(value.choice.companyIds) !== JSON.stringify(ids) ||
      (expectedVersion !== undefined &&
        value.selectionVersion !== expectedVersion)
    )
      throw new Error('basis_changed');
  }
  const expectedScope = JSON.stringify(result?.choice.companyIds ?? []);
  useEffect(() => {
    if (!generation || !activeGeneration(generation)) return;
    let live = true;
    const timer = setTimeout(() => {
      void call<Generation>(
        `/api/v1/briefings/${encodeURIComponent(round.id)}/personalized/generations/${encodeURIComponent(generation.id)}`,
        'GET',
      )
        .then((value) => {
          if (
            !live ||
            useAuthStore.getState().sessionRevision !== revision ||
            useAuthStore.getState().member?.id !== memberId
          )
            return;
          if (value.selectionVersion !== generation.selectionVersion)
            throw new Error('basis_changed');
          if (value.status === 'stale') {
            setError(
              '회차나 후보 기준이 바뀌었어요. 종목과 회차를 다시 확인해 주세요.',
            );
            setGeneration(value);
            return;
          }
          if (value.selection) {
            if (
              JSON.stringify(value.selection.choice.companyIds) !==
              expectedScope
            )
              throw new Error('basis_changed');
            acceptSelection(
              value.selection,
              value.selection.choice.companyIds,
              generation.selectionVersion,
            );
            setResult(value.selection);
          }
          setGeneration(value);
        })
        .catch(() => {
          if (live)
            setError(
              '생성 진행 상태를 확인하지 못했어요. 다시 확인하면 같은 작업을 조회합니다.',
            );
        });
    }, 1500);
    return () => {
      live = false;
      clearTimeout(timer);
    };
    // A new response schedules the next read; unmount/account/round changes cancel polling.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [generation, round.id, round.dataAsOf, memberId, revision, expectedScope]);
  async function retryWithheld() {
    if (!generation) return;
    setBusy(true);
    setError('');
    try {
      const next = await call<Generation>(
        `/api/v1/briefings/${encodeURIComponent(round.id)}/personalized/generations/${encodeURIComponent(generation.id)}/retry`,
        'POST',
      );
      if (!validSession()) return;
      if (next.selectionVersion !== generation.selectionVersion)
        throw new Error('basis_changed');
      setGeneration(next);
    } catch {
      if (validSession())
        setError(
          '보완 작업을 시작하지 못했어요. 원래 결과와 실행 기록은 보존됩니다.',
        );
    } finally {
      if (validSession()) setBusy(false);
    }
  }
  async function generate() {
    setBusy(true);
    setError('');
    setGeneration(undefined);
    const ids = [...selected].sort();
    try {
      const value = await call<Result>(
        `/api/v1/briefings/${encodeURIComponent(round.id)}/personalized/selection`,
        'POST',
        {
          companyIds: ids,
          maxIssues: max,
          minIssues: min,
          perCompanyLimit: per,
        },
      );
      if (!validSession()) return;
      acceptSelection(value, ids);
      setResult(value);
      setEditing(false);
      if (value.pendingAnalysisCount > 0) {
        const job = await call<Generation>(
          `/api/v1/briefings/${encodeURIComponent(round.id)}/personalized/generations`,
          'POST',
          { choice: value.choice, selectionVersion: value.selectionVersion },
        );
        if (!validSession()) return;
        if (job.selectionVersion !== value.selectionVersion)
          throw new Error('basis_changed');
        if (job.selection) {
          acceptSelection(job.selection, ids, value.selectionVersion);
          setResult(job.selection);
        }
        setGeneration(job);
      }
    } catch {
      if (validSession())
        setError(
          '선택 결과 또는 생성 작업을 확인하지 못했어요. 완료 기록은 보존됩니다.',
        );
    } finally {
      if (validSession()) setBusy(false);
    }
  }
  if (!memberId)
    return (
      <div className={`${CARD} space-y-3`}>
        <h2 className="font-bold">개인화 브리핑</h2>
        <p>로그인한 회원이 기준 종목을 직접 선택해 만드는 브리핑입니다.</p>
        <Link
          className={`inline-block underline ${FOCUS_RING}`}
          to="/login"
          state={{ from: location }}
        >
          로그인 후 개인화 브리핑 만들기
        </Link>
      </div>
    );
  const names = (ids: string[]) =>
    ids
      .map((id) => options?.companies.find((c) => c.id === id)?.name ?? id)
      .join(' · ');
  return (
    <section
      className={`${CARD} space-y-4`}
      aria-label="개인화 브리핑 만들기"
      data-screen-id="D-BRF-01 D-BRF-02"
    >
      <header>
        <h2 className="text-lg font-bold">개인화 브리핑</h2>
        <p className={NOTE}>
          로그인 계정: {email ?? '회원'} · {round.date}{' '}
          {round.edition === 'morning' ? '출근' : '퇴근'}
        </p>
      </header>
      {editing && (
        <form
          onSubmit={(e) => {
            e.preventDefault();
            void generate();
          }}
          className="space-y-4"
        >
          <div className="flex flex-wrap items-center gap-3">
            <h3 className="font-semibold">1. 기준 종목 선택</h3>
            <button
              type="button"
              className={`text-xs underline ${FOCUS_RING}`}
              disabled={busy}
              onClick={() => void importMine()}
            >
              보유·관심 종목 불러오기
            </button>
          </div>
          {options?.importedBasis && (
            <p className={NOTE}>
              연결된 모의 계좌 보유 종목과 관심 종목을 불러왔습니다. 필요한
              종목만 남겨 주세요.
            </p>
          )}
          <label className="block text-sm">
            종목 검색
            <input
              className={`mt-1 w-full rounded border border-zoop-line p-2 ${FOCUS_RING}`}
              value={search}
              onChange={(e) => setSearch(e.target.value)}
              placeholder="기업명 또는 종목 코드"
            />
          </label>
          <fieldset
            disabled={busy}
            className="max-h-64 overflow-y-auto rounded border border-zoop-line p-3"
          >
            <legend className="text-xs">종목 선택 · 최대 20개</legend>
            {!options && <p role="status">종목 목록을 확인하고 있어요.</p>}
            {options?.companies
              .filter((c) =>
                `${c.name} ${c.id}`
                  .toLowerCase()
                  .includes(search.toLowerCase()),
              )
              .map((c) => (
                <label
                  key={c.id}
                  className="flex min-h-11 cursor-pointer items-center gap-3 text-sm"
                >
                  <input
                    type="checkbox"
                    checked={selected.includes(c.id)}
                    disabled={!selected.includes(c.id) && selected.length >= 20}
                    onChange={(e) =>
                      setSelected((ids) =>
                        e.target.checked
                          ? [...ids, c.id]
                          : ids.filter((id) => id !== c.id),
                      )
                    }
                  />
                  <span>
                    {c.name} <span className={NOTE}>{c.id}</span>
                  </span>
                </label>
              ))}
          </fieldset>
          <p className="text-sm" role="status">
            선택 {selected.length}개
            {selected.length > 0 ? `: ${names(selected)}` : ''}
          </p>
          <details>
            <summary className={`cursor-pointer text-sm ${FOCUS_RING}`}>
              추가 설정 · 이슈 수
            </summary>
            <div className="mt-3 flex flex-wrap gap-4">
              <label>
                최대 핵심 이슈{' '}
                <select
                  aria-label="최대 핵심 이슈"
                  value={max}
                  onChange={(e) => {
                    const n = Number(e.target.value);
                    setMax(n);
                    setMin((v) => Math.min(v, n));
                  }}
                >
                  {[1, 2, 3].map((n) => (
                    <option key={n}>{n}</option>
                  ))}
                </select>
              </label>
              <label>
                최소 희망 이슈{' '}
                <select
                  aria-label="최소 희망 이슈"
                  value={min}
                  onChange={(e) => setMin(Number(e.target.value))}
                >
                  {Array.from({ length: max + 1 }, (_, n) => (
                    <option key={n}>{n}</option>
                  ))}
                </select>
              </label>
              <label>
                종목당 최대{' '}
                <select
                  aria-label="종목당 최대"
                  value={per}
                  onChange={(e) => setPer(Number(e.target.value))}
                >
                  {[1, 2, 3].map((n) => (
                    <option key={n}>{n}</option>
                  ))}
                </select>
              </label>
            </div>
            <p className={`${NOTE} mt-2`}>
              희망 개수보다 적격 이슈가 적으면 실제 개수만 제공합니다.
              중요도·근거·재보도 검증은 유지합니다.
            </p>
          </details>
          <button
            disabled={busy || !options || selected.length === 0}
            className={`${PRIMARY_BUTTON} disabled:opacity-40`}
          >
            {busy
              ? '선정·생성 작업을 준비하고 있어요…'
              : '2. 선택 종목으로 브리핑 만들기'}
          </button>
          <p className={NOTE}>
            전체 적격 후보에서 관련 이슈를 선정하고 공통 브리핑과 같은 검증된
            분석·시세·근거를 사용합니다. 기존 검증본은 재사용하고 분석이 없는
            이슈만 AI 생성·검증합니다.
          </p>
        </form>
      )}
      {activeGeneration(generation) && (
        <p role="status" className={EMPTY}>
          선택한 종목·회차를 유지해{' '}
          {generation?.status === 'queued'
            ? 'AI 분석을 기다리고 있어요.'
            : '새 분석을 생성·독립 검증하고 있어요.'}{' '}
          화면을 다시 확인해도 같은 작업을 재사용합니다.
        </p>
      )}
      {generation &&
        !activeGeneration(generation) &&
        !['ready', 'stale'].includes(generation.status) && (
          <p role="status" className={EMPTY}>
            생성 결과:{' '}
            {generation.status === 'partial'
              ? '일부 통과·일부 보류'
              : generation.status === 'withheld'
                ? '근거 검증 보류'
                : generation.status === 'budget_exhausted'
                  ? '승인된 호출·비용 한도 도달'
                  : '실행 기록 확인 필요'}
            . 통과한 결과와 기존 근거는 유지됩니다.
          </p>
        )}
      {generation &&
        ['partial', 'withheld'].includes(generation.status) &&
        (generation.attempt ?? 1) < 2 && (
          <button
            className={PRIMARY_BUTTON}
            disabled={busy}
            onClick={() => void retryWithheld()}
          >
            보류 항목만 보완·재검증
          </button>
        )}
      {error && (
        <p role="alert" className={EMPTY}>
          {error}
        </p>
      )}
      {result && !editing && (
        <>
          <div className="rounded border border-zoop-line p-3">
            <p className="font-semibold">
              선택한 종목: {names(result.choice.companyIds)}
            </p>
            <p className={NOTE}>
              전체 적격 {result.eligibleCount}개 → 관련 {result.matchingCount}개
              → 핵심 {result.presentation.items.length}개 · 공통과 같은
              중요도·새 정보·중복 검증
            </p>
            <button
              className={`mt-2 text-xs underline ${FOCUS_RING}`}
              onClick={() => {
                setEditing(true);
                setGeneration(undefined);
                setError('');
              }}
            >
              종목·조건 다시 선택
            </button>
          </div>
          {result.minimumShortfall > 0 && (
            <p role="status" className={EMPTY}>
              희망한 최소 개수보다 {result.minimumShortfall}개 부족합니다.
              기준을 통과하지 않은 이슈로 채우지 않았습니다.
            </p>
          )}
          {result.analysisStatus === 'needs_generation' && (
            <p role="status" className={EMPTY}>
              {result.pendingAnalysisCount}개 이슈는 선정·근거 확인을 통과했으나
              공통 기준 AI 분석 저장본이 없습니다. 이 항목의 전망은 아직
              제공하지 않습니다.
            </p>
          )}
          <IssueCentricBriefing
            key={JSON.stringify(result.choice)}
            result={result.verifiedPresentation ?? result.presentation}
            compact={compact}
            selectionDetails={result.details}
          />
          {result.verifiedPresentation &&
            result.presentation.items
              .filter(
                (item) =>
                  !result.verifiedPresentation!.items.some(
                    (ready) => ready.eventId === item.eventId,
                  ),
              )
              .map((item) => (
                <article
                  key={item.eventId}
                  className="rounded border border-zoop-line p-4"
                >
                  <h3 className="font-semibold">
                    분석 대기·보류: {item.title}
                  </h3>
                  <p className={NOTE}>
                    {generation?.outcome?.withheld?.find(
                      (w) => w.issueId === item.eventId,
                    )?.reason ??
                      '확인된 원문과 선정 근거는 유지하며, 검증을 통과한 새 분석만 제공합니다.'}
                  </p>
                  <BriefingItemDetails
                    roundId={round.id}
                    graphVersion={null}
                    item={item}
                    initialDetail={result.details[item.eventId]}
                    evidenceOnly
                  />
                </article>
              ))}
          <details>
            <summary className={`cursor-pointer text-sm ${FOCUS_RING}`}>
              이전 이슈와 확인사항 ({result.tracking.length})
            </summary>
            {result.tracking.map((t) => (
              <div
                className="mt-3 border-t border-zoop-line pt-3 text-sm"
                key={t.issueId}
              >
                <strong>{t.title}</strong>
                <p>{t.nextCheck || '저장된 확인 조건이 없습니다.'}</p>
                <p className={NOTE}>
                  이전 회차의 확인 과제입니다. 충족 여부를 새로 검증한 결과는
                  아닙니다.
                </p>
              </div>
            ))}
          </details>
        </>
      )}
    </section>
  );
}
