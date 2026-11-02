import { useEffect, useId, useRef, useState } from 'react';
import { ApiError } from '@/apis/auth/ApiService';
import { getBriefingItemDetail } from '@/apis/briefing/briefing';
import { panelStyles as ui } from '@/components/common/detail-panel-styles';
import {
  formatPublishedAt,
  safeArticleUrl,
} from '@/components/graph/event-format';
import type {
  BriefingItem,
  BriefingItemDetail,
  BriefingItemEvidence,
} from '@/types/briefing';
import { briefingTime } from '@/util/briefingTime';
import { useBriefingIssueTracking } from './briefingTelemetryContext';
import LoadingIndicator from '@/components/common/LoadingIndicator';
import { hasOnlyKnownLimitations } from './briefingLimitations';
import { BODY, EMPTY, FOCUS_RING, NOTE, STATUS_PILL } from './briefingStyles';

type DetailState =
  | { status: 'idle' | 'loading' }
  | { status: 'ready'; detail: BriefingItemDetail }
  | { status: 'error'; message: string };

const claimLabels: Record<
  BriefingItemDetail['claims'][number]['type'],
  string
> = {
  fact: '사실',
  plan: '계획',
  outlook: '전망',
};

function detailError(cause: unknown, roundLabel: string) {
  if (cause instanceof ApiError) {
    if (cause.status === 401 || cause.status === 403)
      return `${roundLabel}의 상세·근거를 조회할 권한이 없어요.`;
    if (cause.status === 404)
      return `${roundLabel}에서 제공할 수 있는 상세·근거가 없어요.`;
    if (cause.status === 503)
      return `${roundLabel}의 고정 상세·근거를 지금 제공할 수 없어요. 다시 시도해 주세요.`;
  }
  return `${roundLabel === '이전 회차' ? '이전 회차의 ' : ''}상세·근거를 불러오지 못했어요. 다시 시도해 주세요.`;
}

function BodyContext({ evidence }: { evidence: BriefingItemEvidence }) {
  const context = evidence.bodyContext;
  if (!context)
    return (
      <p className={NOTE}>이 원문 버전의 주변 본문은 제공되지 않았어요.</p>
    );

  // JS 문자열 인덱스(UTF-16)와 API의 Unicode code point 위치를 섞지 않는다.
  const points = Array.from(context.text);
  const start = context.quoteStart - context.start;
  const end = context.quoteEnd - context.start;
  const matches =
    start >= 0 &&
    end <= points.length &&
    end > start &&
    points.slice(start, end).join('') === evidence.quote;
  return (
    <p className={BODY}>
      {matches ? (
        <>
          {points.slice(0, start).join('')}
          <mark className="bg-zoop-wash font-semibold text-zoop-ink underline decoration-zoop-muted underline-offset-4">
            {points.slice(start, end).join('')}
          </mark>
          {points.slice(end).join('')}
        </>
      ) : (
        context.text
      )}
    </p>
  );
}

function EvidenceCard({
  evidence,
  index,
  id,
}: {
  evidence: BriefingItemEvidence;
  index: number;
  id: string;
}) {
  const href = safeArticleUrl(evidence.url);
  const publisher = evidence.publisher.trim();
  const collected = ['exa', 'tavily'].includes(publisher.toLowerCase());
  const source = collected
    ? `수집원 ${publisher}${href ? ` · 원문 ${new URL(href).hostname}` : ''}`
    : publisher || '매체 미제공';
  return (
    <li>
      <article
        id={id}
        tabIndex={-1}
        className={`rounded-panel border border-panel-line p-4 ${FOCUS_RING}`}
        aria-label={`근거 ${index + 1}: ${evidence.title}`}
      >
        <div className="flex flex-wrap items-center gap-2">
          <span className={STATUS_PILL}>
            근거 {index + 1} ·{' '}
            {evidence.sourceKind === 'disclosure' ? '공시' : '기사'}
          </span>
          <span className={NOTE}>저장 원문과 인용 일치</span>
        </div>
        <h6 className={`${ui.itemTitle} mt-2`}>
          {evidence.title || '제목 미제공'}
        </h6>
        <p className={`${NOTE} mt-1`}>
          {source} ·{' '}
          {formatPublishedAt(evidence.publishedAt)
            ? `발행 ${formatPublishedAt(evidence.publishedAt)}`
            : '발행 시각 미상'}
        </p>
        <p className={`${ui.itemTitle} mt-4`}>고정 직접 인용</p>
        <blockquote
          cite={href}
          className={`${BODY} mt-2 border-l-2 border-panel-line pl-3`}
        >
          {evidence.quote}
        </blockquote>
        <p className={`${ui.itemTitle} mt-4 mb-2`}>주변 본문</p>
        <BodyContext evidence={evidence} />
        <div className={`${ui.textActions} mt-3`}>
          {href ? (
            <a href={href} target="_blank" rel="noopener noreferrer">
              ↗ 원문 보기 <span className="sr-only">(새 창에서 열림)</span>
            </a>
          ) : (
            <p className={NOTE}>사용할 수 있는 원문 URL이 제공되지 않았어요.</p>
          )}
        </div>
        {href && (
          <p className={`${NOTE} mt-1`}>
            <span className="font-semibold">원문 URL</span> {href}
          </p>
        )}
        <p className={`${NOTE} mt-2`}>원문 버전 {evidence.documentVersion}</p>
      </article>
    </li>
  );
}

// D-BRF-01·02. 펼친 이슈만 조회하고, 같은 회차·이슈의 두 보기가 요청/결과를 공유한다.
// 호출자는 회차·이슈·버전으로 key를 주어 전환 시 이전 응답과 열린 상태를 남기지 않는다.
export default function BriefingItemDetails({
  roundId,
  graphVersion,
  item,
  isRecap = false,
  evidenceOnly = false,
}: {
  roundId: string;
  graphVersion: string | null;
  item: BriefingItem;
  isRecap?: boolean;
  evidenceOnly?: boolean;
}) {
  const roundLabel = isRecap ? '이전 회차' : '이 회차';
  const issueLabel = isRecap ? '이전 핵심 이슈' : '핵심 이슈';
  const id = useId();
  const recordOpen = useBriefingIssueTracking(roundId, item.eventId);
  const [detailOpen, setDetailOpen] = useState(false);
  const [evidenceOpen, setEvidenceOpen] = useState(false);
  const [state, setState] = useState<DetailState>({ status: 'idle' });
  const active = useRef(true);
  const pending = useRef<Promise<void> | null>(null);
  const detailButton = useRef<HTMLButtonElement>(null);
  const evidenceButton = useRef<HTMLButtonElement>(null);
  useEffect(() => {
    active.current = true;
    return () => {
      active.current = false;
    };
  }, []);

  function load(recheck = false) {
    if ((state.status === 'ready' && !recheck) || pending.current) return;
    setState({ status: 'loading' });
    pending.current = getBriefingItemDetail(roundId, item.eventId, graphVersion)
      .then((detail) => {
        if (active.current) setState({ status: 'ready', detail });
      })
      .catch((cause: unknown) => {
        if (active.current)
          setState({
            status: 'error',
            message: detailError(cause, roundLabel),
          });
      })
      .finally(() => {
        pending.current = null;
      });
  }

  const detail = state.status === 'ready' ? state.detail : null;
  const visible = detailOpen || evidenceOpen;
  const scope = detail
    ? [
        ...new Set([
          ...detail.limitations,
          ...detail.metadata.failures.map((failure) => failure.message),
        ]),
      ]
    : [];
  const partialFailure =
    detail?.metadata.partial &&
    !hasOnlyKnownLimitations(detail.metadata.failures);
  function showEvidence(index: number) {
    setEvidenceOpen(true);
    requestAnimationFrame(() =>
      document.getElementById(`${id}-evidence-${index}`)?.focus(),
    );
  }

  return (
    <div className="mt-2">
      <div className="flex flex-wrap gap-2">
        {!evidenceOnly && (
          <button
            ref={detailButton}
            type="button"
            className={ui.button}
            aria-label={`${issueLabel} ${item.rank} 자세히 ${detailOpen ? '접기' : '보기'}`}
            aria-expanded={detailOpen}
            aria-controls={`${id}-detail`}
            onClick={() => {
              setDetailOpen(!detailOpen);
              if (!visible && !detailOpen) recordOpen();
              if (!detailOpen) load(!visible);
            }}
          >
            자세히 {detailOpen ? '접기' : '보기'}
          </button>
        )}
        <button
          ref={evidenceButton}
          type="button"
          className={ui.button}
          aria-label={`${issueLabel} ${item.rank} 근거 ${evidenceOpen ? '접기' : '보기'}`}
          aria-expanded={evidenceOpen}
          aria-controls={`${id}-evidence`}
          onClick={() => {
            setEvidenceOpen(!evidenceOpen);
            if (!evidenceOnly && !visible && !evidenceOpen) recordOpen();
            if (!evidenceOpen) load(!visible);
          }}
        >
          근거 {evidenceOpen ? '접기' : '보기'}
          {!evidenceOpen && ` (${item.evidenceCount})`}
        </button>
      </div>
      {visible && (
        <div className="mt-3" aria-busy={state.status === 'loading'}>
          {state.status === 'loading' && (
            <LoadingIndicator
              label={`${roundLabel}의 상세·근거를 불러오고 있어요.`}
              className={`${EMPTY} flex min-h-12 w-full`}
            />
          )}
          {state.status === 'error' && (
            <div className={EMPTY}>
              <p role="alert">{state.message}</p>
              <button
                type="button"
                className={`${ui.button} mt-2`}
                onClick={() => load()}
              >
                {isRecap && '이전 회차 '}상세·근거 다시 시도
              </button>
            </div>
          )}
          {detail && (
            <>
              <p className={NOTE}>
                {roundLabel}에 저장된 문안·근거 · 데이터 기준{' '}
                {briefingTime(detail.metadata.asOf)}
              </p>
            </>
          )}
        </div>
      )}
      <section
        id={`${id}-detail`}
        hidden={!detailOpen || !detail}
        aria-label={`${issueLabel} ${item.rank} 상세`}
        className="mt-3 rounded-panel border border-panel-line p-4"
        onKeyDown={(event) => {
          if (event.key === 'Escape') {
            setDetailOpen(false);
            detailButton.current?.focus();
          }
        }}
      >
        {detail && (
          <>
            <h5 className={ui.itemTitle}>{isRecap && '이전 '}브리핑 문안</h5>
            <p className={`${BODY} mt-2`}>
              {'text' in detail.summary
                ? detail.summary.text
                : detail.summary.reason}
            </p>
            {'text' in detail.summary && (
              <p className={`${NOTE} mt-2`}>
                문안 생성 {briefingTime(detail.summary.generatedAt)} · 문안 버전{' '}
                {detail.summary.resultVersion}
              </p>
            )}
            <h5 className={`${ui.itemTitle} mt-4`}>문안의 사실·계획·전망</h5>
            {detail.claims.length ? (
              <ul className="mt-2 flex flex-col gap-3">
                {detail.claims.map((claim, index) => (
                  <li key={`${claim.type}:${index}`}>
                    <span className={STATUS_PILL}>
                      {claimLabels[claim.type]}
                    </span>
                    <p className={`${BODY} mt-1`}>{claim.text}</p>
                    <div className={`${ui.textActions} mt-1`}>
                      {claim.evidenceIds.map((evidenceId) => {
                        const position = detail.evidence.findIndex(
                          (evidence) => evidence.id === evidenceId,
                        );
                        return position >= 0 ? (
                          <button
                            key={evidenceId}
                            type="button"
                            onClick={() => showEvidence(position)}
                          >
                            근거 {position + 1} 확인
                          </button>
                        ) : null;
                      })}
                    </div>
                  </li>
                ))}
              </ul>
            ) : (
              <p className={`${NOTE} mt-2`}>
                문안의 사실·계획·전망 구분이 제공되지 않았어요.
              </p>
            )}
            <h5 className={`${ui.itemTitle} mt-4`}>관련 기업</h5>
            {detail.companies.length ? (
              <ul className="mt-2 flex flex-col gap-1.5">
                {detail.companies.map((company) => (
                  <li key={company.id} className={NOTE}>
                    <span className="font-semibold text-zoop-ink">
                      {company.name}
                    </span>
                    {' · '}
                    {company.relationType === 'STRUCTURALLY_RELATED_TO'
                      ? '구조적 관련 기업'
                      : '사건 관련 기업'}
                    {' · '}
                    {company.roleUnconfirmed
                      ? '역할 미확인'
                      : company.role || '역할 미제공'}
                  </li>
                ))}
              </ul>
            ) : (
              <p className={`${NOTE} mt-2`}>확인된 기업이 없어요.</p>
            )}
            <h5 className={`${ui.itemTitle} mt-4`}>선정 이유</h5>
            <p className={`${BODY} mt-2`}>{detail.selectionReason}</p>
          </>
        )}
      </section>
      <section
        id={`${id}-evidence`}
        hidden={!evidenceOpen || !detail}
        aria-label={`${issueLabel} ${item.rank} 근거`}
        className="mt-3"
        onKeyDown={(event) => {
          if (event.key === 'Escape') {
            setEvidenceOpen(false);
            evidenceButton.current?.focus();
          }
        }}
      >
        {detail && (
          <>
            <h5 className={`${ui.itemTitle} mb-2`}>
              {isRecap ? '이전 회차' : '발행 회차'}에 고정된 근거
            </h5>
            {detail.evidence.length ? (
              <ol className="flex flex-col gap-3">
                {detail.evidence.map((evidence, index) => (
                  <EvidenceCard
                    key={evidence.id}
                    evidence={evidence}
                    index={index}
                    id={`${id}-evidence-${index}`}
                  />
                ))}
              </ol>
            ) : (
              <p className={EMPTY}>
                {roundLabel}에서 제공할 수 있는 원문 근거가 없어요.
              </p>
            )}
          </>
        )}
      </section>
      {visible && detail && (scope.length > 0 || partialFailure) && (
        <div
          role={partialFailure ? 'status' : 'note'}
          aria-label="상세·근거 확인 범위"
          className={`${EMPTY} mt-3`}
        >
          <p className="font-semibold">
            {partialFailure
              ? '일부 상세 정보를 제공하지 못했어요.'
              : '확인 범위'}
          </p>
          <ul className="mt-1 list-disc pl-4">
            {scope.map((limitation, index) => (
              <li key={index}>{limitation}</li>
            ))}
          </ul>
        </div>
      )}
    </div>
  );
}
