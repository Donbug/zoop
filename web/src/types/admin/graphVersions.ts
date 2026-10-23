// A-ADM-03 그래프 버전 (FS059, docs/api/openapi.yaml listGraphVersions·activateGraphVersion)

export type GraphVersionKind = 'fixture' | 'snapshot';
export type GraphDbVersionStatus = 'reflected' | 'pending' | 'unknown';

export type GraphVersion = {
  id: string;
  sequence: number;
  /** fixture는 로컬·개발용 합성 자료, snapshot은 원장에서 가져온 공개 버전 */
  kind: GraphVersionKind;
  createdAt: string;
  createdBy: string;
  reason: string | null;
  sourceLabel: string;
  policyVersion: string | null;
  issueCount: number;
  relationCount: number;
  articleCount: number;
  candidateCount: number | null;
  sha256: string;
  bytes: number;
  /** 지금 사용자에게 보이는 버전 */
  active: boolean;
  activatedAt: string | null;
  graphDb: {
    status: GraphDbVersionStatus;
    pendingJobsAtCreation: number | null;
    note: string | null;
  };
};

export type GraphVersionActivation = {
  versionId: string;
  previousVersionId: string | null;
  at: string;
  adminEmail: string | null;
  reason: string | null;
  action: 'publish' | 'activate' | 'seed';
};

export type GraphVersionList = {
  activeVersionId: string | null;
  items: GraphVersion[];
  activations: GraphVersionActivation[];
  nextCursor: string | null;
};

export type GraphVersionActivated = {
  activeVersionId: string;
  previousActiveVersionId: string | null;
  /** 이미 그 버전이 표시 중이어서 바뀐 것이 없다. */
  idempotent: boolean;
};
