export type GraphTarget =
  | { kind: 'company'; id: string }
  | { kind: 'issue'; id: string }
  | { kind: 'edge'; id: string }
  | { kind: 'path'; id: string };

export type MapMode = 'all' | 'personal';

export type PersonalScope = 'all' | 'holdings' | 'watchlist';

export type GraphTutorialStep = 1 | 2 | 3 | 4 | 5;

export type GraphUiState = {
  evidenceTarget: GraphTarget | null;
  tutorialStep: GraphTutorialStep | null;
  openEvidence: (target: GraphTarget) => void;
  closeEvidence: () => void;
  setTutorialStep: (step: GraphTutorialStep | null) => void;
  reset: () => void;
};
