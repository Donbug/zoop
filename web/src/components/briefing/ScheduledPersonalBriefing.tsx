import { useEffect, useRef, useState } from 'react';
import { Link, useLocation } from 'react-router-dom';
import { call } from '@/apis/auth/ApiService';
import { selectMemberId, useAuthStore } from '@/stores/useAuthStore';
import CompanyLogo from '@/components/common/CompanyLogo';
import type { BriefingResponse } from '@/types/briefing';
import type { Result } from './ExplicitPersonalBriefing';
import IssueCentricBriefing from './IssueCentricBriefing';
import BriefingItemDetails from './BriefingItemDetails';
import {
  CARD,
  EMPTY,
  FOCUS_RING,
  NOTE,
  PRIMARY_BUTTON,
} from './briefingStyles';

type Choice = Result['choice'];
type Company = { id: string; name: string; logoUrl?: string | null };
type Settings = {
  demoEnabled: boolean;
  initializationStatus?: string;
  nextScheduledAt: string;
  preference: null | {
    revisionId: string;
    choice: Choice;
    effectiveFrom: string;
  };
};
type Delivery = {
  id?: string;
  status: string;
  mode?: 'scheduled' | 'demo';
  roundId: string;
  preferenceRevision?: string;
  selection?: Result;
};
const SETTINGS = '/api/v1/briefings/personalization/settings';
const defaultChoice: Choice = {
  companyIds: [],
  maxIssues: 3,
  minIssues: 0,
  perCompanyLimit: 3,
};
const kst = (value: string) =>
  new Intl.DateTimeFormat('ko-KR', {
    timeZone: 'Asia/Seoul',
    month: 'numeric',
    day: 'numeric',
    hour: '2-digit',
    minute: '2-digit',
    hour12: false,
  }).format(new Date(value));

/** D-BRF-01/02. Settings writes never generate or replace an existing round. */
export default function ScheduledPersonalBriefing({
  round,
  compact,
}: {
  round: BriefingResponse;
  compact: boolean;
}) {
  const member = useAuthStore(selectMemberId);
  const revision = useAuthStore((s) => s.sessionRevision);
  const location = useLocation();
  const [settings, setSettings] = useState<Settings>();
  const [companies, setCompanies] = useState<Company[]>([]);
  const [choice, setChoice] = useState<Choice>(defaultChoice);
  const [editing, setEditing] = useState(false);
  const [picker, setPicker] = useState(false);
  const [search, setSearch] = useState('');
  const [delivery, setDelivery] = useState<Delivery>();
  const [preview, setPreview] = useState<Delivery>();
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState('');
  const [notice, setNotice] = useState('');
  const epoch = useRef(0);
  const path = `/api/v1/briefings/${encodeURIComponent(round.id)}/personalized`;
  const valid = () =>
    useAuthStore.getState().member?.id === member &&
    useAuthStore.getState().sessionRevision === revision;
  useEffect(() => {
    const pendingScope = epoch;
    const token = ++pendingScope.current;
    if (member) {
      void Promise.all([
        call<Settings>(`${SETTINGS}/initialize`, 'POST'),
        call<{ companies: Company[] }>(
          '/api/v1/briefings/personalization/options',
          'GET',
        ),
        call<Delivery>(`${path}/delivery`, 'GET').catch(() => ({
          status: 'unavailable',
          roundId: round.id,
        })),
      ])
        .then(([saved, options, published]) => {
          if (epoch.current !== token) return;
          setSettings(saved);
          setCompanies(options.companies);
          setChoice(saved.preference?.choice ?? defaultChoice);
          setEditing(false);
          if (saved.initializationStatus === 'initialized')
            setNotice(
              '보유·관심 종목으로 기본 설정했습니다. 다음 회차부터 적용합니다.',
            );
          setDelivery(published);
          if (saved.demoEnabled)
            void call<Delivery>(`${path}/delivery?demo=true`, 'GET')
              .then((p) => {
                if (epoch.current === token) setPreview(p);
              })
              .catch(() => {
                if (epoch.current === token)
                  setError('데모 기록을 불러오지 못했어요.');
              });
        })
        .catch(() => {
          if (epoch.current === token)
            setError('개인화 설정이나 발행 기록을 불러오지 못했어요.');
        });
    }
    return () => {
      pendingScope.current++;
    };
  }, [member, revision, path, round.id]);
  const pending =
    delivery?.status === 'generating' || preview?.status === 'generating';
  useEffect(() => {
    if (!pending) return;
    let live = true;
    const timer = setTimeout(() => {
      void Promise.all([
        call<Delivery>(`${path}/delivery`, 'GET'),
        settings?.demoEnabled
          ? call<Delivery>(`${path}/delivery?demo=true`, 'GET')
          : Promise.resolve(undefined),
      ])
        .then(([saved, demo]) => {
          if (
            live &&
            useAuthStore.getState().member?.id === member &&
            useAuthStore.getState().sessionRevision === revision
          ) {
            setDelivery(saved);
            if (demo) setPreview(demo);
          }
        })
        .catch(() => {
          if (live) setError('발행 진행 상태를 확인하지 못했어요.');
        });
    }, 2000);
    return () => {
      live = false;
      clearTimeout(timer);
    };
  }, [
    pending,
    delivery,
    preview,
    path,
    member,
    revision,
    settings?.demoEnabled,
  ]);
  async function save() {
    setBusy(true);
    setError('');
    try {
      const saved = await call<Settings>(SETTINGS, 'PUT', {
        choice: {
          ...choice,
          companyIds: [...choice.companyIds].sort(),
          maxIssues: 3,
          minIssues: 0,
          perCompanyLimit: 3,
        },
        expectedRevision: settings?.preference?.revisionId ?? null,
      });
      if (!valid()) return;
      setSettings(saved);
      setChoice(saved.preference!.choice);
      setEditing(false);
      setPicker(false);
      setNotice(
        `${kst(saved.preference!.effectiveFrom)} 회차부터 적용합니다. 이미 나온 브리핑은 유지됩니다.`,
      );
    } catch {
      if (valid())
        setError(
          '설정을 저장하지 못했어요. 다른 창에서 바꿨다면 새로고침 후 확인해 주세요.',
        );
    } finally {
      if (valid()) setBusy(false);
    }
  }
  async function importMine() {
    setBusy(true);
    setError('');
    try {
      const options = await call<{ selectedIds: string[] }>(
        '/api/v1/briefings/personalization/options?importMine=true',
        'GET',
      );
      if (valid()) {
        setChoice((c) => ({
          ...c,
          companyIds: options.selectedIds,
        }));
        setNotice(
          '보유·관심 종목을 선택에 넣었습니다. 설정 저장 후 적용됩니다.',
        );
      }
    } catch {
      if (valid()) setError('보유·관심 종목을 불러오지 못했어요.');
    } finally {
      if (valid()) setBusy(false);
    }
  }
  async function demo() {
    if (!settings?.preference) return;
    setBusy(true);
    setError('');
    try {
      const result = await call<Delivery>(`${path}/demo`, 'POST', {
        preferenceRevision: settings.preference.revisionId,
      });
      if (valid()) setPreview(result);
    } catch {
      if (valid())
        setError('데모를 준비하지 못했어요. 기존 발행본은 유지됩니다.');
    } finally {
      if (valid()) setBusy(false);
    }
  }
  if (!member)
    return (
      <div className={`${CARD} space-y-3`}>
        <h2 className="font-bold">개인화 브리핑</h2>
        <p>로그인하고 기준 종목을 설정하면 회차마다 브리핑을 제공합니다.</p>
        <Link
          to="/login"
          state={{ from: location }}
          className={`underline ${FOCUS_RING}`}
        >
          로그인 후 개인화 브리핑 설정
        </Link>
      </div>
    );
  const chips = (ids: string[]) => (
    <div className="flex flex-wrap gap-2">
      {ids.map((id) => {
        const c = companies.find((x) => x.id === id);
        return (
          <span
            key={id}
            className="inline-flex items-center gap-2 rounded-full border border-zoop-line px-3 py-1 text-sm"
          >
            <CompanyLogo
              name={c?.name ?? id}
              logoUrl={c?.logoUrl}
              className="size-6 rounded-full bg-zoop-surface"
            />
            {c?.name ?? id}
          </span>
        );
      })}
    </div>
  );
  const published = delivery?.selection ? delivery : undefined;
  return (
    <section className="space-y-5" data-screen-id="D-BRF-01 D-BRF-02">
      <section className={`${CARD} space-y-4`} aria-label="개인화 브리핑 설정">
        <header className="flex items-center justify-between gap-3">
          <div>
            <h2 className="text-lg font-bold">나의 브리핑 설정</h2>
            <p className={NOTE}>
              매일 09:20 · 17:30 기준으로 자동 제공해요. 보유·관심 종목이 없으면
              새 브리핑을 만들지 않아요.
            </p>
          </div>
          {settings && (
            <button
              type="button"
              className={`shrink-0 text-sm underline ${FOCUS_RING}`}
              onClick={() => {
                setChoice(settings.preference?.choice ?? defaultChoice);
                setEditing((v) => !v);
                setPicker(false);
              }}
            >
              {settings.preference ? '설정 변경' : '종목 설정'}
            </button>
          )}
        </header>
        {!settings && !error && <p role="status">설정을 불러오고 있어요.</p>}
        {settings?.preference && !editing && (
          <>
            {chips(settings.preference.choice.companyIds)}
            <p className={NOTE}>
              {kst(settings.preference.effectiveFrom)} 회차부터 적용 · 핵심 최대{' '}
              {settings.preference.choice.maxIssues}개
            </p>
          </>
        )}
        {settings && !settings.preference && !editing && (
          <p className={NOTE}>
            보유·관심 종목이 없어 개인화 브리핑을 제공하지 않습니다.{' '}
            <Link to="/my" className="underline">
              내 종목 설정
            </Link>
          </p>
        )}
        {editing && (
          <form
            className="space-y-4"
            onSubmit={(e) => {
              e.preventDefault();
              void save();
            }}
          >
            <label className="block text-sm">
              기준 종목 검색
              <input
                value={search}
                onFocus={() => setPicker(true)}
                onClick={() => setPicker(true)}
                onChange={(e) => {
                  setSearch(e.target.value);
                  setPicker(true);
                }}
                onKeyDown={(e) => {
                  if (e.key === 'Escape') setPicker(false);
                }}
                role="combobox"
                aria-haspopup="dialog"
                aria-autocomplete="list"
                aria-expanded={picker}
                aria-controls="personal-stock-picker"
                placeholder="클릭해서 기업명 또는 종목 코드 검색"
                className={`mt-2 w-full rounded-lg border border-zoop-line p-3 ${FOCUS_RING}`}
              />
            </label>
            {picker && (
              <fieldset
                id="personal-stock-picker"
                role="dialog"
                aria-label="기준 종목 선택"
                disabled={busy}
                className="max-h-64 overflow-y-auto rounded-lg border border-zoop-line p-3"
              >
                <legend className="text-xs">기준 종목 선택</legend>
                <div className="flex justify-end">
                  <button
                    type="button"
                    onClick={() => setPicker(false)}
                    className={`text-sm underline ${FOCUS_RING}`}
                  >
                    목록 닫기
                  </button>
                </div>
                {companies
                  .filter((c) =>
                    `${c.name} ${c.id}`
                      .toLowerCase()
                      .includes(search.toLowerCase()),
                  )
                  .map((c) => (
                    <label
                      key={c.id}
                      className="flex min-h-12 cursor-pointer items-center gap-3 text-sm"
                    >
                      <input
                        type="checkbox"
                        aria-label={`${c.name} ${c.id}`}
                        checked={choice.companyIds.includes(c.id)}
                        disabled={
                          !choice.companyIds.includes(c.id) &&
                          choice.companyIds.length >= 1000
                        }
                        onChange={(e) =>
                          setChoice((v) => ({
                            ...v,
                            companyIds: e.target.checked
                              ? [...v.companyIds, c.id]
                              : v.companyIds.filter((id) => id !== c.id),
                          }))
                        }
                      />
                      <CompanyLogo
                        name={c.name}
                        logoUrl={c.logoUrl}
                        className="size-8 rounded-full bg-zoop-surface"
                      />
                      <span>
                        {c.name}
                        <span className={`ml-2 ${NOTE}`}>{c.id}</span>
                      </span>
                    </label>
                  ))}
                {!companies.some((c) =>
                  `${c.name} ${c.id}`
                    .toLowerCase()
                    .includes(search.toLowerCase()),
                ) && <p className={NOTE}>검색 결과가 없습니다.</p>}
              </fieldset>
            )}
            {chips(choice.companyIds)}
            <button
              type="button"
              disabled={busy}
              onClick={() => void importMine()}
              className={`text-sm underline ${FOCUS_RING}`}
            >
              보유·관심 종목 불러오기
            </button>
            <p className={NOTE}>
              저장한 설정은 다음 회차부터 적용합니다. 이미 발행된 브리핑은
              변경되지 않습니다.
            </p>
            <button
              disabled={busy || choice.companyIds.length === 0}
              className={`${PRIMARY_BUTTON} disabled:opacity-40`}
            >
              {busy ? '저장 중…' : '브리핑 설정 저장'}
            </button>
          </form>
        )}
        {notice && (
          <p role="status" className={NOTE}>
            {notice}
          </p>
        )}
        {error && (
          <p role="alert" className={EMPTY}>
            {error}
          </p>
        )}
      </section>
      <section className="space-y-4" aria-label="발행된 개인화 브리핑">
        <h2 className="text-lg font-bold">
          {round.date} {round.edition === 'morning' ? '출근' : '퇴근'} 브리핑
        </h2>
        {delivery?.status === 'generating' && (
          <p role="status" className={EMPTY}>
            이 회차의 분석을 생성·검증하고 있어요. 확인된 사실·근거를 먼저
            제공합니다.
          </p>
        )}
        {delivery &&
          ['partial', 'withheld', 'failed'].includes(delivery.status) && (
            <p role="status" className={EMPTY}>
              이 회차는 일부 분석이 보류됐습니다. 검증된 분석과 확인된 근거를
              구분해서 제공합니다.
            </p>
          )}
        {published ? (
          <>
            <div className={NOTE}>이 회차에 고정된 기준 종목</div>
            {chips(published.selection!.choice.companyIds)}
            <PersonalResult result={published.selection!} compact={compact} />
          </>
        ) : (
          <p role="status" className={EMPTY}>
            {delivery?.status === 'unavailable'
              ? '이 회차의 발행 기록을 불러오지 못했어요. 설정은 계속 변경할 수 있습니다.'
              : delivery?.status === 'generating'
                ? '회차 기준으로 분석을 생성·검증하고 있어요. 완료되면 자동으로 표시됩니다.'
                : '이 회차에 발행된 개인화 브리핑이 없습니다. 설정 저장 이후의 회차부터 제공합니다.'}
          </p>
        )}
      </section>
      {settings?.demoEnabled && (
        <details className={`${CARD} space-y-3`}>
          <summary className={`cursor-pointer text-sm ${FOCUS_RING}`}>
            데모 미리보기
          </summary>
          <p className={`${NOTE} mt-3`}>
            현재 저장한 설정으로 이 과거 회차를 시험합니다. 정식 자동 발행본과
            별도로 보존하며, 운영 화면에는 이 실행 버튼이 없습니다.
          </p>
          <button
            type="button"
            disabled={
              busy || !settings.preference || preview?.status === 'generating'
            }
            className={`${PRIMARY_BUTTON} mt-3 disabled:opacity-40`}
            onClick={() => void demo()}
          >
            현재 설정으로 데모 보기
          </button>
          {preview?.selection && (
            <div className="mt-4 space-y-3">
              <p className={NOTE}>별도 데모 기록 · 이 회차에서 시험한 종목</p>
              {chips(preview.selection.choice.companyIds)}
              <PersonalResult result={preview.selection} compact={compact} />
            </div>
          )}
          {preview?.status === 'generating' && (
            <p role="status" className={EMPTY}>
              데모 분석을 생성·검증 중입니다.
            </p>
          )}
        </details>
      )}
    </section>
  );
}
function PersonalResult({
  result,
  compact,
}: {
  result: Result;
  compact: boolean;
}) {
  return (
    <>
      <IssueCentricBriefing
        result={result.verifiedPresentation ?? result.presentation}
        compact={compact}
        selectionDetails={result.details}
      />
      {result.verifiedPresentation &&
        result.presentation.items
          .filter(
            (i) =>
              !result.verifiedPresentation!.items.some(
                (r) => r.eventId === i.eventId,
              ),
          )
          .map((item) => (
            <article key={item.eventId} className={`${CARD} space-y-3`}>
              <h3 className="font-semibold">분석 보류 · {item.title}</h3>
              <BriefingItemDetails
                roundId={result.roundId}
                graphVersion={null}
                item={item}
                initialDetail={result.details[item.eventId]}
                evidenceOnly
              />
            </article>
          ))}
      {result.minimumShortfall > 0 && (
        <p className={NOTE}>
          희망 개수보다 {result.minimumShortfall}개 적습니다. 적격 이슈만
          제공합니다.
        </p>
      )}
      <details>
        <summary className={`cursor-pointer text-sm ${FOCUS_RING}`}>
          이전 이슈와 확인사항 ({result.tracking.length})
        </summary>
        {result.tracking.map((t) => (
          <div key={t.issueId} className="mt-3 space-y-1 text-sm">
            <strong>{t.title}</strong>
            <p>{t.nextCheck || '저장된 확인 조건이 없습니다.'}</p>
            <p className={NOTE}>
              이전 회차의 확인 과제이며 충족 여부를 새로 검증한 결과는 아닙니다.
            </p>
          </div>
        ))}
      </details>
    </>
  );
}
