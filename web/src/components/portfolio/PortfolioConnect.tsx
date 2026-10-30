import { useCallback, useRef, useState } from 'react';
import ErrorNotice from '@/components/common/ErrorNotice';
import OnboardingStep from '@/components/onboarding/OnboardingStep';
import {
  connectPortfolio,
  createIdempotencyKey,
  getMockPortfolios,
  getMockPortfolioPreview,
  getPortfolio,
} from '@/apis/portfolio/portfolio';
import { useAsyncData } from '@/hooks/useAsyncData';
import {
  formatKst,
  formatMoney,
  formatQuantity,
  formatWeight,
} from '@/util/format';
import type {
  PortfolioConnection,
  PortfolioConnectProps,
} from '@/types/portfolio';

const MOCK_NOTICE = '실제 증권 계좌가 아닌 준비된 모의 데이터로 만든 가상 계좌';

const primaryButton =
  'w-full rounded-xl bg-gray-950 px-4 py-3 font-semibold text-white hover:bg-gray-800 disabled:cursor-not-allowed disabled:bg-gray-300';
const secondaryButton =
  'w-full rounded-xl border border-gray-200 bg-white px-4 py-3 font-semibold text-gray-950 hover:bg-gray-50 disabled:cursor-not-allowed disabled:text-gray-300';

const iconProps = {
  'aria-hidden': true,
  viewBox: '0 0 24 24',
  fill: 'none',
  stroke: 'currentColor',
  strokeWidth: 1.8,
  strokeLinecap: 'round',
  strokeLinejoin: 'round',
} as const;

function BankIcon({ className }: { className: string }) {
  return (
    <svg {...iconProps} className={className}>
      <path d="M3 10h18M12 3 3 8v2h18V8l-9-5ZM5 10v8M9.5 10v8M14.5 10v8M19 10v8M3 21h18" />
    </svg>
  );
}

function CheckIcon() {
  return (
    <svg aria-hidden="true" viewBox="0 0 24 24" className="size-6 shrink-0">
      <circle cx="12" cy="12" r="11" className="fill-gray-950" />
      <path
        d="m7.5 12.5 3 3 6-6.5"
        fill="none"
        stroke="white"
        strokeWidth="2"
        strokeLinecap="round"
        strokeLinejoin="round"
      />
    </svg>
  );
}

function MockNotice() {
  return (
    <p className="flex items-center gap-2 rounded-lg border border-gray-200 bg-white px-4 py-3 text-sm text-gray-700">
      {MOCK_NOTICE}
    </p>
  );
}

// D-ONB-02 가상 계좌 연결(초기 설정) · 내 종목의 계좌 연결이 함께 쓰는 연결 기능
// - 지금 연결 상태와 연결할 계좌 목록을 모두 확인한 뒤에만 연결한다(조회 실패를 미연결로 보지 않는다).
// - 연결에 실패하면 고른 계좌를 그대로 두고 다시 시도한다.
// - 초기 설정: 연결하면 보유 종목을 보여 주고 [관심 종목 고르기]로만 넘어간다. 건너뛰어도 관심 종목으로 간다.
// - 내 종목: 연결하면 onConnected로 돌아가고, [취소]는 연결하지 않고 돌아간다.
export default function PortfolioConnect({
  source,
  onBack,
  onConnected,
  onContinue,
}: PortfolioConnectProps) {
  const options = useAsyncData(getMockPortfolios);
  const portfolio = useAsyncData(getPortfolio);
  const [chosenId, setChosenId] = useState<string | null>(null);
  const [connecting, setConnecting] = useState(false);
  const [connectFailed, setConnectFailed] = useState(false);
  const [connected, setConnected] = useState<PortfolioConnection | null>(null);
  // 같은 계좌로 다시 시도하면 같은 Idempotency-Key를 보낸다(응답 유실 시 중복 연결 방지).
  const attempt = useRef<{ accountId: string; key: string } | null>(null);
  const fromOnboarding = source === 'onboarding';

  const items = options.data?.items ?? [];
  // 목록을 다시 받았을 때 고른 계좌가 없으면 첫 계좌로 돌아간다.
  const selectedId =
    (chosenId && items.some((item) => item.id === chosenId)
      ? chosenId
      : items[0]?.id) ?? null;
  const loadPreview = useCallback(
    () =>
      selectedId ? getMockPortfolioPreview(selectedId) : Promise.resolve(null),
    [selectedId],
  );
  const preview = useAsyncData(loadPreview);
  const lookupsReady =
    options.status === 'success' && portfolio.status === 'success';
  const isConnected = Boolean(connected) || Boolean(portfolio.data?.connected);

  const connect = async () => {
    if (!lookupsReady || !selectedId || connecting) return;
    setConnecting(true);
    setConnectFailed(false);
    if (attempt.current?.accountId !== selectedId) {
      attempt.current = { accountId: selectedId, key: createIdempotencyKey() };
    }
    try {
      const connection = await connectPortfolio(
        selectedId,
        attempt.current.key,
      );
      attempt.current = null;
      setConnected(connection);
      onConnected?.(connection);
      // 초기 설정은 이 화면에서 연결한 계좌의 보유 종목을 보여 준다.
      if (fromOnboarding) portfolio.reload();
    } catch {
      setConnectFailed(true);
      // 이미 연결됐거나(다른 탭·응답 유실) 상태가 바뀌었을 수 있어 연결 상태를 다시 확인한다.
      // 연결된 것으로 확인되면 연결 완료 화면으로 넘어간다.
      portfolio.reload();
    } finally {
      setConnecting(false);
    }
  };

  if (isConnected) {
    const holdings = portfolio.data?.connected ? portfolio.data.holdings : [];
    const label =
      (portfolio.data?.connected && portfolio.data.connection?.label) ||
      connected?.label ||
      '가상 계좌';
    return (
      <OnboardingStep
        title="가상 계좌를 연결했어요"
        footer={
          fromOnboarding ? (
            <button
              type="button"
              className={primaryButton}
              onClick={onContinue}
            >
              관심 종목 고르기
            </button>
          ) : (
            <button type="button" className={primaryButton} onClick={onBack}>
              내 종목으로 돌아가기
            </button>
          )
        }
      >
        <MockNotice />
        <section
          aria-labelledby="portfolio-connected-holdings"
          className="rounded-xl border border-gray-200 bg-white p-5"
        >
          <h2
            id="portfolio-connected-holdings"
            className="mb-3 text-lg font-semibold"
          >
            {label} 보유 종목
          </h2>
          {portfolio.status === 'loading' && (
            <p role="status" className="text-sm text-gray-500">
              보유 종목을 불러오고 있어요
            </p>
          )}
          {portfolio.status === 'error' && (
            <ErrorNotice
              title="보유 종목을 불러오지 못했어요"
              message="계좌는 연결됐어요. 다시 시도하거나 다음 단계로 넘어가도 돼요."
              onRetry={portfolio.reload}
            />
          )}
          {portfolio.status === 'success' && holdings.length === 0 && (
            <p className="text-sm text-gray-500">
              이 계좌에는 보유 종목이 없어요.
            </p>
          )}
          {holdings.length > 0 && (
            <ul className="divide-y divide-gray-100">
              {holdings.map((holding) => (
                <li key={holding.companyId} className="py-3">
                  <p className="font-medium text-gray-950">{holding.name}</p>
                  <p className="text-sm text-gray-500 tabular-nums">
                    {[
                      holding.ticker,
                      formatQuantity(holding.quantity),
                      formatWeight(holding.weight),
                    ]
                      .filter(Boolean)
                      .join(' · ')}
                  </p>
                </li>
              ))}
            </ul>
          )}
        </section>
      </OnboardingStep>
    );
  }

  return (
    <OnboardingStep
      title="가상 계좌를 연결해요"
      subtitle={
        fromOnboarding
          ? undefined
          : '연결한 계좌의 모의 보유 종목이 내 종목에 보여요. 연결하거나 취소하면 내 종목으로 돌아가요.'
      }
      onBack={fromOnboarding ? onBack : undefined}
      backDisabled={connecting}
      footer={
        <>
          {connectFailed && (
            <ErrorNotice
              title="계좌를 연결하지 못했어요"
              message="고른 계좌는 그대로예요. 다시 시도해 주세요."
            />
          )}
          <button
            type="button"
            className={primaryButton}
            disabled={!lookupsReady || !selectedId || connecting}
            onClick={() => void connect()}
          >
            {connecting
              ? '연결하고 있어요'
              : connectFailed
                ? '다시 연결하기'
                : '선택한 가상 계좌 연결하기'}
          </button>
          <button
            type="button"
            className={secondaryButton}
            disabled={connecting}
            onClick={fromOnboarding ? onContinue : onBack}
          >
            {fromOnboarding ? '건너뛰고 관심 종목 고르기' : '취소'}
          </button>
        </>
      }
    >
      {/* <MockNotice /> */}
      <section
        aria-labelledby="portfolio-connect-options"
        className="flex flex-col gap-3"
      >
        <h2
          id="portfolio-connect-options"
          className="flex items-center gap-2 font-semibold text-gray-950"
        >
          {/* <BankIcon className="size-5 shrink-0" /> */}
          가상 계좌 선택
        </h2>
        {(options.status === 'loading' || portfolio.status === 'loading') && (
          <p role="status" className="text-sm text-gray-500">
            가상 계좌를 불러오고 있어요
          </p>
        )}
        {portfolio.status === 'error' && (
          <ErrorNotice
            title="지금 계좌 연결 상태를 확인하지 못했어요"
            message="연결 상태를 확인한 뒤에 연결할 수 있어요."
            onRetry={portfolio.reload}
          />
        )}
        {options.status === 'error' && (
          <ErrorNotice
            title="가상 계좌를 불러오지 못했어요"
            onRetry={options.reload}
          />
        )}
        {options.status === 'success' && items.length === 0 && (
          <p className="text-sm text-gray-500">
            지금은 연결할 수 있는 가상 계좌가 없어요.
          </p>
        )}
        {items.length > 0 && (
          <ul aria-label="가상 계좌 목록" className="flex flex-col gap-2">
            {items.map((item) => (
              <li key={item.id}>
                <button
                  type="button"
                  aria-pressed={selectedId === item.id}
                  disabled={connecting}
                  onClick={() => setChosenId(item.id)}
                  className={`flex w-full items-center gap-4 rounded-xl border px-4 py-4 text-left disabled:cursor-not-allowed ${
                    selectedId === item.id
                      ? 'border-gray-400 bg-gray-100'
                      : 'border-gray-200 bg-white hover:bg-gray-50'
                  }`}
                >
                  <BankIcon className="size-6 shrink-0 text-gray-700" />
                  <span className="flex min-w-0 flex-1 flex-col gap-0.5">
                    <span className="font-semibold text-gray-950">
                      {item.label}
                    </span>
                    <span className="text-sm text-gray-500 tabular-nums">
                      보유 종목 {item.holdingsCount}개
                    </span>
                  </span>
                  {selectedId === item.id && <CheckIcon />}
                </button>
              </li>
            ))}
          </ul>
        )}
      </section>
      {fromOnboarding && selectedId && (
        <section
          aria-labelledby="portfolio-preview-heading"
          className="rounded-xl border border-gray-200 bg-white p-5"
        >
          <div className="mb-3 flex items-start justify-between gap-3">
            <div>
              <h2
                id="portfolio-preview-heading"
                className="font-semibold text-gray-950"
              >
                {items.find((item) => item.id === selectedId)?.label}
              </h2>
            </div>
          </div>
          {preview.status === 'loading' && (
            <p role="status" className="text-sm text-gray-500">
              종목과 비중을 불러오고 있어요
            </p>
          )}
          {preview.status === 'error' && (
            <ErrorNotice
              title="계좌 미리보기를 불러오지 못했어요"
              message="계좌 연결은 하지 않았어요. 다시 시도해 주세요."
              onRetry={preview.reload}
            />
          )}
          {preview.status === 'success' && preview.data && (
            <>
              <dl className="mb-3 grid grid-cols-2 gap-2 rounded-lg bg-gray-50 p-3 text-sm">
                <div>
                  <dt className="text-xs text-gray-500">계좌 종류</dt>
                  <dd className="mt-1 font-medium text-gray-900">
                    모의 주식 계좌
                  </dd>
                </div>
                <div>
                  <dt className="text-xs text-gray-500">예수금</dt>
                  <dd className="mt-1 font-medium text-gray-900">
                    {preview.data.cash
                      ? formatMoney(
                          preview.data.cash.amount,
                          preview.data.cash.currency,
                        )
                      : '미제공'}
                  </dd>
                </div>
                <div className="col-span-2">
                  <dt className="text-xs text-gray-500">평가 기준</dt>
                  <dd className="mt-1 text-gray-700">
                    {preview.data.valuation.currency
                      ? `${preview.data.valuation.currency} · `
                      : ''}
                    {formatKst(preview.data.valuation.calculatedAt)}
                  </dd>
                </div>
              </dl>
              {preview.data.holdings.length === 0 ? (
                <p className="text-sm text-gray-500">보유 종목이 없어요.</p>
              ) : (
                <ul
                  aria-label="미리보기 보유 종목"
                  className="divide-y divide-gray-100"
                >
                  {preview.data.holdings.map((holding) => (
                    <li
                      key={holding.companyId}
                      className="flex items-center justify-between gap-3 py-3"
                    >
                      <div className="min-w-0">
                        <p className="truncate font-medium text-gray-950">
                          {holding.name}
                        </p>
                        <p className="text-xs text-gray-500">
                          {[holding.ticker, formatQuantity(holding.quantity)]
                            .filter(Boolean)
                            .join(' · ')}
                        </p>
                      </div>
                      <div className="shrink-0 text-right text-sm">
                        <p className="font-medium text-gray-900">
                          {holding.marketValue !== null &&
                          holding.quote.status === 'available'
                            ? formatMoney(
                                holding.marketValue,
                                holding.quote.currency,
                              )
                            : '평가 금액 미제공'}
                        </p>
                        <p className="text-xs text-gray-500">
                          {formatWeight(holding.weight)}
                        </p>
                      </div>
                    </li>
                  ))}
                </ul>
              )}
              {preview.data.valuation.weightUnavailableReason && (
                <p className="mt-2 text-xs text-gray-500">
                  비중을 계산할 수 없어요:{' '}
                  {preview.data.valuation.weightUnavailableReason}
                </p>
              )}
            </>
          )}
        </section>
      )}
    </OnboardingStep>
  );
}
