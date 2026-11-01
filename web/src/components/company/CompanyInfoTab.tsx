import type { Resource } from '@/hooks/useCompanyResource';
import type { Company } from '@/types/company/detail';
import { panelStyles as ui } from '@/components/common/detail-panel-styles';
import LoadingIndicator from '@/components/common/LoadingIndicator';

const fields = [
  ['legalName', '정식 법인명'],
  ['market', '시장'],
  ['sector', '업종'],
  ['representative', '대표자'],
  ['foundedDate', '설립일'],
] as const;
const provided = (value: string | null) => value?.trim() || null;
function website(value: string | null) {
  if (!value) return null;
  try {
    const url = new URL(value);
    return ['http:', 'https:'].includes(url.protocol) &&
      !url.username &&
      !url.password
      ? url.href
      : null;
  } catch {
    return null;
  }
}

// WBS6.7.10 calls this D-COM-03; manifest's approved info-tab image is D-COM-01.
// Reuse the parent's getCompany snapshot rather than issuing another request.
export default function CompanyInfoTab({
  resource,
}: {
  resource: Resource<Company>;
}) {
  const company = resource.data;
  const href = website(company?.websiteUrl ?? null);
  const permission =
    [401, 403].includes(resource.errorStatus ?? 0) ||
    ['ACCESS_DENIED', 'MEMBER_REQUIRED'].includes(resource.errorCode ?? '');
  // F04·F05: 없음(404)·버전 없음(409)·재시도 불가 장애는 다시 보내도 같으므로 다시 조회를 두지 않는다.
  const canRetry =
    !permission &&
    resource.errorStatus !== 404 &&
    resource.errorCode !== 'VERSION_UNAVAILABLE' &&
    resource.errorRetryable !== false;
  return (
    <section
      aria-label="기업 기준정보"
      aria-busy={resource.loading}
      data-screen-id="D-COM-03"
      data-wireframe-screen-id="D-COM-01"
    >
      <h2>기업 기준정보</h2>
      {resource.loading ? (
        <LoadingIndicator
          label="기업 기준정보를 불러오고 있어요."
          className="flex min-h-12 w-full"
        />
      ) : resource.error ? (
        <div role="alert">
          <p>
            {permission
              ? '기업 기준정보를 조회할 권한이 없어요.'
              : resource.errorStatus === 404
                ? '기업 기준정보를 찾을 수 없어요.'
                : resource.errorCode === 'VERSION_UNAVAILABLE'
                  ? '선택한 공개 버전의 기업 기준정보를 확인할 수 없어요. [최신 시점]으로 돌아가 확인해 주세요.'
                  : resource.errorRetryable === false
                    ? '자료 공급원의 설정이나 응답 형식 문제로 기업 기준정보를 확인할 수 없어요.'
                    : '기업 기준정보를 불러오지 못했어요.'}
          </p>
          {canRetry && (
            <button
              type="button"
              className={ui.button}
              onClick={resource.retry}
            >
              기업 기준정보 다시 조회
            </button>
          )}
        </div>
      ) : company ? (
        <>
          {!fields.some(([key]) => provided(company[key])) && !href && (
            <p role="status">확인된 기업 기준정보가 없습니다.</p>
          )}
          <dl className="grid grid-cols-2 gap-x-4 text-caption max-sm:grid-cols-1">
            {fields.map(([key, label]) => (
              <div
                key={key}
                className="min-w-0 border-b border-zoop-border py-4"
              >
                <dt className="text-zoop-muted">{label}</dt>
                <dd className="mt-1 font-semibold wrap-anywhere">
                  {provided(company[key]) ?? '미제공'}
                </dd>
              </div>
            ))}
            <div className="min-w-0 border-b border-zoop-border py-4">
              <dt className="text-zoop-muted">홈페이지</dt>
              <dd className="mt-1 wrap-anywhere">
                {href ? (
                  <a
                    href={href}
                    target="_blank"
                    rel="noopener noreferrer"
                    className="inline-block underline underline-offset-2 focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-zoop-ink"
                    aria-label="공식 웹사이트"
                  >
                    {href}
                  </a>
                ) : (
                  '미제공'
                )}
              </dd>
            </div>
          </dl>
          {company.metadata.partial && (
            <div
              role="status"
              className="my-3 border-l-2 border-zoop-faint bg-zoop-soft p-3"
            >
              <p>
                일부 기업 자료를 불러오지 못했어요. 확인된 항목만 표시합니다.
              </p>
              {(company.metadata.failures ?? []).map((failure, i) => (
                <p key={`${failure.section}:${i}`}>{failure.message}</p>
              ))}
              <button
                type="button"
                className={ui.button}
                onClick={resource.retry}
              >
                기업 기준정보 다시 조회
              </button>
            </div>
          )}
          <p className="mt-4 wrap-anywhere">
            조회 출처 {company.metadata.source} · 관계·요약 자료 기준{' '}
            {company.metadata.asOf} · 공개 버전{' '}
            {company.metadata.graphVersion ?? '미제공'}
          </p>
          <p>기업 기준정보의 별도 갱신 시각은 제공되지 않았습니다.</p>
        </>
      ) : (
        <p role="status">기업 기준정보가 제공되지 않았습니다.</p>
      )}
    </section>
  );
}
