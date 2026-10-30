import { useNavigate } from 'react-router-dom';
import ErrorNotice from '@/components/common/ErrorNotice';
import OnboardingStep from '@/components/onboarding/OnboardingStep';
import { useMemberSettings } from '@/hooks/useMemberSettings';
import { useOnboardingStore } from '@/stores/useOnboardingStore';
import type { InvestmentStatus } from '@/types/onboarding';

// 와이어프레임 D-ONB-01의 선택지 아이콘(가방·새싹). 장식이라 읽지 않는다.
function BriefcaseIcon() {
  return (
    <svg
      aria-hidden="true"
      viewBox="0 0 24 24"
      className="size-5"
      fill="none"
      stroke="currentColor"
      strokeWidth="1.8"
      strokeLinecap="round"
      strokeLinejoin="round"
    >
      <rect x="3" y="7" width="18" height="13" rx="2" />
      <path d="M8 7V5a2 2 0 0 1 2-2h4a2 2 0 0 1 2 2v2M8 7v13M16 7v13" />
    </svg>
  );
}

function SproutIcon() {
  return (
    <svg
      aria-hidden="true"
      viewBox="0 0 24 24"
      className="size-5"
      fill="none"
      stroke="currentColor"
      strokeWidth="1.8"
      strokeLinecap="round"
      strokeLinejoin="round"
    >
      <path d="M12 21v-9M12 12C12 8 9 5 4 5c0 4 3 7 8 7ZM12 14c0-4 3-7 8-7 0 4-3 7-8 7Z" />
      <path d="M8 21h8" />
    </svg>
  );
}

const OPTIONS: {
  value: Exclude<InvestmentStatus, null>;
  title: string;
  description: string;
  Icon: () => React.JSX.Element;
}[] = [
  {
    value: 'investing',
    title: '지금 주식에 투자하고 있어요',
    description: '가상 계좌를 연결해 보유 종목 주변을 봐요',
    Icon: BriefcaseIcon,
  },
  {
    value: 'not-investing',
    title: '아직 투자하지 않아요',
    description: '관심 있는 종목을 골라 시작해요',
    Icon: SproutIcon,
  },
];

function fromInvestor(investor: boolean | null | undefined): InvestmentStatus {
  if (investor === true) return 'investing';
  if (investor === false) return 'not-investing';
  return null;
}

// D-ONB-01 투자 여부 선택
// 고르면 바로 investor를 저장하고, 투자 중 → 가상 계좌 연결, 아니면 → 관심 종목 선택으로 간다.
// 저장에 실패하면 이동하지 않고 고른 값을 그대로 둔 채 다시 시도한다.
export default function InvestmentChoice() {
  const navigate = useNavigate();
  const { settings, save, saving, saveFailed } = useMemberSettings();
  const draft = useOnboardingStore((state) => state.investmentStatus);
  const setInvestmentStatus = useOnboardingStore(
    (state) => state.setInvestmentStatus,
  );
  // 이번에 고른 값이 없으면 저장된 답을 보여 준다(새로 고침 후 이어 하기).
  const chosen = draft ?? fromInvestor(settings.data?.investor);

  const choose = async (value: Exclude<InvestmentStatus, null>) => {
    if (saving) return;
    if (value !== draft) setInvestmentStatus(value);
    const saved = await save({ investor: value === 'investing' });
    if (!saved) return;
    navigate(
      value === 'investing' ? '/onboarding/account' : '/onboarding/watchlist',
    );
  };

  return (
    <OnboardingStep title="지금 주식에 투자하고 계신가요?">
      {settings.status === 'loading' && (
        <p role="status" className="text-sm text-zoop-ink">
          설정을 불러오고 있어요
        </p>
      )}
      {settings.status === 'error' && (
        <ErrorNotice
          title="설정을 불러오지 못했어요"
          message="설정을 확인한 뒤에 고를 수 있어요."
          onRetry={settings.reload}
        />
      )}
      {settings.status === 'success' && (
        <ul aria-label="투자 여부" className="flex flex-col gap-3">
          {OPTIONS.map((option) => (
            <li key={option.value}>
              <button
                type="button"
                aria-pressed={chosen === option.value}
                disabled={saving}
                onClick={() => void choose(option.value)}
                className={`flex w-full items-center gap-4 rounded-xl border px-4 py-4 text-left disabled:cursor-progress ${
                  chosen === option.value
                    ? 'border-gray-950 bg-gray-50'
                    : 'border-gray-200 bg-white hover:bg-gray-50'
                }`}
              >
                <span className="flex size-10 shrink-0 items-center justify-center rounded-lg bg-gray-100 text-zoop-ink">
                  <option.Icon />
                </span>
                <span className="flex min-w-0 flex-col gap-1">
                  <span className="font-semibold text-zoop-ink">
                    {option.title}
                  </span>
                  <span className="text-sm text-zoop-ink">
                    {option.description}
                  </span>
                </span>
              </button>
            </li>
          ))}
        </ul>
      )}
      {saving && (
        <p role="status" className="text-sm text-zoop-ink">
          선택을 저장하고 있어요
        </p>
      )}
      {saveFailed && !saving && chosen && (
        <ErrorNotice
          title="선택을 저장하지 못했어요"
          message="고른 답은 그대로예요. 다시 시도해 주세요."
          onRetry={() => void choose(chosen)}
        />
      )}
    </OnboardingStep>
  );
}
