import { useEffect, useMemo, useRef, useState } from 'react';
import {
  formatPublishedAt,
  safeArticleUrl,
} from '@/components/graph/event-format';
import { useEvidenceData } from '@/hooks/useEvidenceData';
import { useGraphUiStore } from '@/stores/useGraphUiStore';
import type { EvidenceResponse } from '@/types/evidence';
import './evidence-drawer.css';

interface Props {
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
    <article className="evidence-card">
      {evidence.article ? (
        <>
          <p className="evidence-source">
            <span>{publisherLabel(evidence)}</span>
            <span aria-hidden="true">·</span>
            <span>
              {formatPublishedAt(evidence.article.publishedAt)
                ? `발행 ${formatPublishedAt(evidence.article.publishedAt)}`
                : '발행 시각 미상'}
            </span>
          </p>
          <p className="evidence-verification">
            {evidence.quoteVerified === true
              ? '원문 구간 확인됨'
              : evidence.quoteVerified === false
                ? '원문 구간 불일치'
                : '원문 구간 검증 상태 미제공'}
          </p>
          <h3>{evidence.article.title ?? '문서 제목 미제공'}</h3>
          <blockquote>{evidence.quote}</blockquote>
          <div className="evidence-actions">
            {href ? (
              <a href={href} target="_blank" rel="noopener noreferrer">
                ↗ 원문 기사 보기{' '}
                <span className="evidence-visually-hidden">
                  (새 창에서 열림)
                </span>
              </a>
            ) : (
              <span className="evidence-link-unavailable">
                원문 링크가 제공되지 않았습니다.
              </span>
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
        <div className="evidence-unavailable">
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
export default function EvidenceDrawer({ onViewOnMap }: Props) {
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
  );

  useEffect(() => {
    if (!target) return;
    opener.current =
      document.activeElement instanceof HTMLElement
        ? document.activeElement
        : null;
    const frame = requestAnimationFrame(() => heading.current?.focus());
    return () => {
      cancelAnimationFrame(frame);
      if (opener.current?.isConnected) opener.current.focus();
    };
  }, [target]);

  if (!target) return null;
  const checkedAt = target.mapContext?.asOf ?? items[0]?.metadata.asOf ?? null;
  const retryable = failures.some((failure) => failure.retryable);

  function viewOnMap(evidence: EvidenceResponse) {
    const eventId = evidence.eventIds[0];
    if (!eventId || !onViewOnMap) return;
    setFocusedEvidenceId((current) =>
      current === evidence.id ? null : evidence.id,
    );
    onViewOnMap(eventId);
  }

  return (
    <div className="evidence-layer">
      <div className="evidence-backdrop" aria-hidden="true" />
      <aside
        ref={dialog}
        className="evidence-drawer"
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
          if (event.shiftKey && document.activeElement === first) {
            event.preventDefault();
            last.focus();
          } else if (!event.shiftKey && document.activeElement === last) {
            event.preventDefault();
            first.focus();
          }
        }}
      >
        <header className="evidence-header">
          <button
            type="button"
            className="evidence-close"
            onClick={close}
            aria-label="근거 창 닫기"
          >
            ×
          </button>
          <h2 id="evidence-title" ref={heading} tabIndex={-1}>
            근거 문서
          </h2>
          <p>{target.label ?? '선택한 연결의 근거'}</p>
          <span className="evidence-archive" aria-hidden="true">
            ▱
          </span>
        </header>
        <div className="evidence-scroll" aria-busy={loading}>
          <div className="evidence-checked-at">
            <span>
              관계 확인 시점{' '}
              {formatPublishedAt(checkedAt) ?? '확인 시점 미제공'}
            </span>
            <details>
              <summary aria-label="관계 확인 시점">i</summary>
              <p>
                검증을 통과한 자료를 이 시각 기준으로 확인했습니다. 각 문서의
                발행 시각과는 다릅니다.
              </p>
            </details>
          </div>

          {loading && (
            <div className="evidence-loading" role="status">
              <span />
              <span />
              <p>근거 문서를 불러오는 중입니다.</p>
            </div>
          )}

          {!loading && evidenceIds.length === 0 && (
            <div className="evidence-empty" role="status">
              <strong>연결된 근거가 없습니다.</strong>
              <p>근거가 충분하지 않아 원문 인용을 표시하지 않습니다.</p>
            </div>
          )}

          {!loading && failures.length > 0 && (
            <section
              className="evidence-failures"
              aria-label="제공하지 못한 근거"
            >
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
                  onClick={() => setRetry((value) => value + 1)}
                >
                  다시 시도
                </button>
              )}
            </section>
          )}

          {!loading && items.length > 0 && (
            <div className="evidence-list">
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
        <footer className="evidence-footer">
          MOCK · ERD v6 구조를 따른 합성 데이터이며 실제 기사·공시가 아닙니다.
        </footer>
      </aside>
    </div>
  );
}
