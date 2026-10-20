import { companyLogo } from '@/util/company-logo';
import CompanyLogo from '@/components/common/CompanyLogo';
import type { EventContext } from '@/types/map/event';
import { panelStyles as ui } from '@/components/common/detail-panel-styles';
import { useEffect, useMemo, useRef, useState } from 'react';
import { Link } from 'react-router-dom';
import { setWatchlistCompany } from '@/apis/graph/companies';
import { useCompanyData } from '@/hooks/useCompanyData';
import type { GraphNode } from '@/types/map/graph';

type RelatedCompany = { id: string; name: string; sharedIssueCount: number };
type Props = {
  companyId: string;
  context?: EventContext;
  fallback: GraphNode;
  relatedCompanies: RelatedCompany[];
  token: string | null;
  onClose: () => void;
  onSelectIssue: (id: string) => void;
  onFocus: () => void;
  onConnections: () => void;
  onSelectRelation?: (companyId: string) => void;
  onAskAi: () => void;
};

function number(value: number | null, currency?: string) {
  if (value === null) return '—';
  return new Intl.NumberFormat('ko-KR', {
    maximumFractionDigits: currency === 'KRW' ? 0 : 2,
  }).format(value);
}

function Sparkline({ values }: { values: number[] }) {
  const points = useMemo(() => {
    if (values.length < 2) return '';
    const min = Math.min(...values);
    const range = Math.max(1, Math.max(...values) - min);
    return values
      .map(
        (value, index) =>
          `${(index / (values.length - 1)) * 280},${76 - ((value - min) / range) * 64}`,
      )
      .join(' ');
  }, [values]);
  return (
    <svg
      className="company-sparkline"
      viewBox="0 0 280 84"
      role="img"
      aria-label="최근 1개월 가격 추이"
    >
      <line x1="0" y1="76" x2="280" y2="76" />
      <polyline points={points} />
    </svg>
  );
}

function SectionError({
  message,
  retry,
}: {
  message?: string;
  retry: () => void;
}) {
  if (!message) return null;
  return (
    <p className="company-section-error" role="alert">
      일부 정보를 불러오지 못했습니다.{' '}
      <button onClick={retry}>다시 시도</button>
    </p>
  );
}

// WBS 6.6.23 · D-GRP-03 · Figma 619:6729
export default function CompanyDetailPanel(props: Props) {
  const heading = useRef<HTMLHeadingElement>(null);
  useEffect(() => {
    heading.current?.focus();
  }, [props.companyId]);
  const [retry, setRetry] = useState(0);
  const { data, loading, errors } = useCompanyData(
    props.companyId,
    props.token,
    retry,
    props.context,
  );
  const [watchOverride, setWatchOverride] = useState<boolean | null>(null);
  const [saving, setSaving] = useState(false);
  const [watchError, setWatchError] = useState('');
  const company = data?.company;
  const watch = watchOverride ?? Boolean(company?.watch);

  async function toggleWatch() {
    if (!props.token || saving) return;
    const previous = watch;
    const desired = !previous;
    setWatchOverride(desired);
    setSaving(true);
    setWatchError('');
    try {
      const settings = await setWatchlistCompany(props.companyId, desired);
      setWatchOverride(settings.watchlistIds.includes(props.companyId));
    } catch {
      setWatchOverride(previous);
      setWatchError('관심기업 저장에 실패했습니다. 다시 시도해 주세요.');
    } finally {
      setSaving(false);
    }
  }

  const quote = data?.quote?.status === 'available' ? data.quote : null;
  const prices = data?.prices?.status === 'available' ? data.prices : null;
  const metrics = data?.metrics?.status === 'available' ? data.metrics : null;
  const name = company?.name ?? props.fallback.label;
  const logoUrl = companyLogo(
    props.fallback.id,
    company?.logoUrl ?? props.fallback.logoUrl,
  );
  const currency = quote?.quote.currency;
  const changePositive = (quote?.quote.change ?? 0) >= 0;

  return (
    <aside
      className={`company-panel ${ui.shell}`}
      data-screen-id="D-GRP-03"
      aria-label={`${name} 기업 상세`}
      onKeyDown={(event) => {
        if (event.key === 'Escape') {
          event.stopPropagation();
          props.onClose();
        }
      }}
    >
      <header className="company-panel-header">
        <div className="company-panel-title">
          <h2 className={ui.title} ref={heading} tabIndex={-1}>
            {name}
          </h2>
          <button
            className={ui.close}
            onClick={props.onClose}
            aria-label="기업 상세 닫기"
          >
            ×
          </button>
        </div>
        <div className="company-identity">
          <CompanyLogo
            name={name}
            logoUrl={logoUrl}
            className="size-[30px] rounded-full border border-zoop-line bg-zoop-paper text-[11.4px] font-extrabold"
          />
          <div className="company-identity-meta">
            <p>{company?.ticker ?? props.companyId.split(':')[1]}</p>
            <div className="company-statuses">
              {(company?.holding || props.fallback.holding) && (
                <span>보유 종목</span>
              )}
              {(company?.watch || props.fallback.watch) && (
                <span>관심 종목</span>
              )}
            </div>
          </div>
        </div>
        {company && company.aliases.length > 0 && (
          <details className="company-aliases">
            <summary>기업명 더 보기</summary>
            <p>{company.aliases.join(' · ')}</p>
          </details>
        )}
      </header>
      {loading && (
        <p className="company-panel-loading" role="status">
          기업 정보를 불러오는 중…
        </p>
      )}
      {!loading && !company && (
        <div className="company-panel-fatal" role="alert">
          <p>기업 정보를 불러오지 못했습니다.</p>
          <button onClick={() => setRetry((value) => value + 1)}>
            다시 시도
          </button>
        </div>
      )}
      {company && (
        <div className={`company-panel-scroll ${ui.scroll}`}>
          <section className={`company-quote ${ui.sectionFrame}`}>
            <h3 className="sr-only">시세</h3>
            {quote ? (
              <>
                <div className="company-price-row">
                  <strong>
                    {number(quote.quote.price, currency)}{' '}
                    <small>{currency}</small>
                  </strong>
                  <p className={changePositive ? 'up' : 'down'}>
                    {changePositive ? '▲ +' : '▼ '}
                    {number(quote.quote.change, currency)} (
                    {changePositive ? '+' : ''}
                    {((quote.quote.changeRate ?? 0) * 100).toFixed(2)}%)
                  </p>
                </div>
                <div className="company-quote-meta">
                  <span>
                    전일 대비 · 기준{' '}
                    {quote.quote.asOf
                      ? new Date(quote.quote.asOf).toLocaleString('ko-KR')
                      : '미제공'}{' '}
                    · {quote.source.name}
                    {quote.source.delayNote ? ' · 지연 가능' : ''}
                  </span>
                  <details className="company-source">
                    <summary aria-label={`시세 출처: ${quote.source.name}`}>
                      i
                    </summary>
                    <p>
                      {quote.source.name} ·{' '}
                      {quote.source.official ? '공식' : '공개 자료'} · 종목 기호{' '}
                      {quote.source.symbol}
                    </p>
                  </details>
                </div>
                <div className="company-stat-grid">
                  <span>
                    거래량 <b>{number(quote.quote.volume)}</b>
                  </span>
                  <span>
                    일중 범위{' '}
                    <b>
                      {number(quote.quote.dayLow)}–{number(quote.quote.dayHigh)}
                    </b>
                  </span>
                  <span>
                    52주 범위{' '}
                    <b>
                      {number(quote.quote.fiftyTwoWeekLow)}–
                      {number(quote.quote.fiftyTwoWeekHigh)}
                    </b>
                  </span>
                </div>
              </>
            ) : data.quote?.status === 'unavailable' ? (
              <p className="company-unavailable">
                시세 미제공 · {data.quote.reason}
              </p>
            ) : null}
            <SectionError
              message={errors.quote}
              retry={() => setRetry((value) => value + 1)}
            />
            {prices ? (
              <figure className="company-price-chart">
                <figcaption>최근 1개월 시세 추이</figcaption>
                <Sparkline values={prices.points.map((point) => point.close)} />
                <p className="company-chart-range">
                  <span>{prices.points.at(0)?.time.slice(0, 10)}</span>
                  <span>{prices.points.at(-1)?.time.slice(0, 10)}</span>
                </p>
                <p className="company-caption">
                  {prices.source.name} · 마지막 거래{' '}
                  {prices.points.at(-1)?.time.slice(0, 10)}
                </p>
              </figure>
            ) : data.prices?.status === 'unavailable' ? (
              <p className="company-unavailable">
                가격 추이 미제공 · {data.prices.reason}
              </p>
            ) : null}
            <SectionError
              message={errors.prices}
              retry={() => setRetry((value) => value + 1)}
            />
          </section>
          <details className={`company-metrics ${ui.sectionFrame}`}>
            <summary>
              주요 지표{' '}
              <span>{metrics ? `${metrics.items.length}개` : '—'}</span>
            </summary>
            {metrics?.items.map((item) => (
              <p key={item.code}>
                <span>{item.label}</span>
                <b>{item.value}</b>
              </p>
            ))}
            {data.metrics?.status === 'unavailable' && (
              <p className="company-unavailable">
                지표 미제공 · {data.metrics.reason}
              </p>
            )}
            <SectionError
              message={errors.metrics}
              retry={() => setRetry((value) => value + 1)}
            />
          </details>
          <section className={ui.sectionFrame}>
            <div className="company-section-title">
              <h3>가상 계좌 보유</h3>
            </div>
            {!props.token ? (
              <p className="company-unavailable">
                <Link to="/login">로그인</Link>하면 보유 정보를 확인할 수
                있습니다.
              </p>
            ) : data.holding ? (
              <div className="company-holding">
                <span>
                  수량 <b>{number(data.holding.quantity)}주</b>
                </span>
                <span>
                  평균 단가{' '}
                  <b>
                    {number(data.holding.avgPrice)}{' '}
                    {data.holding.avgPriceCurrency}
                  </b>
                </span>
                <span>
                  평가액{' '}
                  <b>
                    {data.holding.marketValue === null
                      ? '제공되지 않음'
                      : number(data.holding.marketValue)}
                  </b>
                </span>
                <span>
                  비중{' '}
                  <b>
                    {data.holding.weight === null
                      ? '통화 혼합으로 계산 안 함'
                      : `${data.holding.weight}%`}
                  </b>
                </span>
              </div>
            ) : (
              <p className="company-unavailable">
                이 기업의 모의 보유 내역이 없습니다.
              </p>
            )}
            <SectionError
              message={errors.holding}
              retry={() => setRetry((value) => value + 1)}
            />
          </section>
          <div
            className={`company-actions ${ui.actions} [&>:last-child]:col-span-2`}
          >
            <Link to={`/companies/${encodeURIComponent(company.id)}`}>
              기업 상세
            </Link>
            {props.token ? (
              <button
                onClick={() => void toggleWatch()}
                disabled={saving}
                aria-pressed={watch}
              >
                {saving ? '저장 중…' : watch ? '★ 관심 해제' : '☆ 관심 추가'}
              </button>
            ) : (
              <Link to="/login">로그인 후 관심 추가</Link>
            )}
            <button onClick={props.onFocus}>이 기업 중심으로 보기</button>
            <button onClick={props.onConnections}>다른 기업과 연결 보기</button>
            <button
              className="col-span-2 bg-panel-ink! text-white!"
              onClick={props.onAskAi}
            >
              AI에게 이 기업 묻기
            </button>
          </div>
          {watchError && (
            <p className="company-watch-error" role="alert">
              {watchError}{' '}
              <button onClick={() => void toggleWatch()}>재시도</button>
            </p>
          )}
          <section className={ui.sectionFrame}>
            <div className="company-section-title">
              <h3>직접 관련 사건</h3>
              <span>{company.directIssues.length}</span>
            </div>
            {company.directIssues.length ? (
              <ul className="company-list">
                {company.directIssues.map((issue) => (
                  <li key={issue.issueId}>
                    <button onClick={() => props.onSelectIssue(issue.issueId)}>
                      <b>{issue.title}</b>
                      <span>
                        {issue.eventTime ?? '시각 미상'} · 근거{' '}
                        {issue.evidenceCount}건
                      </span>
                    </button>
                  </li>
                ))}
              </ul>
            ) : (
              <p className="company-unavailable">직접 관련 사건이 없습니다.</p>
            )}
          </section>
          <section className={ui.sectionFrame}>
            <div className="company-section-title">
              <h3>간접 관련 사건</h3>
              <span>{company.structuralIssues.length}</span>
            </div>
            {company.structuralIssues.length ? (
              <ul className="company-list">
                {company.structuralIssues.map((issue) => (
                  <li key={issue.issueId}>
                    <button onClick={() => props.onSelectIssue(issue.issueId)}>
                      <b>{issue.title}</b>
                      <span>구조적 연관 · 근거 {issue.evidenceCount}건</span>
                    </button>
                  </li>
                ))}
              </ul>
            ) : (
              <p className="company-unavailable">
                확인된 간접 관련 사건이 없습니다.
              </p>
            )}
          </section>
          <section className={ui.sectionFrame}>
            <div className="company-section-title">
              <h3>관련 기업</h3>
              <span>{props.relatedCompanies.length}</span>
            </div>
            {props.relatedCompanies.length ? (
              <ul className="company-list">
                {props.relatedCompanies.slice(0, 5).map((related) => (
                  <li key={related.id}>
                    <button
                      onClick={() => props.onSelectRelation?.(related.id)}
                    >
                      <b>{related.name}</b>
                      <span>공유 사건 {related.sharedIssueCount}건</span>
                    </button>
                  </li>
                ))}
              </ul>
            ) : (
              <p className="company-unavailable">
                확인된 관련 기업이 없습니다.
              </p>
            )}
          </section>
          <section className={ui.sectionFrame}>
            <div className="company-section-title">
              <h3>뉴스·공시</h3>
              <span>{data.documents?.items.length ?? '—'}</span>
            </div>
            {data.documents?.items.length ? (
              <ul className="company-list">
                {data.documents.items.map((document) => (
                  <li key={document.id}>
                    {document.url ? (
                      <a href={document.url} target="_blank" rel="noreferrer">
                        <b>{document.title ?? '제목 없음'}</b>
                        <span>
                          {document.kind === 'news' ? '뉴스' : '공시'} ·{' '}
                          {document.publisher ?? '출처 미상'} ·{' '}
                          {document.publishedAt?.slice(0, 10) ?? '시각 미상'}
                        </span>
                      </a>
                    ) : (
                      <div className="company-document">
                        <b>{document.title ?? '제목 없음'}</b>
                        <span>
                          {document.kind === 'news' ? '뉴스' : '공시'} ·{' '}
                          {document.publisher ?? '출처 미상'} · 원문 링크 미제공
                        </span>
                      </div>
                    )}
                  </li>
                ))}
              </ul>
            ) : !errors.documents ? (
              <p className="company-unavailable">
                표시할 뉴스·공시가 없습니다.
              </p>
            ) : null}
            <SectionError
              message={errors.documents}
              retry={() => setRetry((value) => value + 1)}
            />
          </section>
        </div>
      )}
    </aside>
  );
}
