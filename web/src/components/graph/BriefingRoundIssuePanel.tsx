import { useCallback } from 'react';
import { Link } from 'react-router-dom';
import { getBriefing, getBriefingGraphBasis } from '@/apis/briefing/briefing';
import BriefingItemDetails from '@/components/briefing/BriefingItemDetails';
import { panelStyles as ui } from '@/components/common/detail-panel-styles';
import LoadingIndicator from '@/components/common/LoadingIndicator';
import { useAsyncData } from '@/hooks/useAsyncData';

/** D-BRF-04: keep the issue text/citations bound to its original publication, even when the map was reconstructed. */
export default function BriefingRoundIssuePanel({
  roundId,
  eventId,
  graphVersion,
  onClose,
}: {
  roundId: string;
  eventId: string;
  graphVersion: string | null;
  onClose: () => void;
}) {
  const load = useCallback(async () => {
    const basis = await getBriefingGraphBasis(roundId);
    if (basis.status !== 'available' || basis.graphVersion !== graphVersion)
      throw new Error('회차 지도 기준을 다시 확인해 주세요.');
    const publication = await getBriefing(basis.date, basis.edition);
    const item = publication.items.find((value) => value.eventId === eventId);
    if (
      publication.id !== roundId ||
      publication.status !== 'published' ||
      !item
    )
      throw new Error('이 회차에 저장된 핵심 이슈를 찾지 못했습니다.');
    return { item, publication, basis };
  }, [roundId, eventId, graphVersion]);
  const result = useAsyncData(load);
  return (
    <aside
      className={ui.shell}
      aria-label="회차 핵심 이슈 상세"
      data-screen-id="D-BRF-04"
    >
      <header className={ui.header}>
        <h2 className={ui.title}>회차 핵심 이슈</h2>
        <button
          type="button"
          className={ui.close}
          aria-label="핵심 이슈 상세 닫기"
          onClick={onClose}
        >
          ×
        </button>
      </header>
      <div className={ui.scroll}>
        {result.status === 'loading' && (
          <LoadingIndicator
            label="발행본을 확인하고 있어요."
            className={`${ui.state} flex min-h-12 w-full`}
          />
        )}
        {result.status === 'error' && (
          <div className={ui.state} role="alert">
            회차 이슈를 불러오지 못했습니다.{' '}
            <button className={ui.button} onClick={result.reload}>
              다시 시도
            </button>
          </div>
        )}
        {result.status === 'success' && result.data && (
          <section className={ui.section}>
            <h3 className={ui.itemTitle}>{result.data.item.title}</h3>
            {result.data.basis.graphOrigin === 'reconstructed' && (
              <p className={ui.muted}>
                지도는 재구성본이며, 아래 문안·인용은 원래 브리핑에 저장된
                내용입니다.
              </p>
            )}
            {'text' in result.data.item.summary && (
              <p className="whitespace-pre-line">
                {result.data.item.summary.text}
              </p>
            )}
            <p className={ui.muted}>선정 이유: {result.data.item.reason}</p>
            <BriefingItemDetails
              key={`${roundId}:${eventId}`}
              roundId={roundId}
              graphVersion={result.data.publication.graphVersion}
              item={result.data.item}
            />
            <Link
              className={ui.button}
              to={`/briefing?date=${result.data.basis.date}&edition=${result.data.basis.edition}`}
            >
              원래 브리핑 보기
            </Link>
          </section>
        )}
      </div>
    </aside>
  );
}
