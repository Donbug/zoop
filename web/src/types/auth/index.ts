export type Member = {
  id: string;
  displayName: string;
};

export type AuthState = {
  accessToken: string | null;
  member: Member | null;
  onboardingCompleted: boolean | null;
  setAccessToken: (token: string) => void;
  setMember: (member: Member, onboardingCompleted: boolean) => void;
  clearSession: () => void;
};

export type LoginLocationState = {
  from?: {
    pathname?: string;
    search?: string;
    hash?: string;
  };
};
