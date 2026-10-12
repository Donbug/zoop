import { create } from 'zustand';
import type { GraphUiState } from '@/types/map';

const initial = { evidenceTarget: null, tutorialStep: null };

// 지도 선택/필터는 URL이 소유한다. 근거 창을 닫아도 원래 URL 선택은 유지한다.
export const useGraphUiStore = create<GraphUiState>((set) => ({
  ...initial,
  openEvidence: (evidenceTarget) => set({ evidenceTarget }),
  closeEvidence: () => set({ evidenceTarget: null }),
  setTutorialStep: (tutorialStep) => set({ tutorialStep }),
  reset: () => set(initial),
}));
