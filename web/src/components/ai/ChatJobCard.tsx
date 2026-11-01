import { useState } from 'react';
import { Link, useLocation } from 'react-router-dom';
import SavedResultFeedback from '@/components/common/SavedResultFeedback';
import { panelStyles as ui } from '@/components/common/detail-panel-styles';
import { LoadingSpinner } from '@/components/common/LoadingIndicator';
import { PHASES } from '@/components/ai/chat-phases';
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

const KIND_LABEL: Record<string, string> = {
  company: '기업',
  issue: '사건',
  edge: '관계',
  evidence: '근거',
};

type Props = {
  job: ChatJob;
  /** 이 작업이 답한 확인 질문(대화 안에서 찾은 경우) */
  answers?: ChatJob | null;
  busy: boolean;
  onChoose: (job: ChatJob, choice: ChatChoice) => void;
  onAnswerFreely: (job: ChatJob) => void;
  onRetry: (job: ChatJob) => void;
  onCancel: (job: ChatJob) => void;
  /** 답변의 그래프 버전 기준으로 지도에 연다. 그 버전으로 열 수 없으면 false. */
  onViewOnMap?: (target: AnswerMapTarget) => boolean;
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
  const linked = job.context.items;
  return (
    <article className={ui.section} aria-labelledby={`chat-job-${job.id}`}>
      {answers && (
        <p className={ui.muted}>확인 질문 “{answers.question}”에 대한 답</p>
      )}
      <h3 id={`chat-job-${job.id}`} className="mb-0! wrap-anywhere">
        {job.question}
      </h3>
      <p className={ui.muted}>
        연결한 대상:{' '}
        {linked.length
          ? linked
              .map(
                (item) =>
                  `${item.label}(${KIND_LABEL[item.kind] ?? item.kind})`,
              )
              .join(', ')
          : '없음'}
      </p>
      <div className="mt-3">
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
  onCancel,
  onViewOnMap,
}: Props) {
  if (job.status === 'queued' || job.status === 'running') {
    const current = job.status === 'running' ? job.phase : null;
    const index = PHASES.findIndex((step) => step.phase === current);
    return (
      <div className={ui.state}>
        <p className="mt-0!">
          {job.status === 'queued' ? (
            '질문을 접수했어요.'
          ) : (
            <>
              <LoadingSpinner size="sm" />
              <span>
                {' '}
                답변을 준비하고 있어요. 검증을 마친 답변만 보여 드려요.
              </span>
            </>
          )}
        </p>
        {job.status === 'running' && (
          <ol className="m-0 flex list-none flex-wrap gap-1.5 p-0">
            {PHASES.map((step, i) => (
              <li
                key={step.phase}
                className={ui.badge}
                aria-current={i === index ? 'step' : undefined}
              >
                {i === index ? <strong>{step.label}</strong> : step.label}
              </li>
            ))}
          </ol>
        )}
        <button type="button" onClick={() => onCancel(job)}>
          질문 취소
        </button>
      </div>
    );
  }
  if (job.status === 'cancelled') {
    return (
      <p className={ui.secondary}>
        취소한 질문이에요. 다시 물으려면 새로 보내 주세요.
      </p>
    );
  }
  if (job.status === 'failed' && job.failure) {
    const failure = job.failure;
    return (
      <div className={ui.state} role="alert">
        <p className="mt-0!">{failure.message}</p>
        {failure.retry === 'rerun' && (
          <button type="button" disabled={busy} onClick={() => onRetry(job)}>
            질문 다시 처리
          </button>
        )}
        {failure.retry === 'save_only' && (
          <button type="button" disabled={busy} onClick={() => onRetry(job)}>
            저장 다시 시도
          </button>
        )}
        {failure.retry === null && (
          <p className={ui.muted}>문의할 때 작업 ID {job.id}를 알려 주세요.</p>
        )}
      </div>
    );
  }
  if (job.status === 'completed' && job.result) {
    return (
      <div className="flex flex-col gap-3">
        <p
          className={ui.badge}
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
      <div className="border-l-2 border-panel-control pl-3">
        <p className={ui.secondary}>
          <span aria-hidden="true">? </span>
          {result.reason}
        </p>
        {result.choices.length > 0 && (
          <div
            className={`${ui.textActions} mt-2`}
            role="group"
            aria-label="확인 질문 선택지"
          >
            {result.choices.map((choice) => (
              <button
                key={choice.id}
                type="button"
                disabled={busy}
                onClick={() => onChoose(job, choice)}
                className="border! border-panel-line!"
              >
                {choice.label}
              </button>
            ))}
          </div>
        )}
        <button
          type="button"
          className="mt-2 text-caption underline"
          disabled={busy}
          onClick={() => onAnswerFreely(job)}
        >
          직접 입력해 답하기
        </button>
        <p className={`${ui.muted} mt-1`}>
          답하면 새 질문으로 접수되고 이 확인 질문은 그대로 남아요.
        </p>
      </div>
    );
  }
  if (result.outcome === 'guidance') {
    return (
      <div className={ui.state}>
        <p className="mt-0!">{result.reason}</p>
        {result.action?.kind === 'set_watchlist' && (
          <Link to="/my" className="underline">
            {result.action.label}
          </Link>
        )}
      </div>
    );
  }
  if (result.outcome === 'insufficient_evidence') {
    return (
      <div className={ui.state}>
        <p className="mt-0!">{result.reason}</p>
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
  return (
    <div className="flex flex-col gap-3">
      {badge && <p className={ui.badge}>{badge}</p>}
      {result.sections.length > 0 ? (
        result.sections.map((section, i) => (
          <section key={i} aria-label={`${BASIS_LABEL[section.basis]} 구간`}>
            <p className={`${ui.badge} mb-1`}>{BASIS_LABEL[section.basis]}</p>
            <p className="m-0 whitespace-pre-wrap wrap-anywhere text-caption leading-[19.5px]">
              {section.text}
            </p>
            {section.evidenceIds.length > 0 && (
              <p className={ui.muted}>
                근거{' '}
                {section.evidenceIds
                  .map((id) => number.get(id))
                  .filter((n): n is number => n !== undefined)
                  .map((n) => `[${n}]`)
                  .join(' ')}
              </p>
            )}
          </section>
        ))
      ) : (
        // 인용을 지금 읽을 수 없어 서버가 고정 안내만 보낸 경우: 그대로 보여 준다.
        <p className="m-0 whitespace-pre-wrap wrap-anywhere text-caption leading-[19.5px]">
          {result.answer}
        </p>
      )}
      {result.notices.length > 0 && (
        <section aria-label="안내" className={ui.state}>
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
          className={ui.state}
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
        <section aria-label="인용">
          <p className={ui.itemTitle}>인용</p>
          <ol className={ui.list}>
            {result.citations.map((citation, i) => (
              <Citation
                key={citation.evidenceId}
                n={i + 1}
                citation={citation}
              />
            ))}
          </ol>
        </section>
      )}
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

function labelOf(result: ChatResult, id: string) {
  return (
    [...result.applied.companies, ...result.applied.issues].find(
      (item) => item.id === id,
    )?.label ?? id
  );
}

function Citation({ n, citation }: { n: number; citation: ChatCitation }) {
  const profile = citation.sourceKind === 'company_profile';
  const web = citation.sourceKind === 'web_result';
  const href =
    citation.sourceKind === 'article' || profile || web
      ? safeArticleUrl(citation.url)
      : null;
  const published = formatPublishedAt(citation.publishedAt);
  return (
    <li>
      <p className={ui.secondary}>
        [{n}] {citation.articleTitle ?? '제목 미제공'}
        {citation.sourceKind === 'zoop_doc'
          ? ` · ZOOP 문서 ${citation.docVersion ?? ''}`
          : ` · ${web ? '웹 검색 결과 · ' : ''}${citation.publisher ?? '출처 미제공'}${published ? ` · ${published}` : ''}`}
      </p>
      <blockquote className="my-1 rounded-[3px] bg-panel-soft px-3 py-2 text-caption wrap-anywhere">
        {citation.quote}
      </blockquote>
      {href && (
        <a
          href={href}
          target="_blank"
          rel="noopener noreferrer"
          className="underline"
        >
          {profile
            ? '↗ 기업 홈페이지'
            : web
              ? '↗ 웹 페이지 보기'
              : '↗ 원문 보기'}{' '}
          <span className="sr-only">(새 창에서 열림)</span>
        </a>
      )}
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
