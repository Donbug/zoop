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

/** 진행 중 말풍선에 쓰는 문장. 단계 이름(PHASE_LABEL)을 풀어 쓴 것이다. */
export const PHASE_PROGRESS: Record<ChatPhase, string> = {
  planning: '질문을 이해하는 중이에요.',
  retrieving: '자료를 확인하는 중이에요.',
  writing: '답변을 작성하는 중이에요.',
  verifying: '검증하는 중이에요.',
};
