import { useEffect, useMemo, useRef, useState } from 'react';
import {
  formatPublishedAt,
  safeArticleUrl,
} from '@/components/graph/event-format';
import { useEvidenceData } from '@/hooks/useEvidenceData';
import { useGraphUiStore } from '@/stores/useGraphUiStore';
import type { EvidenceResponse } from '@/types/evidence';
import { panelStyles as ui } from '@/components/common/detail-panel-styles';
import EvidenceAnalysis from './EvidenceAnalysis';

interface Props {
  onReady?: (targetId: string) => void;
  /** 사용자가 창을 닫았을 때. 튜토리얼은 근거를 불러오지 못해도 닫으면 다음 단계로 넘어간다. */
  onClosed?: () => void;
  onTutorialSkip?: () => void;
  onViewOnMap?: (eventId: string) => void;
}

function publisherLabel(evidence: EvidenceResponse) {
  const publisher = evidence.article?.publisher ?? '출처 미제공';
  const href = safeArticleUrl(evidence.article?.url ?? null);
  if (!href) return publisher;
  try {
    return `${publisher} (${new URL(href).hostname})`;
  } catch {
    return publisher;
  }
}

function EvidenceCard({
  evidence,
  focused,
  onViewOnMap,
}: {
  evidence: EvidenceResponse;
  focused: boolean;
  onViewOnMap?: (eventId: string) => void;
}) {
  const href = safeArticleUrl(evidence.article?.url ?? null);
  const eventId = evidence.eventIds[0];
  return (
    <article
      className={`${ui.section} px-5! py-4! [&_h3]:mt-2! [&_h3]:mb-0! [&_blockquote]:mt-2 [&_blockquote]:rounded-[3px] [&_blockquote]:bg-panel-soft [&_blockquote]:px-3 [&_blockquote]:py-2.5 [&_blockquote]:text-[12px] [&_blockquote]:leading-[19.5px] [&_blockquote]:wrap-anywhere`}
    >
      {evidence.article ? (
        <>
          <p className={`flex flex-wrap gap-x-1.5 ${ui.secondary}`}>
            <span>{publisherLabel(evidence)}</span>
            <span aria-hidden="true">·</span>
            <span className={ui.muted}>
              {formatPublishedAt(evidence.article.publishedAt)
                ? `발행 ${formatPublishedAt(evidence.article.publishedAt)}`
                : '발행 시각 미상'}
            </span>
          </p>
          <p className={`${ui.badge} mt-1`}>
            {evidence.quoteVerified === true
              ? '원문 구간 확인됨'
              : evidence.quoteVerified === false
                ? '원문 구간 불일치'
                : '원문 구간 검증 상태 미제공'}
          </p>
          <h3 className="mt-3">
            {evidence.article.title ?? '문서 제목 미제공'}
          </h3>
          <blockquote>{evidence.quote}</blockquote>
          <EvidenceAnalysis evidence={evidence} />
          <div className={`${ui.textActions} mt-3`}>
            {href ? (
              <a href={href} target="_blank" rel="noopener noreferrer">
                ↗ 원문 기사 보기{' '}
                <span className="sr-only">(새 창에서 열림)</span>
              </a>
            ) : (
              <span className={ui.muted}>원문 링크가 제공되지 않았습니다.</span>
            )}
            {eventId && onViewOnMap && (
              <button
                type="button"
                aria-pressed={focused}
                onClick={() => onViewOnMap(eventId)}
              >
                ◇ 지도에서 보기
              </button>
            )}
          </div>
        </>
      ) : (
        <div className={ui.state}>
          <strong>근거 문서를 제공할 수 없습니다.</strong>
          <p>
            삭제·비공개 또는 이용 권한 변경으로 원문 정보를 표시하지 않습니다.
          </p>
        </div>
      )}
    </article>
  );
}

// D-GRP-05 · Figma 619:8225 · FS024 · ERD v6 evidence/article_versions.
export default function EvidenceDrawer({
  onReady,
  onClosed,
  onViewOnMap,
  onTutorialSkip,
}: Props) {
  const target = useGraphUiStore((state) => state.evidenceTarget);
  const close = useGraphUiStore((state) => state.closeEvidence);
  const [retry, setRetry] = useState(0);
  const [focusedEvidenceId, setFocusedEvidenceId] = useState<string | null>(
    null,
  );
  const heading = useRef<HTMLHeadingElement>(null);
  const dialog = useRef<HTMLElement>(null);
  const opener = useRef<HTMLElement | null>(null);
  const evidenceIds = useMemo(() => target?.evidenceIds ?? [], [target]);
  const { items, failures, loading } = useEvidenceData(
    evidenceIds,
    target?.mapContext?.graphVersion,
    retry,
    target?.mapContext,
  );

  useEffect(() => {
    if (target && !loading && items.some((item) => item.article !== null))
      onReady?.(target.id);
  }, [target, loading, items, onReady]);

  useEffect(() => {
    if (!target) return;
    opener.current =
      document.activeElement instanceof HTMLElement
        ? document.activeElement
        : null;
    // Block interaction outside the dialog, including the service header.
    const siblings: { element: HTMLElement; inert: boolean }[] = [];
    let branch: HTMLElement | null = dialog.current?.parentElement ?? null;
    while (branch?.parentElement) {
      for (const child of branch.parentElement.children) {
        if (child !== branch && child instanceof HTMLElement) {
          siblings.push({ element: child, inert: child.inert });
          child.inert = true;
        }
      }
      branch = branch.parentElement;
      if (branch === document.body) break;
    }
    const frame = requestAnimationFrame(() => heading.current?.focus());
    return () => {
      cancelAnimationFrame(frame);
      siblings.forEach(({ element, inert }) => {
        element.inert = inert;
      });
      if (opener.current?.isConnected) opener.current.focus();
    };
  }, [target]);

  if (!target) return null;
  const checkedAt = target.verifiedAt ?? null;
  const retryable = failures.some((failure) => failure.retryable);

  function viewOnMap(evidence: EvidenceResponse) {
    const eventId = evidence.eventIds[0];
    if (!eventId || !onViewOnMap) return;
    setFocusedEvidenceId(evidence.id);
    onViewOnMap(eventId);
  }

  return (
    <div className="absolute inset-0 z-20 flex justify-end">
      <div className="absolute inset-0 bg-black/35" aria-hidden="true" />
      <aside
        ref={dialog}
        className={`relative ${ui.shell} ${ui.wideShell} border-l border-panel-line`}
        data-screen-id="D-GRP-05"
        role="dialog"
        aria-modal="true"
        aria-labelledby="evidence-title"
        onKeyDown={(event) => {
          if (event.key === 'Escape') {
            event.stopPropagation();
            close();
            return;
          }
          if (event.key !== 'Tab') return;
          const focusable = dialog.current?.querySelectorAll<HTMLElement>(
            'button:not(:disabled), a[href], summary, [tabindex]:not([tabindex="-1"])',
          );
          if (!focusable?.length) return;
          const first = focusable[0];
          const last = focusable[focusable.length - 1];
          if (
            event.shiftKey &&
            (document.activeElement === first ||
              document.activeElement === heading.current)
          ) {
            event.preventDefault();
            last.focus();
          } else if (!event.shiftKey && document.activeElement === last) {
            event.preventDefault();
            first.focus();
          }
        }}
      >
        <header
          className={`${ui.header} border-b border-panel-line px-5 pt-5 pb-4 pr-14`}
        >
          <button
            type="button"
            className={`absolute top-5 right-5 ${ui.close}`}
            // 튜토리얼 4단계(근거 확인)에서도 창을 닫을 수 있다.
            data-tutorial-action="evidence"
            onClick={() => {
              close();
              onClosed?.();
            }}
            aria-label="근거 창 닫기"
          >
            ×
          </button>
          {onTutorialSkip && (
            <button
              data-tutorial-action="skip"
              onClick={onTutorialSkip}
              className="mb-2 underline"
            >
              튜토리얼 건너뛰기
            </button>
          )}
          <h2
            id="evidence-title"
            ref={heading}
            tabIndex={-1}
            className={ui.title}
          >
            근거 문서
          </h2>
          <p className={`mt-1 ${ui.secondary}`}>
            {target.label ?? '선택한 연결의 근거'}
          </p>
          <span className="mt-2 block text-base" aria-hidden="true">
            ▱
          </span>
        </header>
        <div className={ui.scroll} aria-busy={loading}>
          <div
            className={`flex items-center gap-2 px-5! py-3.5! ${ui.section} [&_details]:relative [&_summary]:grid [&_summary]:size-5 [&_summary]:cursor-pointer [&_summary]:list-none [&_summary]:place-items-center [&_summary]:rounded-full [&_summary]:border [&_summary]:border-panel-control [&_details_p]:absolute [&_details_p]:top-6 [&_details_p]:right-0 [&_details_p]:z-10 [&_details_p]:w-60 [&_details_p]:rounded-panel [&_details_p]:border [&_details_p]:border-panel-line [&_details_p]:bg-white [&_details_p]:p-3 [&_details_p]:shadow-md`}
          >
            <span>
              관계 확인 시점{' '}
              {formatPublishedAt(checkedAt) ?? '확인 시점 미제공'}
            </span>
            <details>
              <summary aria-label="관계 확인 시점">i</summary>
              <p>
                관계 근거에 기록된 검증 시각입니다. 그래프 조회 기준이나 문서
                발행 시각과는 다르며, 기록이 없으면 미제공으로 표시합니다.
              </p>
            </details>
          </div>

          {loading && (
            <div className={ui.state} role="status">
              <span />
              <span />
              <p>근거 문서를 불러오는 중입니다.</p>
            </div>
          )}

          {!loading && evidenceIds.length === 0 && (
            <div className={ui.state} role="status">
              <strong>연결된 근거가 없습니다.</strong>
              <p>근거가 충분하지 않아 원문 인용을 표시하지 않습니다.</p>
            </div>
          )}

          {!loading && failures.length > 0 && (
            <section className={ui.state} aria-label="제공하지 못한 근거">
              <strong>
                {items.length
                  ? '일부 근거를 불러오지 못했습니다.'
                  : '근거를 불러오지 못했습니다.'}
              </strong>
              <ul>
                {failures.map((failure) => (
                  <li key={failure.id}>
                    {failure.kind === 'permission'
                      ? '권한 없음'
                      : failure.kind === 'unavailable'
                        ? '제공 불가'
                        : '조회 실패'}
                    {' · '}
                    {failure.message}
                  </li>
                ))}
              </ul>
              {retryable && (
                <button
                  type="button"
                  data-tutorial-action="retry"
                  onClick={() => setRetry((value) => value + 1)}
                >
                  다시 시도
                </button>
              )}
            </section>
          )}

          {!loading && items.length > 0 && (
            <div className="flex flex-col">
              {items.map((evidence) => (
                <EvidenceCard
                  key={evidence.id}
                  evidence={evidence}
                  focused={focusedEvidenceId === evidence.id}
                  onViewOnMap={
                    onViewOnMap ? () => viewOnMap(evidence) : undefined
                  }
                />
              ))}
            </div>
          )}
        </div>
        <footer className={ui.footer}>
          {evidenceIds.some((id) => id.startsWith('mock-evidence-'))
            ? 'MOCK · ERD v6 구조를 따른 합성 데이터이며 실제 기사·공시가 아닙니다.'
            : '원문 인용과 검증 상태를 함께 확인해 주세요.'}
        </footer>
      </aside>
    </div>
  );
}
