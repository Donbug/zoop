import { panelStyles as ui } from '@/components/common/detail-panel-styles';
import CompanyLogo from '@/components/common/CompanyLogo';
import GraphIcon from '@/components/graph/GraphIcon';
import { useEffect, useRef } from 'react';
import type { Impact } from '@/types/company/detail';
import type { GraphResponse } from '@/types/map/graph';

type Props = {
  companyId: string;
  issueId: string;
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
  issueId,
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
          직접 연결 · 지도 기준{' '}
          {new Date(graph.metadata.asOf).toLocaleString('ko-KR')}
        </p>
      </header>
      <div className={ui.scroll} aria-busy={loading}>
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
            <button onClick={onRetry}>다시 시도</button>
          </div>
        )}
        {impact && (
          <>
            <div className={ui.actions}>
              <button onClick={onViewIssue}>사건 상세 보기</button>
              <button className="bg-panel-ink! text-white!" onClick={onAskAi}>
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
                <p className={ui.muted}>확인된 영향 경로가 없습니다.</p>
              )}
            </section>
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
                          {edge.summary || '직접 관련'} · 근거{' '}
                          {edge.evidenceIds.length}건
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
