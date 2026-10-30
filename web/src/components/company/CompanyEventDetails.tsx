import { useCallback } from 'react';
import { Link } from 'react-router-dom';
import CompanyLogo from '@/components/common/CompanyLogo';
import DocumentSentiment from '@/components/graph/DocumentSentiment';
import { useAsyncData } from '@/hooks/useAsyncData';
import { readCompanyResource } from '@/apis/company/company';
import { evidenceUrl } from '@/apis/evidence/evidence';
import type { EventDetail } from '@/types/company/detail';
import type { EvidenceResponse } from '@/types/evidence';
import { formatTimelineTime } from '@/util/event-time';
import { formatKst } from '@/util/format';
import { panelStyles as ui } from '@/components/common/detail-panel-styles';

/** D-COM-05: port of company-timeline EventExpanded; document judgments stay document/company scoped. */
export default function CompanyEventDetails({
  event,
  owner,
  asOf,
  graphVersion,
}: {
  event: EventDetail;
  owner: string;
  asOf: string | null;
  graphVersion: string | null;
}) {
  const key = `${owner}|${event.id}|${asOf}|${graphVersion}`;
  const evidence = useAsyncData(
    useCallback(
      async () => ({
        key,
        results: await Promise.allSettled(
          (event.articles.length ? event.evidenceIds : []).map(async (id) => {
            const query = new URLSearchParams({
              ...(asOf ? { asOf } : {}),
              ...(graphVersion ? { graphVersion } : {}),
            });
            const data = await readCompanyResource<EvidenceResponse>(
              `${evidenceUrl(id)}${query.size ? `?${query}` : ''}`,
            );
            if (data.id !== id || !data.eventIds.includes(event.id))
              throw new Error('근거의 사건 연결을 확인하지 못했어요.');
            return data;
          }),
        ),
      }),
      [
        key,
        event.id,
        event.evidenceIds,
        event.articles.length,
        asOf,
        graphVersion,
      ],
    ),
  );
  const results = evidence.data?.key === key ? evidence.data.results : [];
  const documents = results.flatMap((r) =>
    r.status === 'fulfilled' ? [r.value] : [],
  );
  const failed =
    evidence.status === 'error' || results.some((r) => r.status === 'rejected');
  return (
    <>
      <p>
        {event.timePrecision === 'unknown' ? (
          '발생 시점 미상'
        ) : (
          <>
            발생{' '}
            <time dateTime={event.eventTime ?? undefined}>
              {formatTimelineTime(event.eventTime, event.timePrecision)}
            </time>
            {event.timePrecision === 'day' && ' · 시각 미상'}
          </>
        )}
        {event.period && ` · 대상 기간 ${event.period}`}
      </p>
      {/* Approval provenance remains hidden under #392; WBS/wireframe do not add an approval badge here. */}
      <section aria-label="사건 연결 기업">
        <h4>사건 연결 기업</h4>
        {(event.companies ?? []).length ? (
          <ul>
            {event.companies!.map((company) => (
              <li
                key={company.id}
                className="flex flex-wrap items-center gap-2 py-2"
              >
                <CompanyLogo
                  name={company.name}
                  className="size-6 rounded-full border border-zoop-line bg-zoop-paper"
                />
                <Link
                  className={ui.button}
                  to={`/companies/${encodeURIComponent(company.id)}`}
                >
                  {company.name}
                </Link>
                <span className="text-xs text-zoop-muted">
                  {company.relationType === 'INVOLVES'
                    ? '직접 관련'
                    : '구조적 관련'}
                  {company.role && ` · ${company.role}`}
                  {company.roleUnconfirmed && ' · 역할 미확인'}
                </span>
              </li>
            ))}
          </ul>
        ) : (
          <p>이 사건에 연결된 다른 기업은 없어요.</p>
        )}
      </section>
      <section aria-label="사건 근거 문서">
        <h4>근거 문서 {event.articles.length}건</h4>
        {evidence.status === 'loading' && event.evidenceIds.length > 0 && (
          <p role="status">근거 문서를 불러오고 있어요</p>
        )}
        {failed && (
          <p role="alert">
            인용 일부를 불러오지 못했어요{' '}
            <button onClick={evidence.reload}>다시 시도</button>
          </p>
        )}
        {!event.articles.length && <p>연결된 근거 문서가 없어요.</p>}
        <ul>
          {event.articles.map((article) => {
            const sentiments = [
              ...new Map(
                documents
                  .filter((d) => d.articleId === article.id && d.sentiment)
                  .map((d) => [d.sentiment!.companyId, d.sentiment!]),
              ).values(),
            ];
            return (
              <li key={article.id} className="py-3">
                <h4>{article.title ?? '제목 미제공'}</h4>
                <p>
                  {article.publisher ?? '발행처 미제공'} ·{' '}
                  {formatKst(article.publishedAt)}
                </p>
                {sentiments.map((sentiment) => (
                  <div
                    key={sentiment.companyId}
                    className="mt-2 flex flex-wrap items-center gap-2 text-xs"
                  >
                    <span>
                      {event.companies?.find(
                        (c) => c.id === sentiment.companyId,
                      )?.name ?? sentiment.companyId}{' '}
                      · 원문 판정
                    </span>
                    <DocumentSentiment
                      value={sentiment}
                      name={article.title ?? '근거 문서'}
                    />
                  </div>
                ))}
              </li>
            );
          })}
        </ul>
      </section>
    </>
  );
}
