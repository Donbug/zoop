import { useState } from 'react';
import SavedResultFeedback from '@/components/common/SavedResultFeedback';
import { Link, useLocation } from 'react-router-dom';
import { panelStyles as ui } from '@/components/common/detail-panel-styles';
import ChatMarkdown from '@/components/ai/ChatMarkdown';
import { PHASE_PROGRESS } from '@/components/ai/chat-phases';
import {
  formatPublishedAt,
  safeArticleUrl,
} from '@/components/graph/event-format';
import { useAiChatStore } from '@/stores/useAiChatStore';
import { useGraphUiStore } from '@/stores/useGraphUiStore';
import type {
  ChatAnswerBasis,
  ChatBasis,
  ChatChoice,
  ChatCitation,
  ChatJob,
  ChatResult,
} from '@/types/ai';

// D-AI-01b·D-AI-02 · 질문 작업 하나: 상태(접수·진행·실패·취소)와 저장된 결과.
// 문구·근거 수준·제한은 서버가 준 값만 그대로 쓰고 본문에서 추측하지 않는다.

/** 답변이 가리키는 지도 대상과 답변을 만든 그래프 버전·기준 시각. */
export type AnswerMapTarget = {
  id: string;
  kind: string;
  graphVersion: string | null;
  asOf: string | null;
};

const BASIS_LABEL: Record<ChatBasis, string> = {
  general_knowledge: '일반 개념',
  zoop_documented: 'ZOOP 안내',
  evidence_grounded: '근거 확인됨',
  web_reported: '웹 검색 보도',
};

const ANSWER_BASIS_LABEL: Partial<Record<ChatAnswerBasis, string>> = {
  ...BASIS_LABEL,
  mixed: '일반 개념 + 근거 확인됨',
};

const ANSWER_STATUS_LABEL: Record<ChatResult['answerStatus'], string> = {
  complete: '답변 완료',
  partial: '일부 답변',
  guidance: '안내',
};

// D-AI-02b: every AI-side message is one left bubble, mirroring the question bubble on the right.
const bubble =
  'flex max-w-full flex-col items-start gap-3 rounded-[18px_18px_18px_4px] bg-zoop-control px-4 py-3 text-caption leading-relaxed text-zoop-ink [&_p]:m-0!';
// A small chip that hugs its text instead of stretching across the column.
const chip =
  'm-0! inline-flex self-start rounded-full border border-zoop-line px-2 py-0.5 text-caption leading-4 text-zoop-muted';
// Recovery actions inside a bubble.
const pill =
  'inline-flex h-8 items-center rounded-full border border-zoop-line bg-zoop-surface px-3 text-caption font-semibold text-zoop-ink no-underline hover:enabled:bg-zoop-wash focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-zoop-ink disabled:cursor-not-allowed disabled:text-zoop-muted';
// Notices and limitations inside an answer.
const note =
  'rounded-r-xl border-l-2 border-zoop-line bg-zoop-control/60 px-3 py-2.5 text-caption leading-relaxed text-panel-secondary [&_strong]:text-zoop-ink [&_ul]:mt-1 [&_ul]:mb-0 [&_ul]:list-disc [&_ul]:pl-4';

type Props = {
  job: ChatJob;
  /** 이 작업이 답한 확인 질문(대화 안에서 찾은 경우) */
  answers?: ChatJob | null;
  busy: boolean;
  onChoose: (job: ChatJob, choice: ChatChoice) => void;
  onAnswerFreely: (job: ChatJob) => void;
  onRetry: (job: ChatJob) => void;
  /** 답변의 그래프 버전 기준으로 지도에 연다. 그 버전으로 열 수 없으면 false. */
  onViewOnMap?: (target: AnswerMapTarget) => boolean;
  /** 취소했거나 다시 처리할 수 없는 질문을 입력칸으로 되돌려 고쳐 보내게 한다. */
  onRewrite?: (question: string) => void;
};

function formatTime(value: string | null) {
  if (!value) return null;
  const time = new Date(value);
  if (Number.isNaN(time.getTime())) return null;
  return time.toLocaleString('ko-KR', {
    timeZone: 'Asia/Seoul',
    year: 'numeric',
    month: '2-digit',
    day: '2-digit',
    hour: '2-digit',
    minute: '2-digit',
  });
}

export default function ChatJobCard(props: Props) {
  const { job, answers } = props;
  return (
    <article
      // D-AI-01b / D-AI-02b: keep both sides of each message clear of the drawer edge.
      className="flex flex-col gap-3 px-[6%] py-2"
      aria-labelledby={`chat-job-${job.id}`}
      data-screen-id="D-AI-02b"
    >
      <div className="flex justify-end">
        <div className="max-w-[88%] rounded-[18px_18px_4px_18px] bg-zoop-control px-3.5 py-2.5">
          <h3
            id={`chat-job-${job.id}`}
            className="mb-0! wrap-anywhere text-caption font-semibold leading-relaxed"
          >
            {job.question}
          </h3>
        </div>
      </div>
      <div className="flex justify-start">
        <section aria-label="AI 응답" className="min-w-0 max-w-full">
          {answers && (
            <p className={`${ui.muted} mb-2`}>
              확인 질문 “{answers.question}”에 대한 답
            </p>
          )}
          <JobState {...props} />
          {job.status === 'completed' &&
            job.result?.outcome === 'answered' &&
            job.feedbackVersion && (
              <SavedResultFeedback
                feature="chatbot_answer"
                targetId={job.result.messageId}
                targetVersion={job.feedbackVersion}
                subject="이 AI 답변"
              />
            )}
        </section>
      </div>
    </article>
  );
}

function JobState({
  job,
  busy,
  onChoose,
  onAnswerFreely,
  onRetry,
  onViewOnMap,
  onRewrite,
}: Props) {
  if (job.status === 'queued' || job.status === 'running') {
    const current = job.status === 'running' ? job.phase : null;
    return (
      <div
        className="inline-flex items-center gap-2.5 rounded-[18px_18px_18px_4px] bg-zoop-control px-4 py-3 text-caption leading-relaxed text-zoop-muted"
        role="status"
        aria-busy="true"
      >
        <span aria-hidden="true" className="inline-flex items-center gap-1">
          {[0, 1, 2].map((i) => (
            <span
              key={i}
              className="size-1.5 rounded-full bg-zoop-muted motion-safe:animate-pulse"
              style={{ animationDelay: `${i * 200}ms` }}
            />
          ))}
        </span>
        {job.status === 'queued'
          ? '질문을 처리할 차례를 기다리고 있어요.'
          : current
            ? PHASE_PROGRESS[current]
            : '답변을 준비하고 있어요.'}
      </div>
    );
  }
  if (job.status === 'cancelled') {
    return (
      <div className={bubble}>
        <p className="text-zoop-muted">
          취소한 질문이에요. 다시 물으려면 새로 보내 주세요.
        </p>
        {onRewrite && (
          <button
            type="button"
            className={pill}
            onClick={() => onRewrite(job.question)}
          >
            질문 다시 쓰기
          </button>
        )}
      </div>
    );
  }
  if (job.status === 'failed' && job.failure) {
    const failure = job.failure;
    return (
      <div className={bubble} role="alert">
        <p>{failure.message}</p>
        {failure.retry === 'rerun' && (
          <button
            type="button"
            className={pill}
            disabled={busy}
            onClick={() => onRetry(job)}
          >
            질문 다시 처리
          </button>
        )}
        {failure.retry === 'save_only' && (
          <button
            type="button"
            className={pill}
            disabled={busy}
            onClick={() => onRetry(job)}
          >
            저장 다시 시도
          </button>
        )}
        {failure.retry === null && (
          <>
            {onRewrite && (
              <button
                type="button"
                className={pill}
                onClick={() => onRewrite(job.question)}
              >
                질문 고쳐서 새로 보내기
              </button>
            )}
            <p className="text-zoop-muted">
              문의할 때 작업 ID {job.id}를 알려 주세요.
            </p>
          </>
        )}
      </div>
    );
  }
  if (job.status === 'completed' && job.result) {
    return (
      <div className="flex flex-col items-start gap-2">
        <p
          // 일부만 답한 경우만 보이게 알린다. 완료·안내는 말풍선 모양으로 충분하다.
          className={job.result.answerStatus === 'partial' ? chip : 'sr-only'}
          aria-label={`답변 상태: ${ANSWER_STATUS_LABEL[job.result.answerStatus]}`}
        >
          {ANSWER_STATUS_LABEL[job.result.answerStatus]}
        </p>
        <ResultView
          job={job}
          result={job.result}
          busy={busy}
          onChoose={onChoose}
          onAnswerFreely={onAnswerFreely}
          onViewOnMap={onViewOnMap}
        />
      </div>
    );
  }
  return <p className={ui.muted}>이 질문의 상태를 확인하지 못했어요.</p>;
}

function ResultView({
  job,
  result,
  busy,
  onChoose,
  onAnswerFreely,
  onViewOnMap,
}: {
  job: ChatJob;
  result: ChatResult;
  busy: boolean;
  onChoose: Props['onChoose'];
  onAnswerFreely: Props['onAnswerFreely'];
  onViewOnMap?: Props['onViewOnMap'];
}) {
  if (result.outcome === 'clarification') {
    return (
      <div className={bubble}>
        <p>
          <span aria-hidden="true">? </span>
          {result.reason}
        </p>
        {result.choices.length > 0 && (
          <div
            className="flex flex-wrap gap-2"
            role="group"
            aria-label="확인 질문 선택지"
          >
            {result.choices.map((choice) => (
              <button
                key={choice.id}
                type="button"
                disabled={busy}
                onClick={() => onChoose(job, choice)}
                className={pill}
              >
                {choice.label}
              </button>
            ))}
          </div>
        )}
        <button
          type="button"
          className="text-caption font-medium underline underline-offset-2 hover:text-zoop-muted disabled:opacity-50"
          disabled={busy}
          onClick={() => onAnswerFreely(job)}
        >
          직접 입력해 답하기
        </button>
        <p className="-mt-2 text-zoop-muted">
          답하면 새 질문으로 접수되고 이 확인 질문은 그대로 남아요.
        </p>
      </div>
    );
  }
  if (result.outcome === 'guidance') {
    return (
      <div className={bubble}>
        <p>{result.reason}</p>
        {result.action?.kind === 'set_watchlist' && (
          <Link to="/my" className={pill}>
            {result.action.label}
          </Link>
        )}
      </div>
    );
  }
  if (result.outcome === 'insufficient_evidence') {
    return (
      <div className={bubble}>
        <p>{result.reason}</p>
        <Applied result={result} />
      </div>
    );
  }
  return <Answer job={job} result={result} onViewOnMap={onViewOnMap} />;
}

function Answer({
  job,
  result,
  onViewOnMap,
}: {
  job: ChatJob;
  result: ChatResult;
  onViewOnMap?: Props['onViewOnMap'];
}) {
  const number = new Map(
    result.citations.map((citation, i) => [citation.evidenceId, i + 1]),
  );
  const badge = ANSWER_BASIS_LABEL[result.answerBasis];
  const marks = (ids: string[]) => {
    const ns = ids
      .map((id) => number.get(id))
      .filter((n): n is number => n !== undefined);
    if (!ns.length) return null;
    return (
      <span className="ml-1 inline-flex gap-0.5 align-super">
        <span className="sr-only">근거</span>
        {ns.map((n) => (
          <a
            key={n}
            href={`#cite-${job.id}-${n}`}
            className="inline-grid h-4 min-w-4 place-items-center rounded-full bg-zoop-control px-1 text-[11px] leading-none font-semibold text-zoop-muted no-underline hover:bg-zoop-ink hover:text-zoop-on-ink"
          >
            {n}
          </a>
        ))}
      </span>
    );
  };
  return (
    // D-AI-02b: answers read like a document (no bubble), short states stay in bubbles.
    <div className="flex w-full min-w-0 flex-col gap-4">
      {badge && <p className="sr-only">{badge}</p>}
      {result.sections.length > 0 ? (
        result.sections.map((section, i) => (
          <section key={i} aria-label={`${BASIS_LABEL[section.basis]} 구간`}>
            {section.basis === 'web_reported' ? (
              // ZOOP이 확인하지 않은 웹 보도라는 점은 계속 보이게 둔다.
              <p className={`${chip} mb-2!`}>{BASIS_LABEL[section.basis]}</p>
            ) : (
              <p className="sr-only">{BASIS_LABEL[section.basis]}</p>
            )}
            <ChatMarkdown
              text={section.text}
              trailing={marks(section.evidenceIds)}
            />
          </section>
        ))
      ) : (
        // 인용을 지금 읽을 수 없어 서버가 고정 안내만 보낸 경우: 그대로 보여 준다.
        <ChatMarkdown text={result.answer} />
      )}
      {result.notices.length > 0 && (
        <section aria-label="안내" className={note}>
          <strong>안내</strong>
          <ul>
            {result.notices.map((notice, i) => (
              <li key={i} data-code={notice.code}>
                {notice.labels.length > 0 && (
                  <>
                    <span className="font-semibold">
                      {notice.labels.join(', ')}
                    </span>
                    :{' '}
                  </>
                )}
                {notice.message}
              </li>
            ))}
          </ul>
        </section>
      )}
      {result.limitations.length > 0 && (
        // 모두 답한 답변(complete)의 limitation은 답한 요구 옆의 주의뿐이다.
        <section
          aria-label={
            result.answerStatus === 'complete'
              ? '참고할 점'
              : '답하지 않은 부분'
          }
          className={note}
        >
          <strong>
            {result.answerStatus === 'complete'
              ? '참고할 점'
              : '답하지 않은 부분'}
          </strong>
          <ul>
            {result.limitations.map((limitation, i) => (
              <li key={i} data-kind={limitation.kind}>
                <span className="font-semibold">{limitation.label}</span>:{' '}
                {limitation.message}
              </li>
            ))}
          </ul>
        </section>
      )}
      {result.citations.length > 0 && (
        <section aria-label="인용" className="flex flex-col gap-2">
          <p className="m-0! text-caption font-semibold text-zoop-muted">
            인용 {result.citations.length}건
          </p>
          <ol className="m-0! flex list-none flex-col gap-2 p-0">
            {result.citations.map((citation, i) => (
              <Citation
                key={citation.evidenceId}
                id={`cite-${job.id}-${i + 1}`}
                n={i + 1}
                citation={citation}
              />
            ))}
          </ol>
        </section>
      )}
      {onViewOnMap && <SourceEvidence job={job} result={result} />}
      {result.graphTargets.length > 0 && onViewOnMap && (
        <MapTargets job={job} result={result} onViewOnMap={onViewOnMap} />
      )}
      {result.uiActions.length > 0 && (
        <UiActions result={result} onViewOnMap={onViewOnMap} />
      )}
      <Applied result={result} />
    </div>
  );
}

// 대상은 답변을 만든 그래프 버전·기준 시각에 묶여 있다: 지금 지도가 같은 스냅샷이 아니면 그 스냅샷으로 열거나, 열 수 없다고 알린다.
function MapTargets({
  job,
  result,
  onViewOnMap,
}: {
  job: ChatJob;
  result: ChatResult;
  onViewOnMap: NonNullable<Props['onViewOnMap']>;
}) {
  const [unavailable, setUnavailable] = useState(false);
  return (
    <div>
      <div className={ui.textActions}>
        {result.graphTargets.map((target) => (
          <button
            key={target.id}
            type="button"
            onClick={() =>
              setUnavailable(
                !onViewOnMap({
                  id: target.id,
                  kind: target.kind,
                  graphVersion: result.applied.graphVersion,
                  // 질문에 명시된 기준 시각만: 버전만 고정한 답변에 데이터 시점을 시간 필터로 덧붙이지 않는다.
                  asOf: job.context.asOf ?? null,
                }),
              )
            }
          >
            ◇ 지도에서 보기 · {labelOf(result, target.id)}
          </button>
        ))}
      </div>
      {unavailable && (
        <p className={ui.muted} role="status">
          이 답변은 그래프 버전 {result.applied.graphVersion}
          {job.context.asOf ? ` · ${job.context.asOf}` : ''} 기준이라 지금
          지도에서 그대로 열 수 없어요.
        </p>
      )}
    </div>
  );
}

// 서버가 준 동작만 눌렀을 때 연다. 대상 화면이 권한·공개 상태를 다시 확인하고, 모르는 kind는 그리지 않는다.
function UiActions({
  result,
  onViewOnMap,
}: {
  result: ChatResult;
  onViewOnMap?: Props['onViewOnMap'];
}) {
  const [unavailable, setUnavailable] = useState(false);
  const close = useAiChatStore((state) => state.close);
  const location = useLocation();
  return (
    <div>
      <div className={ui.textActions}>
        {result.uiActions.map((action) => {
          const { target } = action;
          if (action.kind === 'open_company' && target.companyId) {
            return (
              <Link
                key={action.actionId}
                to={`/companies/${encodeURIComponent(target.companyId)}`}
                onClick={close}
              >
                {action.label}
              </Link>
            );
          }
          if (action.kind === 'open_briefing' && target.date) {
            const query = new URLSearchParams({
              date: target.date,
              edition: target.edition ?? 'morning',
            });
            return (
              <Link
                key={action.actionId}
                to={`/briefing?${query}`}
                onClick={close}
              >
                {action.label}
              </Link>
            );
          }
          if (action.kind === 'open_watchlist') {
            return (
              <Link key={action.actionId} to="/my" onClick={close}>
                {action.label}
              </Link>
            );
          }
          // D-GRP-05 근거 창은 지도에만 있다. 서버 동작의 근거 ID로 열고, 창이 지금 볼 수 있는지 다시 확인한다.
          if (
            action.kind === 'open_evidence' &&
            target.evidenceIds?.length &&
            onViewOnMap
          ) {
            const { evidenceIds } = target;
            return (
              <button
                key={action.actionId}
                type="button"
                onClick={() => {
                  close();
                  useGraphUiStore.getState().openEvidence({
                    kind: 'path',
                    id: `answer:${evidenceIds.join(',')}`,
                    label: action.label,
                    evidenceIds,
                    mapContext: {
                      url: `${location.pathname}${location.search}`,
                      graphVersion: target.graphVersion ?? undefined,
                      asOf: target.asOf ?? undefined,
                    },
                  });
                }}
              >
                {action.label}
              </button>
            );
          }
          if (
            action.kind === 'focus_relation' &&
            target.edgeId &&
            onViewOnMap
          ) {
            const edgeId = target.edgeId;
            return (
              <button
                key={action.actionId}
                type="button"
                onClick={() =>
                  setUnavailable(
                    !onViewOnMap({
                      id: edgeId,
                      kind: 'edge',
                      graphVersion: target.graphVersion,
                      asOf: target.asOf,
                    }),
                  )
                }
              >
                {action.label}
              </button>
            );
          }
          if (
            action.kind === 'focus_path' &&
            target.fromId &&
            target.toId &&
            onViewOnMap
          ) {
            return (
              <button
                key={action.actionId}
                type="button"
                onClick={() =>
                  setUnavailable(
                    !onViewOnMap({
                      id: `${target.fromId},${target.toId}`,
                      kind: 'path',
                      graphVersion: target.graphVersion,
                      asOf: target.asOf,
                    }),
                  )
                }
              >
                {action.label}
              </button>
            );
          }
          return null;
        })}
      </div>
      {unavailable && (
        <p className={ui.muted} role="status">
          이 항목은 답변을 만든 그래프 기준이라 지금 지도에서 열 수 없어요.
        </p>
      )}
    </div>
  );
}

// D-GRP-05 · prototype chat-job-view.tsx:241-246: 서버의 sources는 기사 ID라 근거 창에는 그 기사 인용의 근거 ID를 넘긴다.
// 서버가 근거 열기 동작을 이미 준 답변에는 같은 버튼을 두 번 두지 않는다.
function SourceEvidence({ job, result }: { job: ChatJob; result: ChatResult }) {
  const location = useLocation();
  const close = useAiChatStore((state) => state.close);
  const evidenceIds = result.citations
    .filter(
      (citation) =>
        citation.articleId !== null &&
        result.sources.includes(citation.articleId),
    )
    .map((citation) => citation.evidenceId);
  if (
    evidenceIds.length === 0 ||
    result.uiActions.some((action) => action.kind === 'open_evidence')
  )
    return null;
  return (
    <div className={ui.textActions}>
      <button
        type="button"
        onClick={() => {
          close();
          useGraphUiStore.getState().openEvidence({
            kind: 'path',
            id: `answer:${evidenceIds.join(',')}`,
            label: job.question,
            evidenceIds,
            mapContext: {
              url: `${location.pathname}${location.search}`,
              graphVersion: result.applied.graphVersion ?? undefined,
              asOf: job.context.asOf ?? undefined,
            },
          });
        }}
      >
        근거 문서 열기
      </button>
    </div>
  );
}

function labelOf(result: ChatResult, id: string) {
  return (
    [...result.applied.companies, ...result.applied.issues].find(
      (item) => item.id === id,
    )?.label ?? id
  );
}

function Citation({
  id,
  n,
  citation,
}: {
  id: string;
  n: number;
  citation: ChatCitation;
}) {
  const profile = citation.sourceKind === 'company_profile';
  const web = citation.sourceKind === 'web_result';
  const href =
    citation.sourceKind === 'article' || profile || web
      ? safeArticleUrl(citation.url)
      : null;
  const published = formatPublishedAt(citation.publishedAt);
  return (
    <li
      id={id}
      className="flex scroll-mt-4 gap-2.5 rounded-xl border border-zoop-line px-3 py-2.5 target:border-zoop-ink"
    >
      <span
        aria-hidden="true"
        className="mt-0.5 inline-grid size-5 shrink-0 place-items-center rounded-full bg-zoop-control text-[11px] font-semibold text-zoop-muted"
      >
        {n}
      </span>
      <div className="flex min-w-0 flex-1 flex-col gap-1">
        <p className="m-0! text-caption leading-snug font-semibold text-zoop-ink wrap-anywhere">
          <span className="sr-only">[{n}] </span>
          {citation.articleTitle ?? '제목 미제공'}
        </p>
        <p className="m-0! text-caption leading-snug text-zoop-muted">
          {citation.sourceKind === 'zoop_doc'
            ? `ZOOP 문서 ${citation.docVersion ?? ''}`
            : `${web ? '웹 검색 결과 · ' : ''}${citation.publisher ?? '출처 미제공'}${published ? ` · ${published}` : ''}`}
        </p>
        <details className="group text-caption text-panel-secondary">
          <summary className="cursor-pointer list-none text-zoop-muted underline-offset-2 hover:underline [&::-webkit-details-marker]:hidden">
            <span className="group-open:hidden">인용문 보기</span>
            <span className="hidden group-open:inline">인용문 접기</span>
          </summary>
          <blockquote className="m-0! mt-1.5! border-l-2 border-zoop-line pl-3 leading-relaxed wrap-anywhere">
            {citation.quote}
          </blockquote>
        </details>
        {href && (
          <a
            href={href}
            target="_blank"
            rel="noopener noreferrer"
            className="self-start text-caption font-medium text-zoop-ink underline underline-offset-2"
          >
            {profile
              ? '↗ 기업 홈페이지'
              : web
                ? '↗ 웹 페이지 보기'
                : '↗ 원문 보기'}{' '}
            <span className="sr-only">(새 창에서 열림)</span>
          </a>
        )}
      </div>
    </li>
  );
}

function Applied({ result }: { result: ChatResult }) {
  const applied = result.applied;
  const names = [...applied.companies, ...applied.issues].map(
    (item) => item.label,
  );
  return (
    <details className={ui.muted}>
      <summary className="cursor-pointer">적용 범위</summary>
      <ul className="my-1 list-disc pl-4">
        <li>대상: {names.length ? names.join(', ') : '없음'}</li>
        {applied.period && (
          <li>
            기간: {applied.period.start} ~ {applied.period.end}
          </li>
        )}
        <li>그래프 버전: {applied.graphVersion ?? '없음'}</li>
        <li>
          자료 기준 시각: {formatTime(applied.dataAsOf) ?? applied.dataAsOf}
        </li>
        {applied.questionOverrodeContext && (
          <li>선택한 대상 대신 질문에 적힌 대상을 기준으로 답했어요.</li>
        )}
      </ul>
    </details>
  );
}
