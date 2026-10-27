import { panelStyles as ui } from '@/components/common/detail-panel-styles';
import CompanyLogo from '@/components/common/CompanyLogo';
import GraphIcon from '@/components/graph/GraphIcon';
import { useEffect, useRef, useState } from 'react';
import { useRelationData } from '@/hooks/useRelationData';
import type { Impact } from '@/types/company/detail';
import type { EventContext } from '@/types/map/event';
import type { GraphResponse } from '@/types/map/graph';
import type { StructuralSupplyLink } from '@/types/map/relation';
import StructuralRelationSection from './StructuralRelationSection';

type Props = {
  tutorialEvidence?: boolean;
  tutorialAi?: boolean;
  tutorialSaving?: boolean;
  companyId: string;
  issueId: string;
  context: EventContext;
  graph: GraphResponse;
  impact: Impact | null;
  loading: boolean;
  error: string | null;
  onRetry: () => void;
  onClose: () => void;
  onViewIssue: () => void;
  onEvidence: (evidenceIds: string[]) => void;
  onAskAi: () => void;
};

const unique = (items: string[]) => [...new Set(items)];

// WBS 6.6.26 · D-GRP-06 · Figma 619:8880
export default function ImpactPathPanel({
  companyId,
  tutorialEvidence = false,
  tutorialAi = false,
  tutorialSaving = false,
  issueId,
  context,
  graph,
  impact,
  loading,
  error,
  onRetry,
  onClose,
  onViewIssue,
  onEvidence,
  onAskAi,
}: Props) {
  const heading = useRef<HTMLHeadingElement>(null);
  useEffect(() => {
    heading.current?.focus();
  }, [companyId, issueId]);
  const company = graph.nodes.find((node) => node.id === companyId);
  const structuralEdge = graph.edges.find(
    (edge) =>
      !edge.derived &&
      edge.relationType === 'STRUCTURALLY_RELATED_TO' &&
      [edge.source, edge.target].includes(companyId) &&
      [edge.source, edge.target].includes(issueId),
  );
  const evidenceIds = unique(
    impact?.steps.flatMap((step) => step.evidenceIds) ?? [],
  );
  const connectedCompanies = graph.edges
    .filter(
      (edge) =>
        !edge.derived &&
        (edge.source === issueId || edge.target === issueId) &&
        (edge.relationType === 'INVOLVES' ||
          edge.relationType === 'STRUCTURALLY_RELATED_TO'),
    )
    .map((edge) => {
      const connectedId = edge.source === issueId ? edge.target : edge.source;
      return {
        edge,
        company:
          connectedId === companyId
            ? undefined
            : graph.nodes.find((node) => node.id === connectedId),
      };
    })
    .filter((item) => item.company?.kind === 'company');

  return (
    <aside
      className={`event-panel ${ui.shell}`}
      data-screen-id="D-GRP-06"
      aria-labelledby="impact-panel-title"
      onKeyDown={(event) => {
        if (event.key === 'Escape') onClose();
      }}
    >
      <header className={ui.header}>
        <button
          className={`absolute top-4 right-4 ${ui.close}`}
          onClick={onClose}
          aria-label="영향 경로 닫기"
        >
          ×
        </button>
        <h2
          id="impact-panel-title"
          ref={heading}
          tabIndex={-1}
          className={`${ui.title} pr-10`}
        >
          {company?.label ?? companyId} · 영향 경로
        </h2>
        <p className={ui.muted}>
          {loading
            ? '연결 확인 중'
            : error
              ? '연결 확인 불가'
              : impact?.pathStatus === 'structural_path_details_unavailable'
                ? '구조 관계 확인'
                : impact?.pathStatus === 'direct_available'
                  ? '직접 연결 확인'
                  : impact?.pathStatus === 'no_direct_relation'
                    ? '직접 연결 미확인'
                    : impact?.steps.length
                      ? '연결 확인'
                      : '직접 연결 미확인'}{' '}
          · 지도 기준 {new Date(graph.metadata.asOf).toLocaleString('ko-KR')}
        </p>
      </header>
      <div className={ui.scroll} aria-busy={loading}>
        {impact?.metadata.partial && (
          <p className="px-4 py-2 text-[11px] text-zoop-alert" role="status">
            현재 공개 권한을 확인할 수 있는 근거만 표시합니다.
          </p>
        )}
        {loading && (
          <div className={ui.state} role="status">
            <span className="block h-14 rounded-panel bg-panel-line motion-safe:animate-pulse" />
            <p>영향 경로를 불러오는 중입니다.</p>
          </div>
        )}
        {error && (
          <div className={ui.state} role="alert">
            <strong>영향 경로를 불러오지 못했습니다.</strong>
            <p>{error}</p>
            <p>지도와 기업 선택은 그대로 유지됩니다.</p>
            <button data-tutorial-action="retry" onClick={onRetry}>
              다시 시도
            </button>
          </div>
        )}
        {impact && (
          <>
            <div className={ui.actions}>
              <button onClick={onViewIssue}>사건 상세 보기</button>
              <button
                className={`bg-panel-ink! text-white! ${tutorialAi ? 'tutorial-target tutorial-ai-target' : ''}`}
                disabled={tutorialSaving}
                onClick={onAskAi}
              >
                <GraphIcon name="ai" size={14} />
                AI에게 묻기
              </button>
            </div>
            <section
              className={ui.section}
              aria-labelledby="impact-route-title"
            >
              <h3 id="impact-route-title">확인된 연결</h3>
              {impact.steps.length ? (
                <ol className="m-0 list-none p-0">
                  {impact.steps.map((step, index) => {
                    const node = graph.nodes.find(
                      (item) => item.id === step.id,
                    );
                    const stepEvidence = unique(step.evidenceIds);
                    return (
                      <li
                        key={`${step.id}-${index}`}
                        className="relative flex gap-2.5 py-2.5 not-last:border-b not-last:border-panel-line"
                      >
                        {node?.kind === 'company' ? (
                          <CompanyLogo
                            name={node.label}
                            logoUrl={node.logoUrl}
                            className={ui.avatar}
                          />
                        ) : (
                          <span className={ui.avatar} aria-hidden="true">
                            {node ? '◇' : '•'}
                          </span>
                        )}
                        <div className="min-w-0 flex-1">
                          <p className={ui.muted}>
                            {node?.kind === 'issue' ? '사건' : '기업'} ·{' '}
                            {step.reason}
                          </p>
                          <strong className={ui.itemTitle}>
                            {node?.label ?? step.id}
                          </strong>
                          <button
                            className="mt-1 text-[11px] font-semibold underline disabled:text-panel-muted"
                            disabled={stepEvidence.length === 0}
                            data-tutorial-action={
                              tutorialEvidence ? 'evidence' : undefined
                            }
                            data-tutorial-evidence={
                              tutorialEvidence || undefined
                            }
                            onClick={() => onEvidence(stepEvidence)}
                          >
                            근거 {stepEvidence.length}건 보기
                          </button>
                        </div>
                      </li>
                    );
                  })}
                </ol>
              ) : (
                <p className={ui.muted}>
                  {impact.pathStatus === 'structural_path_details_unavailable'
                    ? '구조 관계가 공개 그래프에서 확인됐습니다. 경로 상세와 단계별 근거는 아래 사업 관계 상세에서 확인합니다.'
                    : '선택한 그래프에서 기업과 이슈 사이의 직접 연결을 확인하지 못했습니다.'}
                </p>
              )}
            </section>
            {structuralEdge && (
              <StructuralImpactDetails
                key={`${structuralEdge.id}:${JSON.stringify(context)}`}
                edgeId={structuralEdge.id}
                context={context}
                onEvidence={(link) => onEvidence(unique(link.evidenceIds))}
              />
            )}
            <section
              className={ui.section}
              aria-labelledby="impact-company-title"
            >
              <h3 id="impact-company-title">
                함께 연결된 기업 {connectedCompanies.length}곳
              </h3>
              {connectedCompanies.length ? (
                <ul className={`${ui.list} [&>li]:flex [&>li]:gap-2.5`}>
                  {connectedCompanies.map(({ edge, company: connected }) => (
                    <li key={edge.id}>
                      <CompanyLogo
                        name={connected?.label ?? ''}
                        logoUrl={connected?.logoUrl}
                        className={ui.avatar}
                      />
                      <div className="min-w-0">
                        <strong className={ui.itemTitle}>
                          {connected?.label}
                        </strong>
                        <p className={ui.muted}>
                          {edge.summary || '공개 그래프 연결'}
                        </p>
                      </div>
                    </li>
                  ))}
                </ul>
              ) : (
                <p className={ui.muted}>함께 연결된 다른 기업이 없습니다.</p>
              )}
            </section>
            <section
              className={ui.section}
              aria-labelledby="impact-limit-title"
            >
              <h3 id="impact-limit-title">해석 한계</h3>
              <ul className="list-disc space-y-1 pl-4 text-panel-secondary">
                <li>
                  위 연결은 기사에 적힌 사실과 승인된 사업 관계이며, 주가나 실적
                  영향을 판단하지 않아요.
                </li>
                <li>
                  계획·전망 표현은 실제 발생이 확인된 사건과 구분해서 살펴봐야
                  해요.
                </li>
              </ul>
            </section>
            <footer className={ui.footer}>
              <p>{impact.metadata.source}</p>
              <p>경로 근거 {evidenceIds.length}건 · 화면 ID D-GRP-06</p>
            </footer>
          </>
        )}
      </div>
    </aside>
  );
}

function StructuralImpactDetails({
  edgeId,
  context,
  onEvidence,
}: {
  edgeId: string;
  context: EventContext;
  onEvidence: (link: StructuralSupplyLink) => void;
}) {
  const [retry, setRetry] = useState(0);
  const { data, loading, error } = useRelationData(edgeId, context, retry);
  const failure = data?.metadata.failures.find(
    (item) => item.section === 'structuralDetails',
  );
  if (loading && !data)
    return (
      <section className={ui.section} aria-label="사업 관계 상세" role="status">
        사업 관계 상세를 불러오는 중입니다.
      </section>
    );
  if (error && !data)
    return (
      <section className={ui.section} aria-label="사업 관계 상세" role="alert">
        <p>사업 관계 상세를 불러오지 못했습니다.</p>
        <p>{error}</p>
        <button onClick={() => setRetry((value) => value + 1)}>
          다시 시도
        </button>
      </section>
    );
  if (!data) return null;
  return (
    <StructuralRelationSection
      details={data.structuralDetails}
      failure={failure}
      onRetry={() => setRetry((value) => value + 1)}
      onEvidence={onEvidence}
    />
  );
}
