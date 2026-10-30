import { panelStyles as ui } from '@/components/common/detail-panel-styles';
import CompanyLogo from '@/components/common/CompanyLogo';
import { useEffect, useRef, useState } from 'react';
import { Link } from 'react-router-dom';
import { useEventData } from '@/hooks/useEventData';
import type { EventContext, EventDetail } from '@/types/map/event';
import type { GraphNode } from '@/types/map/graph';
import GraphIcon from './GraphIcon';
import EventLinkedDetails from './EventLinkedDetails';
import {
  formatEventTime,
  formatPublishedAt,
  safeArticleUrl,
} from './event-format';

export type EventAction = 'evidence' | 'focus' | 'ai';
interface Props {
  id: string;
  companyDetailHref?: (id: string) => string;
  context: EventContext;
  geography: GraphNode['geography'];
  /** 지도에 있는 기업 노드의 로고 */
  logoOf?: (companyId: string) => string | null | undefined;
  onClose: () => void;
  onAction: (action: EventAction, event: EventDetail) => void;
}

// D-GRP-02 · Figma 619:6269 · WBS 6.6.22.
export default function EventDetailPanel({
  id,
  companyDetailHref,
  context,
  geography,
  logoOf,
  onClose,
  onAction,
}: Props) {
  const [retry, setRetry] = useState(0);
  const [notice, setNotice] = useState('');
  const heading = useRef<HTMLHeadingElement>(null);
  const { data, loading, error } = useEventData(id, context, retry);
  useEffect(() => {
    heading.current?.focus();
  }, [id]);
  function action(name: EventAction) {
    if (!data) return;
    onAction(name, data);
    setNotice(
      name === 'evidence'
        ? '이 사건에 연결된 근거 문서를 열었습니다.'
        : name === 'ai'
          ? '이 사건을 질문 대상으로 연결했습니다.'
          : '이 사건을 지도 중심으로 선택했습니다.',
    );
  }
  const failures = data?.metadata.failures ?? [];
  const failed = (section: string) =>
    failures.some((failure) => failure.section === section);
  const evidenceCount = data ? new Set(data.evidenceIds).size : 0;
  const directCompanies =
    data?.companies.filter((company) => company.relationType === 'INVOLVES') ??
    [];
  const structuralCompanies =
    data?.companies.filter(
      (company) => company.relationType === 'STRUCTURALLY_RELATED_TO',
    ) ?? [];
  function renderCompanies(items: typeof directCompanies) {
    return (
      <ul
        className={`${ui.list} [&>li]:flex [&>li]:items-center [&>li]:gap-2.5 [&_strong]:text-[12px] [&_strong]:font-semibold [&_strong]:leading-[18px] [&_p]:text-[11px] [&_p]:leading-[16.5px] [&_p]:text-panel-muted`}
      >
        {items.map((company, index) => (
          <li key={`${company.id}-${index}`}>
            <CompanyLogo
              name={company.name}
              logoUrl={logoOf?.(company.id)}
              className={ui.avatar}
            />
            <div>
              <Link
                to={
                  companyDetailHref?.(company.id) ??
                  `/companies/${encodeURIComponent(company.id)}`
                }
                className="text-zoop-ink underline underline-offset-4 focus-visible:outline-2"
              >
                <strong>{company.name}</strong>
              </Link>
              <p>
                {company.roleUnconfirmed
                  ? '역할 미확인'
                  : company.role === 'participant'
                    ? '참여 기업'
                    : company.role || '역할 미제공'}
              </p>
            </div>
          </li>
        ))}
      </ul>
    );
  }
  return (
    <aside
      className={`event-panel ${ui.shell}`}
      data-screen-id="D-GRP-02"
      aria-labelledby="event-panel-title"
      onKeyDown={(event) => {
        if (event.key === 'Escape') {
          event.stopPropagation();
          onClose();
        }
      }}
    >
      <header className={ui.header}>
        <div className="mb-3 flex flex-wrap gap-1.5 pr-10">
          <span className={ui.badge}>
            <GraphIcon name="issue" size={12} />
            사건
          </span>
          <span className={ui.badge}>
            {geography === 'domestic'
              ? '국내'
              : geography === 'international'
                ? '국제'
                : '지역 미제공'}
          </span>
        </div>
        <button
          className={`absolute top-4 right-4 ${ui.close}`}
          onClick={onClose}
          aria-label="상세 닫기"
        >
          ×
        </button>
        <h2
          id="event-panel-title"
          ref={heading}
          tabIndex={-1}
          className={ui.title}
        >
          {data?.title ?? '사건 상세'}
        </h2>
        {data && (
          <p className={ui.muted}>
            {formatEventTime(data.eventTime, data.timePrecision)}
          </p>
        )}
        {data?.period && <p className={ui.muted}>기간 · {data.period}</p>}
      </header>
      <div className={ui.scroll} aria-busy={loading}>
        {loading && (
          <div className={ui.state} role="status">
            <span className="block h-16 rounded-panel bg-panel-line motion-safe:animate-pulse" />
            <p>사건 정보를 불러오는 중입니다.</p>
          </div>
        )}
        {error && (
          <div className={ui.state} role="alert">
            <strong>사건을 불러오지 못했습니다.</strong>
            <p>{error}</p>
            <p>지도는 그대로 유지됩니다.</p>
            <button onClick={() => setRetry((value) => value + 1)}>
              다시 시도
            </button>
          </div>
        )}
        {data && (
          <>
            {/* 승인 출처(approval)는 관리자 쪽 정보라 사용자 패널에 보이지 않는다(FE 전달 3-1, 2026-10-28). */}
            <div
              className={`${ui.actions} [&>button:last-child]:col-span-2 [&>button:last-child]:bg-panel-ink [&>button:last-child]:text-white`}
            >
              <button
                disabled={
                  failed('evidence') ||
                  failed('evidenceIds') ||
                  evidenceCount === 0
                }
                onClick={() => action('evidence')}
              >
                <GraphIcon name="briefing" size={14} />
                {failed('evidence') || failed('evidenceIds')
                  ? '근거 조회 실패'
                  : `근거 ${evidenceCount}건 보기`}
              </button>
              <button onClick={() => action('focus')}>
                <GraphIcon name="fit" size={14} />
                이슈 중심 그래프
              </button>
              <button onClick={() => action('ai')}>
                <GraphIcon name="ai" size={14} />
                AI에게 묻기
              </button>
            </div>
            {notice && (
              <p className={ui.state} role="status">
                {notice}
              </p>
            )}
            {data.metadata.partial && (
              <div className={ui.state} role="status">
                <strong>일부 정보를 불러오지 못했습니다.</strong>
                <ul>
                  {failures.map((failure, index) => (
                    <li key={`${failure.section}-${index}`}>
                      {failure.message}
                    </li>
                  ))}
                </ul>
                {(failures.length === 0 ||
                  failures.some((f) => f.retryable)) && (
                  <button onClick={() => setRetry((value) => value + 1)}>
                    다시 시도
                  </button>
                )}
              </div>
            )}
            <section
              className={ui.section}
              aria-labelledby="event-summary-title"
            >
              <h3 id="event-summary-title">핵심 내용</h3>
              <p>
                {'text' in data.summary && data.summary.evidenceIds.length > 0
                  ? data.summary.text
                  : 'reason' in data.summary
                    ? data.summary.reason
                    : '확인된 근거가 없어 요약을 제공하지 않습니다.'}
              </p>
            </section>
            <section
              className={ui.section}
              aria-labelledby="event-companies-title"
            >
              <h3 id="event-companies-title">
                <GraphIcon name="company" size={14} />
                직접 관련 기업{' '}
                {failed('companies')
                  ? '조회 실패'
                  : `${new Set(directCompanies.map((c) => c.id)).size}곳`}
              </h3>
              {failed('companies') ? (
                <p className={ui.muted}>
                  관련 기업 정보를 불러오지 못했습니다.
                </p>
              ) : directCompanies.length ? (
                renderCompanies(directCompanies)
              ) : (
                <p className={ui.muted}>직접 관련 기업이 없습니다.</p>
              )}
              {structuralCompanies.length > 0 && (
                <>
                  <h3 className="mt-4">
                    구조적 관련 기업{' '}
                    {new Set(structuralCompanies.map((c) => c.id)).size}곳
                  </h3>
                  {renderCompanies(structuralCompanies)}
                </>
              )}
            </section>
            <section
              className={ui.section}
              aria-labelledby="event-documents-title"
            >
              <h3 id="event-documents-title">
                <GraphIcon name="briefing" size={14} />
                관련 문서{' '}
                {failed('articles') ? '조회 실패' : `${data.articles.length}건`}
              </h3>
              {!failed('sourceSupport') &&
                data.sourceSupport.independentSourceCount !== null && (
                  <p className="text-zoop-muted">
                    독립 출처 {data.sourceSupport.independentSourceCount}곳
                  </p>
                )}
              {failed('articles') ? (
                <p className={ui.muted}>관련 문서를 불러오지 못했습니다.</p>
              ) : data.articles.length ? (
                <ul
                  className={`${ui.list} [&_h4]:my-1 [&_h4]:font-semibold [&_h4]:wrap-anywhere [&_a]:mt-2 [&_a]:inline-block [&_a]:underline`}
                >
                  {data.articles.map((article) => {
                    const href = safeArticleUrl(article.url);
                    return (
                      <li key={article.id}>
                        <span className={ui.muted}>
                          {article.relationType === 'REPORTS'
                            ? '보도 기사'
                            : article.relationType === 'PROVIDES_BACKGROUND'
                              ? '배경 자료'
                              : '문서 유형 미제공'}
                        </span>
                        <h4>{article.title ?? '제목 미제공'}</h4>
                        <p className={ui.muted}>
                          {article.publisher ?? '출처 미제공'} ·{' '}
                          {formatPublishedAt(article.publishedAt)
                            ? `발행 ${formatPublishedAt(article.publishedAt)}`
                            : '발행 시각 미상'}
                        </p>
                        {href ? (
                          <a
                            href={href}
                            target="_blank"
                            rel="noopener noreferrer"
                          >
                            원문 보기 <span className={ui.muted}>(새 창)</span>
                          </a>
                        ) : (
                          <p className={ui.muted}>원문 링크 미제공</p>
                        )}
                      </li>
                    );
                  })}
                </ul>
              ) : (
                <p className={ui.muted}>관련 문서가 없습니다.</p>
              )}
            </section>
            <section className={ui.section} aria-label="근거 안내">
              <p>
                {failed('evidence') || failed('evidenceIds')
                  ? '근거 정보를 불러오지 못했습니다.'
                  : evidenceCount
                    ? `연결된 근거 ${evidenceCount}건 · 문서 수와 인용 근거 수는 다를 수 있습니다.`
                    : '연결된 근거가 없습니다.'}
              </p>
              <p className={ui.muted}>
                기업별 영향 해석은 제공되지 않았습니다.
              </p>
            </section>
            <EventLinkedDetails event={data} />
            <footer className={ui.footer}>
              <p>{data.metadata.source}</p>
              <p>
                조회 기준 · {formatPublishedAt(data.metadata.asOf) ?? '미제공'}
              </p>
            </footer>
          </>
        )}
      </div>
    </aside>
  );
}
