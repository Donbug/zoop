export type AdminSession = {
  id: string;
  displayName: string;
  expiresAt: number;
};

export type AdminSessionState = {
  session: AdminSession | null;
  setSession: (session: AdminSession) => void;
  clearSession: () => void;
};
