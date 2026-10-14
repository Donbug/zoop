import { useNavigate } from 'react-router-dom';
import PortfolioConnect from '@/components/portfolio/PortfolioConnect';
import { useOnboardingStore } from '@/stores/useOnboardingStore';

// D-ONB-02: 연결·건너뛰기 → 관심 종목 선택(D-WAT-01), 이전 단계 → 투자 여부(D-ONB-01)
export default function VirtualAccountPage() {
  const navigate = useNavigate();
  const setVirtualAccountId = useOnboardingStore(
    (state) => state.setVirtualAccountId,
  );

  return (
    <PortfolioConnect
      source="onboarding"
      onBack={() => navigate('/onboarding')}
      onConnected={(connection) => setVirtualAccountId(connection.id)}
      onContinue={() => navigate('/onboarding/watchlist')}
    />
  );
}
