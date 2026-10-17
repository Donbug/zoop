import { useParams } from 'react-router-dom';
import { useRouteQuery } from '@/hooks/useRouteQuery';
import { useCompanyResource, type Resource } from '@/hooks/useCompanyResource';
import { companyUrl } from '@/apis/company/company';
import { exactTime, safeHref } from './detail-model';
import type { CompanyDocuments, Evidence } from '@/types/company/documents';
import type { DocumentAnalysis } from '@/types/evidence';

const stageLabels = {
  not_requested: '미요청',
  pending: '처리 중',
  failed: '실패',
  withheld: '공개 보류',
  available: '제공됨',
};
function Failure<T>({
  resource,
  label,
}: {
  resource: Resource<T>;
  label: string;
}) {
  if (resource.loading) return <p role="status">{label} 불러오는 중…</p>;
  if (!resource.error) return null;
  const permission =
    [401, 403].includes(resource.errorStatus ?? 0) ||
    ['ACCESS_DENIED', 'EVIDENCE_UNAVAILABLE', 'MEMBER_REQUIRED'].includes(
      resource.errorCode ?? '',
    );
  return (
    <div role="alert">
      <p>
        {permission ? '공개할 수 없는 자료입니다.' : `${label} 조회 실패`} ·{' '}
        {resource.error}
      </p>
      {!permission && (
        <button onClick={resource.retry}>{label} 다시 조회</button>
      )}
    </div>
  );
}
function Original({ url }: { url: string | null }) {
  const href = safeHref(url);
  return href ? (
    <a href={href} target="_blank" rel="noreferrer">
      원문 보기
    </a>
  ) : (
    <p>원문을 제공하지 않는 자료입니다</p>
  );
}
function Analysis({
  value,
  companyId,
  documentId,
}: {
  value: DocumentAnalysis;
  companyId: string;
  documentId: string;
}) {
  const sentiment =
    value.sentiment?.companyId === companyId ? value.sentiment : null;
  const summary =
    value.documentSummary?.documentId === documentId &&
    value.documentSummary.documentVersion === value.documentVersion &&
    value.documentSummary.resultVersion === value.resultVersion
      ? value.documentSummary
      : null;
  return (
    <>
      {value.documentVersion && (
        <p>
          문서 버전 {value.documentVersion} · 분석 결과 버전{' '}
          {value.resultVersion ?? '미제공'}
        </p>
      )}
      {summary ? (
        <details>
          <summary>제공된 문서 요약</summary>
          <p>{summary.text}</p>
          {summary.limitations.map((limitation, i) => (
            <p key={i}>한계 · {limitation}</p>
          ))}
        </details>
      ) : (
        value.analysisStatus?.summary && (
          <p>
            문서 요약 {stageLabels[value.analysisStatus.summary.status]} ·{' '}
            {value.analysisStatus.summary.reason ?? '사유 미제공'}
          </p>
        )
      )}
      {sentiment ? (
        <p>
          기업 맥락 판정 ·{' '}
          {
            {
              positive: '긍정',
              negative: '부정',
              mixed: '혼재',
              undetermined: '판단 유보',
            }[sentiment.label]
          }{' '}
          · {sentiment.rationale} · 판정 시각 {sentiment.judgedAt}
        </p>
      ) : value.sentiment ? (
        <p>조회 기업과 다른 맥락의 판정은 표시하지 않았어요.</p>
      ) : (
        value.analysisStatus?.sentiment && (
          <p>
            기업 맥락 판정 {stageLabels[value.analysisStatus.sentiment.status]}{' '}
            · {value.analysisStatus.sentiment.reason ?? '사유 미제공'}
          </p>
        )
      )}
      {value.analysisProvenance?.sourceKind === 'synthetic' && (
        <p className="border-l-2 border-zoop-faint bg-zoop-soft p-2">
          합성 테스트 분석입니다. 실제 뉴스 분석 결과가 아닙니다.
        </p>
      )}
    </>
  );
}
export default function CompanyDocumentPanel() {
  const { id = '' } = useParams();
  const { params, updateQuery } = useRouteQuery();
  const asOf = params.get('asOf'),
    version = params.get('graphVersion'),
    eventId = params.get('event');
  const kind = ['news', 'disclosure'].includes(params.get('docKind') ?? '')
    ? params.get('docKind')
    : null;
  const scope = params.get('docScope') === 'event' && eventId ? 'event' : 'all';
  const selected = params.get('document'),
    evidenceId = params.get('evidence');
  const ready = exactTime(asOf);
  const snapshot = { asOf, graphVersion: version };
  const list = useCompanyResource<CompanyDocuments>(
    ready ? companyUrl(id, '/documents', { ...snapshot, kind }) : null,
    '',
    true,
  );
  const evidenceQuery = new URLSearchParams({
    companyId: id,
    ...(asOf ? { asOf } : {}),
    ...(version ? { graphVersion: version } : {}),
  });
  const evidence = useCompanyResource<Evidence>(
    ready && evidenceId
      ? `/api/v1/evidence/${encodeURIComponent(evidenceId)}?${evidenceQuery}`
      : null,
  );
  const cutoff = asOf ? Date.parse(asOf) : Infinity;
  const permitted = (list.data?.items ?? []).filter(
    (doc) =>
      !exactTime(doc.publishedAt) || Date.parse(doc.publishedAt!) <= cutoff,
  );
  const visible =
    scope === 'event'
      ? permitted.filter((doc) =>
          doc.events?.some((event) => event.eventId === eventId),
        )
      : permitted;
  const activeDoc = visible.find((doc) => doc.id === selected);
  const partial = list.data?.metadata.partial;
  const evidenceDoc = visible.find(
    (doc) => doc.id === evidence.data?.articleId,
  );
  const evidenceContextValid =
    !!evidence.data &&
    !list.loading &&
    !list.error &&
    !!evidenceDoc &&
    evidence.data.metadata.graphVersion === list.data?.metadata.graphVersion &&
    Date.parse(evidence.data.metadata.asOf) ===
      Date.parse(list.data!.metadata.asOf) &&
    evidenceDoc.quotes.some((quote) => quote.evidenceId === evidenceId) &&
    evidence.data.id === evidenceId &&
    (!selected ||
      (!list.loading && !!activeDoc && evidence.data.articleId === selected)) &&
    (!eventId || scope !== 'event' || evidence.data.eventIds.includes(eventId));
  const evidenceTimeValid =
    !exactTime(evidence.data?.article?.publishedAt) ||
    Date.parse(evidence.data!.article!.publishedAt!) <= cutoff;
  const eventCounts = new Map<
    string,
    { title: string; documents: Set<string> }
  >();
  for (const doc of permitted)
    for (const event of doc.events ?? []) {
      const entry = eventCounts.get(event.eventId) ?? {
        title: event.title,
        documents: new Set<string>(),
      };
      entry.documents.add(doc.id);
      eventCounts.set(event.eventId, entry);
    }
  return (
    <section
      aria-label="뉴스·공시"
      data-screen-id="D-COM-02"
      className="[&_blockquote]:my-3 [&_blockquote]:border-l-2 [&_blockquote]:border-zoop-line [&_blockquote]:bg-zoop-wash [&_blockquote]:p-3 [&_blockquote]:text-xs [&_blockquote]:leading-[1.7] [&_blockquote]:wrap-anywhere [&_summary]:cursor-pointer [&_h4]:font-semibold"
    >
      <h2>뉴스·공시 · 근거 문서</h2>
      <nav aria-label="문서 종류">
        {[
          ['all', '전체'],
          ['news', '뉴스'],
          ['disclosure', '공시'],
        ].map(([value, label]) => (
          <button
            key={value}
            aria-pressed={(kind ?? 'all') === value}
            onClick={() =>
              updateQuery({
                docKind: value === 'all' ? null : value,
                document: null,
                evidence: null,
              })
            }
          >
            {label}
          </button>
        ))}
      </nav>
      {eventId && (
        <nav aria-label="근거 문서 범위">
          <button
            aria-pressed={scope === 'all'}
            onClick={() =>
              updateQuery({ docScope: null, document: null, evidence: null })
            }
          >
            전체 기업 문서
          </button>
          <button
            aria-pressed={scope === 'event'}
            onClick={() =>
              updateQuery({ docScope: 'event', document: null, evidence: null })
            }
          >
            선택 사건의 근거
          </button>
        </nav>
      )}
      {!ready && <p role="status">기업 상세의 기준 시점을 확인하고 있어요.</p>}
      <Failure resource={list} label="뉴스·공시" />
      {list.data && (
        <>
          <p className="wrap-anywhere">
            출처 {list.data.metadata.source} · 기준 {list.data.metadata.asOf} ·
            버전 {list.data.metadata.graphVersion ?? '미제공'}
          </p>
          <p>
            제공된 근거 문서 {visible.length}건
            {partial ? ' · 일부 자료 미제공' : ''}
          </p>
          {partial && (
            <p role="alert">
              일부 문서 자료를 받지 못했어요. 전체 문서 수나 문서가 없는 상태로
              해석하지 마세요.
              <button onClick={list.retry}>뉴스·공시 다시 조회</button>
            </p>
          )}
          {permitted.length !== list.data.items.length && (
            <p>선택 시점 이후에 발행된 문서는 표시하지 않았어요.</p>
          )}
          {!visible.length && !partial && (
            <p>
              {scope === 'event'
                ? '선택 사건에 연결된 공개 문서가 없어요.'
                : '공개된 뉴스·공시가 없어요.'}
            </p>
          )}
          <ul className="flex flex-wrap gap-2">
            {[...eventCounts].map(([eventId, event]) => (
              <li key={eventId}>
                <button
                  onClick={() =>
                    updateQuery({
                      event: eventId,
                      docScope: 'event',
                      document: null,
                      evidence: null,
                    })
                  }
                >
                  {event.title} · 근거 문서 {event.documents.size}건
                </button>
              </li>
            ))}
          </ul>
          {visible.map((doc) => (
            <article
              key={doc.id}
              aria-label={`문서 ${doc.title ?? '제목 미제공'}`}
            >
              <p>
                {doc.kind === 'disclosure'
                  ? '공시'
                  : doc.kind === 'news'
                    ? '뉴스'
                    : '종류 미제공'}{' '}
                · {doc.publisher ?? '출처 미제공'} ·{' '}
                {doc.publishedAt ?? '발행 시각 미제공'}
              </p>
              <h3>{doc.title ?? '제목 미제공'}</h3>
              {(doc.events ?? []).map((event) => (
                <p key={event.eventId}>
                  {event.relationType === 'REPORTS'
                    ? '사건을 보도한 자료'
                    : event.relationType === 'PROVIDES_BACKGROUND'
                      ? '사건 배경을 제공한 자료'
                      : '관련 설명 미제공'}{' '}
                  ·{' '}
                  <button
                    onClick={() =>
                      updateQuery({
                        tab: 'events',
                        event: event.eventId,
                        bucket: null,
                      })
                    }
                  >
                    {event.title} 사건 보기
                  </button>
                </p>
              ))}
              <Original url={doc.url} />
              <button
                aria-pressed={selected === doc.id}
                onClick={() =>
                  updateQuery({ document: doc.id, evidence: null })
                }
              >
                문서 근거 선택 · {doc.quotes?.length ?? 0}건
              </button>
              <Analysis value={doc} companyId={id} documentId={doc.id} />
            </article>
          ))}
          {activeDoc && (
            <section aria-label="선택 문서 인용">
              <h3>{activeDoc.title ?? '제목 미제공'} · 근거 인용</h3>
              {!activeDoc.quotes?.length && <p>제공된 근거 인용이 없어요.</p>}
              {activeDoc.quotes?.map((quote) => (
                <div key={quote.evidenceId}>
                  <blockquote>{quote.quote}</blockquote>
                  <p>
                    원문 대조{' '}
                    {quote.quoteVerified === true
                      ? '확인됨'
                      : quote.quoteVerified === false
                        ? '불일치'
                        : '미확인'}
                  </p>
                  <button
                    aria-pressed={evidenceId === quote.evidenceId}
                    onClick={() => updateQuery({ evidence: quote.evidenceId })}
                  >
                    근거 {quote.evidenceId} 상세
                  </button>
                </div>
              ))}
            </section>
          )}
          {selected && !activeDoc && !list.loading && (
            <p role="alert">
              선택한 문서는 현재 기업·시점·필터에 공개되어 있지 않아요.
            </p>
          )}
        </>
      )}
      {evidenceId && (
        <section aria-label="선택 근거 상세">
          <h3>근거 상세</h3>
          <Failure resource={evidence} label="근거" />
          {evidence.data && list.loading && (
            <p role="status">근거의 문서 소속을 확인하고 있어요.</p>
          )}
          {evidence.data &&
            !list.loading &&
            !list.error &&
            (!evidenceContextValid || !evidenceTimeValid ? (
              <p role="alert">
                선택 기업·문서·사건·시점과 일치하지 않는 근거는 표시하지
                않았어요.
              </p>
            ) : (
              <>
                <h4>{evidence.data.article?.title ?? '문서 제목 미제공'}</h4>
                <p>
                  {evidence.data.article?.publisher ?? '출처 미제공'} ·{' '}
                  {evidence.data.article?.publishedAt ?? '발행 시각 미제공'}
                </p>
                <p>
                  관련 설명 · 제공된 인용과 연결 사건 정보입니다. 연결 사건{' '}
                  {evidence.data.eventIds.length}건
                </p>
                <blockquote>{evidence.data.quote}</blockquote>
                <p>
                  원문 대조{' '}
                  {evidence.data.quoteVerified === true
                    ? '확인됨'
                    : evidence.data.quoteVerified === false
                      ? '불일치'
                      : '미확인'}{' '}
                  · 원문 위치 {evidence.data.start}–{evidence.data.end} · 문서
                  버전 {evidence.data.articleVersion}
                </p>
                <Original url={evidence.data.article?.url ?? null} />
                <Analysis
                  value={evidence.data}
                  companyId={id}
                  documentId={evidence.data.articleId}
                />
                <p>
                  공개 버전 {evidence.data.metadata.graphVersion ?? '미제공'} ·
                  자료 기준 {evidence.data.metadata.asOf}
                </p>
              </>
            ))}
          <button onClick={() => updateQuery({ evidence: null })}>
            근거 닫기
          </button>
        </section>
      )}
    </section>
  );
}
