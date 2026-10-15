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
    title: 'AI에게 묻기',
    body: '선택한 기업·사건·관계를 질문에 연결하면 현재 보고 있는 맥락을 바탕으로 답을 받을 수 있어요.',
    tip: 'AI 답변은 투자 권유가 아니며, 근거 문서를 함께 확인해 주세요.',
  },
] as const;

type Props = {
  step: GraphTutorialStep;
  saving?: boolean;
  error?: string | null;
  onStepChange: (step: GraphTutorialStep) => void;
  onFinish: () => void;
  onSkip: () => void;
  onRetry?: () => void;
};

// WBS 6.3.10 · D-GRP-T/T2/T3/T4/T5 · Figma 619:3337~5682
export default function GraphTutorial({
  step,
  saving = false,
  error,
  onStepChange,
  onFinish,
  onSkip,
  onRetry,
}: Props) {
  const current = steps[step - 1];
  return (
    <aside
      data-screen-id={current.id}
      aria-label="관계 그래프 튜토리얼"
      aria-live="polite"
      className="absolute inset-y-0 left-4 z-20 flex w-[274px] flex-col border border-panel-line bg-white font-panel text-panel-ink shadow-[0_12px_32px_rgb(0_0_0/0.08)]"
    >
      <div className="border-b border-panel-line px-5 py-4">
        <p className="text-[11px] leading-[16.5px] text-panel-muted">
          튜토리얼 {step}/5
        </p>
        <h2 className="mt-1 text-[17px] leading-[25.5px] font-bold tracking-[-0.25px]">
          {current.title}
        </h2>
      </div>
      <div className="flex flex-1 flex-col px-5 py-5">
        <p className="text-[12px] leading-[19px] text-panel-secondary">
          {current.body}
        </p>
        <p className="mt-4 border-l-2 border-panel-line pl-3 text-[11px] leading-[17px] text-panel-muted">
          {current.tip}
        </p>
        <div className="mt-auto" aria-label={`전체 5단계 중 ${step}단계`}>
          <div className="mb-5 grid grid-cols-5 gap-1" aria-hidden="true">
            {steps.map((item, index) => (
              <span
                key={item.id}
                className={`h-1 rounded-full ${index < step ? 'bg-panel-ink' : 'bg-panel-line'}`}
              />
            ))}
          </div>
          {error && (
            <div
              className="mb-3 rounded-panel border border-panel-line bg-panel-soft p-3 text-[11px] leading-[16.5px] text-panel-secondary"
              role="alert"
            >
              <p>{error}</p>
              {onRetry && (
                <button className="mt-2 underline" onClick={onRetry}>
                  다시 시도
                </button>
              )}
            </div>
          )}
          <div className="grid grid-cols-2 gap-2">
            {step > 1 ? (
              <button
                className="h-9 rounded-panel border border-panel-line text-[12px] font-semibold hover:bg-panel-soft"
                onClick={() => onStepChange((step - 1) as GraphTutorialStep)}
                disabled={saving}
              >
                이전
              </button>
            ) : (
              <span />
            )}
            <button
              className="h-9 rounded-panel bg-panel-ink text-[12px] font-semibold text-white disabled:bg-panel-muted"
              onClick={() =>
                step === 5
                  ? onFinish()
                  : onStepChange((step + 1) as GraphTutorialStep)
              }
              disabled={saving}
            >
              {saving ? '저장 중…' : step === 5 ? '마치기' : '다음'}
            </button>
          </div>
          <button
            className="mt-3 w-full py-2 text-[11px] font-semibold text-panel-secondary underline-offset-2 hover:underline"
            onClick={onSkip}
            disabled={saving}
          >
            튜토리얼 건너뛰기
          </button>
        </div>
      </div>
    </aside>
  );
}
