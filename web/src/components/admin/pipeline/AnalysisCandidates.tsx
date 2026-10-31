import { useCallback, useState } from 'react';
import { listAnalysisCandidates } from '@/apis/admin/pipeline';
import {
  Empty,
  ErrorBox,
  Loading,
  MoreButton,
  Note,
  Segmented,
  Table,
} from '@/components/admin/common/AdminUi';
import {
  SEARCH_INPUT,
  TD,
  TH,
  count,
} from '@/components/admin/common/adminStyles';
import CandidateDetailPanel from '@/components/admin/pipeline/CandidateDetailPanel';
import { useCursorPages } from '@/hooks/useCursorPages';
import { useDebouncedValue } from '@/hooks/useDebouncedValue';
import { useRouteQuery } from '@/hooks/useRouteQuery';
import { useAdminSessionStore } from '@/stores/useAdminSessionStore';
import type { CandidateFilters, CandidateStatus } from '@/types/admin/pipeline';
import {
  candidateStatusLabel,
  decisionLabel,
} from '@/components/admin/pipeline/candidateLabels';

type StatusFilter = CandidateStatus | 'all';

const parseStatus = (value: string | null): StatusFilter =>
  value === 'all' || value === 'ALLOW' || value === 'REJECT' ? value : 'HOLD';

const SCOPE_OPTIONS: { value: 'all' | 'rule'; label: string }[] = [
  { value: 'all', label: '모든 후보' },
  { value: 'rule', label: '규칙 대상만' },
];

function StatusIcon({ status }: { status: CandidateStatus }) {
  return (
    <svg
      aria-hidden="true"
      viewBox="0 0 16 16"
      fill="none"
      stroke="currentColor"
      strokeWidth="1.4"
      strokeLinecap="round"
      className="size-3.5 shrink-0"
    >
      <circle cx="8" cy="8" r="6" />
      {status === 'ALLOW' && <path d="m5.5 8.2 1.7 1.7 3.3-3.6" />}
      {status === 'HOLD' && <path d="m6 6 4 4m0-4-4 4" />}
      {status === 'REJECT' && <path d="m4 12 8-8" />}
    </svg>
  );
}

function HiddenIcon() {
  return (
    <svg
      aria-hidden="true"
      viewBox="0 0 16 16"
      fill="none"
      stroke="currentColor"
      strokeWidth="1.3"
      strokeLinecap="round"
      className="size-3.5 shrink-0"
    >
      <path d="M2 8s2.2-4 6-4 6 4 6 4-2.2 4-6 4-6-4-6-4Z" />
      <circle cx="8" cy="8" r="1.8" />
      <path d="m3 13 10-10" />
    </svg>
  );
}

// A-ADM-03 후보 탭 (FS067-01·FS067-02, listAnalysisCandidates·getAnalysisCandidate)
// - 프로토타입 admin/pipeline/candidates.tsx를 옮겼다. 필터·검색어·고른 후보(?candidate=)는 주소에 남는다.
// - 판정 기본값은 프로토타입처럼 보류(HOLD)다. 조건이 바뀌면 첫 쪽부터 다시 읽는다(커서는 같은 조건에서만 유효).
// - 와이어프레임대로 [판정] [모든 후보 | 규칙 대상만] 필터와 검색만 둔다. 규칙 대상(?rule=true)은 listAnalysisCandidates의 rule 조건이다.
//   앱이 아직 규칙을 후보에 평가하지 않아(rule=null) 지금은 규칙 대상만 고르면 빈 목록이 온다.
// - 허용·거부 결정은 상세에서 관계마다 한다(decideAnalysisCandidate).
// - 목록의 onUserGraph=false는 공개하지 않은 후보와 공개 여부를 확인하지 못한 후보를 함께 뜻해서, 단정하지 않고 상세에서 구분한다.
// 표시 버전이 바뀌면(graphRevision) 공개 표시 상태가 달라지므로 목록·상세를 다시 읽는다. 필터·고른 후보는 주소에 남아 그대로다.
export default function AnalysisCandidates({
  graphRevision = 0,
}: {
  graphRevision?: number;
}) {
  const revision = useAdminSessionStore((state) => state.revision);
  return <CandidatesSession key={`${revision}:${graphRevision}`} />;
}

function CandidatesSession() {
  const { params, updateQuery } = useRouteQuery();
  const selectedId = params.get('candidate');
  const status = parseStatus(params.get('status'));
  const ruleOnly = params.get('rule') === 'true';
  const urlQ = params.get('q') ?? '';
  const [text, setText] = useState(urlQ);
  // 뒤로·앞으로 가기로 주소의 검색어가 바뀌면 입력칸도 맞춘다.
  const [seenQ, setSeenQ] = useState(urlQ);
  if (urlQ !== seenQ) {
    setSeenQ(urlQ);
    if (urlQ !== text.trim()) setText(urlQ);
  }
  const q = useDebouncedValue(text.trim(), 300);
  const load = useCallback(
    (cursor?: string) => {
      const filters: CandidateFilters = {
        status: status === 'all' ? undefined : status,
        rule: ruleOnly || undefined,
        q: q || undefined,
      };
      return listAnalysisCandidates(filters, cursor);
    },
    [status, ruleOnly, q],
  );
  const candidates = useCursorPages(load);
  const first = candidates.pages[0];
  const counts = first?.counts;
  const statusOptions: { value: StatusFilter; label: string }[] = [
    {
      value: 'HOLD',
      label:
        `보류 ${counts?.HOLD === undefined ? '' : count(counts.HOLD)}`.trim(),
    },
    {
      value: 'ALLOW',
      label:
        `통과 ${counts?.ALLOW === undefined ? '' : count(counts.ALLOW)}`.trim(),
    },
    {
      value: 'REJECT',
      label:
        `폐기 ${counts?.REJECT === undefined ? '' : count(counts.REJECT)}`.trim(),
    },
    { value: 'all', label: '전체' },
  ];
  const select = (id: string | null) => updateQuery({ candidate: id });

  return (
    <div className="grid gap-6 lg:grid-cols-[minmax(0,1fr)_minmax(360px,460px)]">
      <section aria-label="후보" className="flex min-w-0 flex-col gap-3">
        <div className="flex flex-wrap items-center gap-3">
          <Segmented
            label="판정 상태"
            value={status}
            options={statusOptions}
            onChange={(value) =>
              updateQuery(
                { status: value === 'HOLD' ? null : value },
                { replace: true },
              )
            }
          />
          <Segmented
            label="규칙 대상"
            value={ruleOnly ? 'rule' : 'all'}
            options={SCOPE_OPTIONS}
            onChange={(value) =>
              updateQuery(
                { rule: value === 'rule' ? 'true' : null },
                { replace: true },
              )
            }
          />
        </div>
        <input
          type="search"
          aria-label="후보 검색"
          placeholder="제목·기업·대상으로 찾기"
          maxLength={200}
          value={text}
          onChange={(event) => {
            setText(event.target.value);
            updateQuery(
              { q: event.target.value.trim() || null },
              { replace: true },
            );
          }}
          className={SEARCH_INPUT}
        />
        {candidates.refreshError && (
          <p role="status" className="text-caption text-zoop-muted">
            새로 고치지 못했어요. 이전 결과를 표시해요.
          </p>
        )}
        {candidates.status === 'loading' && (
          <Loading>후보를 불러오고 있어요</Loading>
        )}
        {candidates.status === 'error' && candidates.error && (
          <ErrorBox
            title="후보 목록을 불러오지 못했어요"
            error={candidates.error}
            onRetry={candidates.reload}
          />
        )}
        {candidates.status === 'success' && (
          <>
            {counts && (
              <Note>
                활성 후보 기준 · 비활성 {count(counts.inactive ?? null)}건
              </Note>
            )}
            <Note>
              사용자 그래프 [표시 안 됨·확인 못 함]에는 공개 여부를 확인하지
              못한 후보도 들어 있어요. 후보를 열면 구분해서 보여요.
            </Note>
            {candidates.items.length === 0 ? (
              <Empty>
                {q
                  ? '검색어에 맞는 후보가 없어요. 다른 검색어로 찾아 보세요.'
                  : '이 조건의 후보가 없어요.'}
              </Empty>
            ) : (
              <Table caption="후보 목록">
                <thead>
                  <tr>
                    <th className={TH}>판정</th>
                    <th className={TH}>이슈</th>
                    <th className={TH}>관련 기업</th>
                    <th className={`${TH} text-right`}>근거</th>
                    <th className={TH}>사용자 그래프</th>
                    <th className={TH}>검수</th>
                  </tr>
                </thead>
                <tbody>
                  {candidates.items.map((row) => (
                    <tr
                      key={row.candidateId}
                      className={
                        row.candidateId === selectedId
                          ? 'bg-zoop-wash'
                          : undefined
                      }
                    >
                      <td className={`${TD} whitespace-nowrap font-semibold`}>
                        <span
                          className={`inline-flex items-center gap-1 ${row.status === 'HOLD' ? 'text-zoop-hold' : ''}`}
                        >
                          <StatusIcon status={row.status} />
                          {candidateStatusLabel[row.status]}
                        </span>
                      </td>
                      <td className={`${TD} max-w-[28rem]`}>
                        <button
                          type="button"
                          aria-pressed={row.candidateId === selectedId}
                          onClick={() => select(row.candidateId)}
                          className="line-clamp-2 min-h-8 text-left font-semibold hover:underline focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-zoop-ink"
                        >
                          {row.title ?? '사건 없는 관계 후보'}
                        </button>
                        {!row.active && (
                          <span className="mt-1 inline-block rounded-[3px] border-[0.667px] border-zoop-line px-1.5 py-0.5 text-caption text-zoop-muted">
                            비활성
                          </span>
                        )}
                      </td>
                      <td className={`${TD} max-w-48 truncate text-zoop-muted`}>
                        {row.companies
                          .map((company) => company.name)
                          .join(', ') || '–'}
                      </td>
                      <td className={`${TD} text-right tabular-nums`}>
                        {count(row.evidenceCount)}
                      </td>
                      <td className={`${TD} whitespace-nowrap text-zoop-muted`}>
                        {row.onUserGraph ? (
                          '표시 중'
                        ) : (
                          <span className="inline-flex items-center gap-1">
                            <HiddenIcon />
                            표시 안 됨·확인 못 함
                          </span>
                        )}
                      </td>
                      <td className={TD}>
                        {row.decision
                          ? decisionLabel[row.decision.decision]
                          : '–'}
                      </td>
                    </tr>
                  ))}
                </tbody>
              </Table>
            )}
            {candidates.hasMore && (
              <MoreButton
                loading={candidates.loadingMore}
                error={candidates.moreError}
                onClick={candidates.loadMore}
              />
            )}
          </>
        )}
      </section>

      <aside
        aria-label="후보 상세"
        className="min-w-0 border-t-[0.667px] border-zoop-line pt-6 lg:border-t-0 lg:border-l-[0.667px] lg:pt-0 lg:pl-6"
      >
        {selectedId ? (
          <CandidateDetailPanel
            key={selectedId}
            id={selectedId}
            onClose={() => select(null)}
            onDecided={() => candidates.reload({ quiet: true })}
          />
        ) : (
          <div className="flex flex-col gap-2 pt-2">
            <h2 className="text-body font-bold">후보를 골라 주세요</h2>
            <p className="text-caption text-zoop-muted">
              왼쪽 목록에서 후보를 고르면 원문 인용과 판정 근거를 보여 줘요.
            </p>
          </div>
        )}
      </aside>
    </div>
  );
}
