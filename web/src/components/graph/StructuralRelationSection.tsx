import { panelStyles as ui } from '@/components/common/detail-panel-styles';
import type {
  StructuralDetails,
  StructuralSupplyLink,
} from '@/types/map/relation';
import { formatPublishedAt } from './event-format';

const validityLabels = {
  scheduled: '예정',
  active: '유효',
  ended: '종료',
  unknown: '미상',
};

// D-GRP-04 / FS023. Chain order is not supplier→customer direction.
export default function StructuralRelationSection({
  details,
  onEvidence,
}: {
  details?: StructuralDetails;
  onEvidence: (link: StructuralSupplyLink) => void;
}) {
  if (details?.status === 'not_applicable') return null;
  if (details?.status !== 'available' || !details.paths.length) {
    const message = !details
      ? '사업 관계 상세 정보가 아직 제공되지 않습니다.'
      : details.reason === 'legacy_data'
        ? '이 버전에는 사업 관계 상세 정보가 기록되어 있지 않습니다.'
        : details.reason === 'not_recorded'
          ? '이 연결에는 사업 관계 상세 정보가 기록되어 있지 않습니다.'
          : '현재 표시할 수 있는 사업 관계 상세 정보가 없습니다.';
    return (
      <section className={ui.section} aria-label="사업 관계 상세">
        <h3>사업 관계 상세</h3>
        <p className={ui.muted}>{message}</p>
      </section>
    );
  }
  return (
    <section className={ui.section} aria-label="사업 관계 상세">
      <h3>사업 관계 상세</h3>
      <p className={ui.muted}>
        사업 관계를 바탕으로 연결된 경로이며, 사건의 직접 참여나 주가 영향을
        뜻하지 않습니다.
      </p>
      {details.paths.map((path, index) => (
        <div key={path.relationId} className="mt-3">
          <h4 className={ui.itemTitle}>연결 경로 {index + 1}</h4>
          <ol className={ui.list}>
            {path.links.map((link) => {
              const supplier = path.companies.find(
                (company) => company.id === link.supplierCompanyId,
              );
              const customer = path.companies.find(
                (company) => company.id === link.customerCompanyId,
              );
              if (!supplier || !customer || link.relationType !== 'SUPPLIES')
                return (
                  <li key={link.basisId}>
                    현재 표시할 수 있는 사업 관계 상세 정보가 없습니다.
                  </li>
                );
              return (
                <li key={link.basisId}>
                  <p className={ui.itemTitle}>
                    {supplier.label} → {customer.label}
                  </p>
                  <p className={ui.muted}>
                    공급 · {validityLabels[link.validity] ?? '미상'}
                  </p>
                  <dl className="mt-2 grid grid-cols-[80px_1fr] gap-2 break-words">
                    <dt className={ui.muted}>사업 범위</dt>
                    <dd>{link.businessScope ?? '범위 정보 미상'}</dd>
                    <dt className={ui.muted}>제품 범위</dt>
                    <dd>{link.productScope ?? '범위 정보 미상'}</dd>
                    <dt className={ui.muted}>유효 기간</dt>
                    <dd>
                      {link.validFrom ?? '시작일 미상'} ~{' '}
                      {link.validUntil ?? '종료일 미상'}
                    </dd>
                    <dt className={ui.muted}>관계 확인 시각</dt>
                    <dd>
                      {formatPublishedAt(link.verifiedAt) ?? '확인 시점 미제공'}
                    </dd>
                  </dl>
                  <button
                    className={`${ui.button} mt-2`}
                    disabled={!link.evidenceIds.length}
                    onClick={() => onEvidence(link)}
                  >
                    공급 관계 근거 {new Set(link.evidenceIds).size}건 보기
                  </button>
                </li>
              );
            })}
          </ol>
        </div>
      ))}
    </section>
  );
}
