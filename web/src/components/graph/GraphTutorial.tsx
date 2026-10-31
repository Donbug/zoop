import type { GraphTutorialStep } from '@/types/map';

const steps = [
  {
    id: 'D-GRP-T',
    title: '지도 움직이기',
    body: '빈 공간을 드래그해 지도를 움직이고, 휠이나 확대·축소 버튼으로 관계를 살펴보세요.',
    tip: '키보드에서는 Tab으로 노드에 이동할 수 있어요.',
  },
  {
    id: 'D-GRP-T2',
    title: '기업이나 사건 고르기',
    body: '기업 원이나 사건 마름모를 선택하면 지도는 유지된 채 오른쪽 상세 패널이 열려요.',
    tip: '선택을 닫아도 보고 있던 지도 위치는 그대로예요.',
  },
  {
    id: 'D-GRP-T3',
    title: '영향 경로 보기',
    body: '기업 상세의 관련 사건을 선택하면 승인된 연결을 따라 기업과 사건 사이 경로를 보여드려요.',
    tip: '점선인 사건 공유 연결은 영향 경로 계산에 사용하지 않아요.',
  },
  {
    id: 'D-GRP-T4',
    title: '상세와 근거 확인하기',
    body: '상세 패널의 근거 버튼에서 관계를 뒷받침하는 기사·공시와 확보된 원문 구간을 확인하세요.',
    tip: '문서 발행 시각과 관계 확인 시각은 서로 다를 수 있어요.',
  },
  {
    id: 'D-GRP-T5',
    title: 'AI에게 질문',
    body: '강조된 ‘AI에게 질문’ 버튼을 누르면 선택한 기업·사건·관계를 질문에 연결할 수 있어요. 튜토리얼을 마친 뒤 현재 맥락을 바탕으로 답을 받아보세요.',
    tip: 'AI 답변은 투자 권유가 아니며, 근거 문서를 함께 확인해 주세요.',
  },
] as const;

type Props = {
  step: GraphTutorialStep;
  practice?: boolean;
  compact?: boolean;
  instruction?: string;
  saving?: boolean;
  error?: string | null;
  onStepChange: (step: GraphTutorialStep) => void;
  onFinish: () => void;
  onSkip: () => void;
  onRetry?: () => void;
  onReload?: () => void;
};

// WBS 6.3.10 · D-GRP-T/T2/T3/T4/T5 · Figma 619:3337~5682
export default function GraphTutorial({
  step,
  practice = false,
  compact = false,
  instruction,
  saving = false,
  error,
  onStepChange,
  onFinish,
  onSkip,
  onRetry,
  onReload,
}: Props) {
  const current = steps[step - 1];
  return (
    <aside
      data-screen-id={current.id}
      aria-label="관계 그래프 튜토리얼"
      aria-live="polite"
      className={`order-first flex ${compact ? 'w-full' : 'w-[260px]'} shrink-0 flex-col self-start rounded-[6px] border border-panel-line bg-white p-4 font-panel text-panel-ink shadow-[0_0_0_0.5px_rgb(26_26_26/0.08)] max-sm:w-full`}
    >
      <div>
        <p className="flex items-center gap-2 text-body leading-5 text-panel-muted">
          <img
            src="/graph-assets/tutorial-help.svg"
            width="13"
            height="13"
            alt=""
          />
          튜토리얼 {step}/5
        </p>
        <h2 className="mt-2 text-title leading-[30px] font-bold">
          {current.title}
        </h2>
      </div>
      <div className="mt-4 flex flex-col gap-3">
        <p className="text-body leading-[23px] text-panel-secondary">
          {instruction ?? current.body}
        </p>
        <p className="text-body leading-[21px] text-panel-muted">
          {practice
            ? step === 5
              ? 'AI 답변은 투자 권유가 아니며 근거를 함께 확인해 주세요.'
              : '' // : '강조된 동작을 완료하면 자동으로 다음 단계로 넘어가요. 언제든 건너뛸 수 있어요.'
            : current.tip}
        </p>
        <div className="mt-1" aria-label={`전체 5단계 중 ${step}단계`}>
          <div className="mb-3 grid grid-cols-5 gap-1" aria-hidden="true">
            {steps.map((item, index) => (
              <span
                key={item.id}
                className={`h-1 rounded-full ${index < step ? 'bg-panel-ink' : 'bg-panel-line'}`}
              />
            ))}
          </div>
          {error && (
            <div
              className="mb-3 rounded-panel border border-panel-line bg-panel-soft p-3 text-caption leading-[16.5px] text-panel-secondary"
              role="alert"
            >
              <p>{error}</p>
              {onRetry && (
                <button
                  className="mt-2 underline"
                  data-tutorial-action="retry"
                  onClick={onRetry}
                >
                  다시 시도
                </button>
              )}
            </div>
          )}
          <div className="flex flex-wrap items-center gap-2">
            {onReload && (
              <button
                data-tutorial-action="retry"
                onClick={onReload}
                className="h-9 px-2 text-caption underline"
              >
                지도 다시 불러오기
              </button>
            )}
            {step > 1 && !practice ? (
              <button
                className="h-9 rounded-panel border border-panel-line px-3 text-body font-semibold hover:bg-panel-soft"
                onClick={() => onStepChange((step - 1) as GraphTutorialStep)}
                disabled={saving}
              >
                이전
              </button>
            ) : null}
            {(!practice || step === 5) && (
              <button
                className="h-9 rounded-panel bg-panel-ink px-3 text-body font-semibold text-white disabled:bg-panel-muted"
                onClick={() =>
                  step === 5
                    ? onFinish()
                    : onStepChange((step + 1) as GraphTutorialStep)
                }
                disabled={saving}
              >
                {saving ? '저장 중…' : step === 5 ? '마치기' : '다음'}
              </button>
            )}
            {step < 5 && (
              <button
                className="ml-auto h-9 rounded-panel border border-panel-line px-2 text-caption font-semibold text-panel-secondary hover:bg-panel-soft"
                data-tutorial-action="skip"
                onClick={onSkip}
                disabled={saving}
              >
                튜토리얼 건너뛰기
              </button>
            )}
          </div>
        </div>
      </div>
    </aside>
  );
}
