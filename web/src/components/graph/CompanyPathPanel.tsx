import { useEffect, useRef, useState } from 'react';
import { panelStyles as ui } from '@/components/common/detail-panel-styles';
import type { GraphResponse } from '@/types/map/graph';
import { companyPath } from './company-path';

// D-GRP-07 · two-company path (user decision 2026-10-17).
export default function CompanyPathPanel({
  graph,
  from,
  to,
  loading,
  error,
  onPick,
  onClose,
  onRetry,
  onEvidence,
}: {
  graph: GraphResponse | null;
  from: string;
  to: string | null;
  loading: boolean;
  error: string | null;
  onPick: (id: string) => void;
  onClose: () => void;
  onRetry: () => void;
  onEvidence: (id: string) => void;
}) {
  const [query, setQuery] = useState('');
  const heading = useRef<HTMLHeadingElement>(null);
  useEffect(() => {
    heading.current?.focus();
  }, [from, to]);
  const companies = graph?.nodes.filter((n) => n.kind === 'company') ?? [];
  const source = companies.find((n) => n.id === from);
  const target = companies.find((n) => n.id === to);
  const path = graph && to ? companyPath(graph, from, to) : null;
  return (
    <aside
      className={ui.shell}
      data-screen-id="D-GRP-07"
      aria-label="두 기업 사이 경로"
      onKeyDown={(e) => {
        if (e.key === 'Escape') {
          e.stopPropagation();
          onClose();
        }
      }}
    >
      <header className={ui.header}>
        <div className="flex items-start justify-between gap-2">
          <h2 ref={heading} tabIndex={-1} className={ui.title}>
            {source?.label ?? from} ↔ {target?.label ?? '다른 기업'}
          </h2>
          <button className={ui.close} aria-label="경로 닫기" onClick={onClose}>
            ×
          </button>
        </div>
        {to && (
          <button className={`${ui.button} mt-3`} onClick={() => onPick('')}>
            다른 기업 고르기
          </button>
        )}
      </header>
      <div className={ui.scroll}>
        {loading ? (
          <p className={ui.state} role="status">
            경로의 기준 그래프를 확인하고 있어요.
          </p>
        ) : error ? (
          <div className={ui.state} role="alert">
            그래프 조회 실패 <button onClick={onRetry}>다시 시도</button>
          </div>
        ) : !source ? (
          <p className={ui.state}>
            선택한 기업이 조회 범위에 없습니다. 전체 보기에서 다시 선택해
            주세요.
          </p>
        ) : !to ? (
          <section className={ui.section}>
            <h3>두 번째 기업 선택</h3>
            <label className="block">
              기업 검색
              <input
                value={query}
                onChange={(e) => setQuery(e.target.value)}
                className="my-2 w-full rounded-panel border border-panel-line px-2 py-2"
              />
            </label>
            <ul className={ui.list}>
              {companies
                .filter(
                  (n) =>
                    n.id !== from &&
                    n.label.toLowerCase().includes(query.toLowerCase()),
                )
                .map((n) => (
                  <li key={n.id}>
                    <button
                      className="w-full py-2 text-left"
                      onClick={() => onPick(n.id)}
                    >
                      {n.label}
                    </button>
                  </li>
                ))}
            </ul>
          </section>
        ) : !target ? (
          <p className={ui.state}>
            비교 기업이 조회 범위에 없습니다. 다른 기업을 골라 주세요.
          </p>
        ) : !path ? (
          <p className={ui.state} role="status">
            조회한 그래프 안에서 두 기업 사이 경로를 찾지 못했어요.
          </p>
        ) : (
          <section className={ui.section}>
            <h3>{path.edgeIds.length}단계 연결</h3>
            <ol className="space-y-4">
              {path.nodes.map((node, i) => (
                <li key={node.id} className="border-l border-panel-line pl-3">
                  <span className={ui.muted}>
                    {node.kind === 'company' ? '기업' : '사건'}
                  </span>
                  <strong className="block text-xs">{node.label}</strong>
                  {i < path.edgeIds.length && (
                    <p className={ui.muted}>
                      {
                        graph?.edges.find((e) => e.id === path.edgeIds[i])
                          ?.summary
                      }
                    </p>
                  )}
                  {node.kind === 'issue' && (
                    <button
                      className={`${ui.button} mt-2`}
                      onClick={() => onEvidence(node.id)}
                    >
                      근거 보기
                    </button>
                  )}
                </li>
              ))}
            </ol>
          </section>
        )}
        <footer className={ui.footer}>
          조회된 그래프 안의 최단 무방향 연결입니다. 영향이나 인과관계를 뜻하지
          않아요.
          {graph?.metadata.truncated && (
            <p>조회 상한으로 일부 관계가 생략되었습니다.</p>
          )}
          {graph?.metadata.partial && <p>일부 자료를 받지 못했습니다.</p>}
        </footer>
      </div>
    </aside>
  );
}
