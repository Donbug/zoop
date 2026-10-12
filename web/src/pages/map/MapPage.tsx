import { Navigate, useLocation } from 'react-router-dom';
import PageShell from '@/components/common/PageShell';
import GraphCanvas from '@/components/graph/GraphCanvas';
import EventDetailPanel from '@/components/graph/EventDetailPanel';
import CompanyDetailPanel from '@/components/graph/CompanyDetailPanel';
import RelationDetailPanel from '@/components/graph/RelationDetailPanel';
import ImpactPathPanel from '@/components/graph/ImpactPathPanel';
import CompanyPathPanel from '@/components/graph/CompanyPathPanel';
import GraphFocusControls from '@/components/graph/GraphFocusControls';
import GraphTutorial from '@/components/graph/GraphTutorial';
import BriefingSnapshotBanner from '@/components/graph/BriefingSnapshotBanner';
import EvidenceDrawer from '@/components/evidence/EvidenceDrawer';
import AiChatDrawer from '@/components/ai/AiChatDrawer';
import { useGraphQuery } from '@/hooks/useGraphQuery';
import { useAuth } from '@/hooks/useAuth';
import { useAiChatStore } from '@/stores/useAiChatStore';

// 시장/개인/회차/확대는 동일 페이지의 상태다. URL에 탐색 맥락을 보존한다.
export default function MapPage() {
  const { params, updateQuery, mode, roundId, focusId, target } =
    useGraphQuery();
  const { isAuthenticated } = useAuth();
  const location = useLocation();
  const openAi = useAiChatStore((state) => state.open);
  if (mode === 'personal' && !isAuthenticated) {
    return <Navigate to="/login" replace state={{ from: location }} />;
  }
  return (
    <PageShell
      title={
        roundId
          ? '회차 기준 지도'
          : mode === 'personal'
            ? '내 종목 지도'
            : '시장 전체 지도'
      }
    >
      <div className="flex gap-4">
        <button
          type="button"
          onClick={() => updateQuery({ mode: 'all', round: null })}
        >
          시장 전체
        </button>
        <button
          type="button"
          onClick={() => updateQuery({ mode: 'personal', round: null })}
        >
          내 종목
        </button>
        <button type="button" onClick={() => openAi(target)}>
          AI에게 묻기
        </button>
      </div>
      {roundId && <BriefingSnapshotBanner />}
      <GraphCanvas />
      {focusId && <GraphFocusControls />}
      {params.get('select') === 'issue' && <EventDetailPanel />}
      {params.get('select') === 'company' && <CompanyDetailPanel />}
      {params.get('select') === 'edge' && <RelationDetailPanel />}
      {params.has('impact') && <ImpactPathPanel />}
      {params.has('path') && <CompanyPathPanel />}
      {params.get('tour') === '1' && <GraphTutorial />}
      <EvidenceDrawer />
      <AiChatDrawer />
    </PageShell>
  );
}
