export type GraphTarget = (
  | { kind: 'company'; id: string }
  | { kind: 'issue'; id: string }
  | { kind: 'edge'; id: string }
  | { kind: 'path'; id: string }
) & {
  // D-GRP-02 handoff: preserve the map URL and the actual response version.
  mapContext?: {
    url: string;
    round?: string;
    graphVersion?: string;
    asOf?: string;
  };
  evidenceIds?: string[];
  // Actual verification timestamp only; never substitute a graph snapshot asOf.
  verifiedAt?: string | null;
  label?: string;
};

export type MapMode = 'all' | 'personal';

export type PersonalScope = 'all' | 'holdings' | 'watchlist';

/** 지도 화면에서 마지막으로 저장한 관심 종목 목록. seq가 바뀌면 사이드바·기업 상세가 이 목록으로 맞춘다. */
export type WatchSync = { ids: string[]; seq: number };

export type GraphTutorialStep = 1 | 2 | 3 | 4 | 5;

export type GraphUiState = {
  evidenceTarget: GraphTarget | null;
  tutorialStep: GraphTutorialStep | null;
  openEvidence: (target: GraphTarget) => void;
  closeEvidence: () => void;
  setTutorialStep: (step: GraphTutorialStep | null) => void;
  reset: () => void;
};
