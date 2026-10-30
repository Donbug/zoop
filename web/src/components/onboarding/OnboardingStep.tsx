import type { OnboardingStepProps } from '@/types/onboarding';

/** 초기 설정 단계 공통 틀: [이전 단계], 제목·부제, 본문, 하단 행동 영역 */
export default function OnboardingStep({
  title,
  subtitle,
  onBack,
  backDisabled,
  children,
  footer,
}: OnboardingStepProps) {
  return (
    <section className="mt-6 flex flex-col gap-6">
      <div className="flex flex-col gap-2">
        {onBack && (
          <button
            type="button"
            onClick={onBack}
            disabled={backDisabled}
            className="self-start text-sm font-medium text-zoop-ink hover:text-zoop-ink disabled:cursor-not-allowed disabled:text-gray-300"
          >
            ← 이전 단계
          </button>
        )}
        <h1 className="text-2xl font-bold text-zoop-ink">{title}</h1>
        {subtitle && <p className="text-sm text-zoop-ink">{subtitle}</p>}
      </div>
      {children}
      {footer && (
        <div className="sticky bottom-0 flex flex-col gap-2 border-t border-gray-200 bg-[#f5f5f5] py-3">
          {footer}
        </div>
      )}
    </section>
  );
}
