// GET/PUT /api/v1/me/settings (docs/api/openapi.yaml SettingsResponse·SettingsUpdate)

/** 개인 지도의 시작 기준. 보유 종목(assets) 또는 관심 종목(watchlist) */
export type PersonalMapBasis = 'assets' | 'watchlist';

export type MemberSettings = {
  mode: PersonalMapBasis;
  watchlistIds: string[];
  tutorialCompleted: boolean;
  completed: boolean;
  /** 투자 여부. 온보딩 질문에 답하기 전에는 null */
  investor: boolean | null;
  /** 낙관적 동시성 제어용. 저장할 때 그대로 돌려보낸다. */
  version: number;
};

/** 보내지 않은 항목은 저장된 값을 유지한다. */
export type SettingsUpdate = {
  version: number;
  mode?: PersonalMapBasis | null;
  watchlistIds?: string[] | null;
  tutorialCompleted?: boolean | null;
  completed?: boolean | null;
  investor?: boolean | null;
};

export type SettingsPatch = Omit<SettingsUpdate, 'version'>;
