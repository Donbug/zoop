import type { ChatPhase } from '@/types/ai';

// D-AI-02 진행 단계. 표시는 서버의 `phase`만 따르고 경과 시간으로 추정하지 않는다.
export const PHASES: { phase: ChatPhase; label: string }[] = [
  { phase: 'planning', label: '질문 이해' },
  { phase: 'retrieving', label: '자료 확인' },
  { phase: 'writing', label: '답변 작성' },
  { phase: 'verifying', label: '검증' },
];

export const PHASE_LABEL = Object.fromEntries(
  PHASES.map((step) => [step.phase, step.label]),
) as Record<ChatPhase, string>;
