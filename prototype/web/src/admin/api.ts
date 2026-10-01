// 관리자 BFF 호출과 조회 훅(계약: AdminBackend의 admin-api.md). 사용자 앱의 queries.ts와 분리해
// 관리자 코드가 사용자 번들에 섞이지 않게 한다. 응답 타입은 BFF /openapi.json에서 생성한 schema.d.ts만 쓴다.
//
// 주기 갱신: 대시보드·작업은 5–10초마다 다시 받는다. TanStack Query는 탭이 보이지 않으면
// refetchInterval을 멈추므로(refetchIntervalInBackground 기본 false) 비활성 탭에서는 요청하지 않는다.
import { keepPreviousData, useInfiniteQuery, useMutation, useQuery, useQueryClient, type QueryClient } from "@tanstack/react-query";
import { api, ApiError, type RequestOptions, type Schemas } from "@/api/client";

type UnauthorizedHandler = (code: string) => void;
let onUnauthorized: UnauthorizedHandler | null = null;

/** 관리자 레이아웃이 등록한다. 세션 조회 외의 관리자 요청이 401이면 호출된다. */
export function setUnauthorizedHandler(handler: UnauthorizedHandler | null) {
  onUnauthorized = handler;
}

async function adminApi<T>(path: string, options?: RequestOptions): Promise<T> {
  try {
    return await api<T>(path, options);
  } catch (error) {
    if (error instanceof ApiError && error.status === 401) onUnauthorized?.(error.code);
    throw error;
  }
}

export type AdminSession = Schemas["AdminSession"];
export type CandidateRow = Schemas["CandidateRow"];
export type CandidateDetail = Schemas["CandidateDetail"];
export type GraphVersion = Schemas["GraphVersionOut"];
export type Job = Schemas["JobOut"];
export type Round = Schemas["RoundOut"];
export type GraphDbStatus = Schemas["GraphDbStatus"];
export type CandidateStatus = CandidateRow["status"];
export type ReviewRule = Schemas["ReviewRuleOut"];

export interface CandidateFilters {
  status: CandidateStatus | "ALL";
  /** 자동 검수 규칙이 다루는 후보만 */
  ruleOnly: boolean;
  q: string;
}

export interface AuditFilters {
  action: string;
  q: string;
}

export const adminKeys = {
  all: ["admin"] as const,
  session: ["admin", "session"] as const,
  dashboard: ["admin", "dashboard"] as const,
  overview: ["admin", "pipeline", "overview"] as const,
  rules: ["admin", "pipeline", "rules"] as const,
  candidates: (filters: CandidateFilters) => ["admin", "pipeline", "candidates", filters] as const,
  candidate: (id: string) => ["admin", "pipeline", "candidate", id] as const,
  versions: ["admin", "graph", "versions"] as const,
  jobs: ["admin", "jobs"] as const,
  job: (id: string) => ["admin", "job", id] as const,
  aiUsage: (window: string) => ["admin", "ai-usage", window] as const,
  briefings: ["admin", "briefings"] as const,
  briefing: (id: string) => ["admin", "briefing", id] as const,
  audit: (filters: AuditFilters) => ["admin", "audit", filters] as const,
};

// ---- 인증

export function useAdminSession() {
  return useQuery({
    queryKey: adminKeys.session,
    queryFn: ({ signal }) => api<AdminSession>("/api/admin/auth/session", { signal }),
    staleTime: 0,
  });
}

export function useAdminLogin() {
  const client = useQueryClient();
  return useMutation({
    mutationFn: (body: Schemas["AdminLoginRequest"]) => api<AdminSession>("/api/admin/auth/login", { method: "POST", body }),
    onSuccess: (session) => {
      client.removeQueries({ queryKey: adminKeys.all });
      client.setQueryData(adminKeys.session, session);
    },
  });
}

export function useAdminLogout() {
  const client = useQueryClient();
  return useMutation({
    mutationFn: () => api<void>("/api/admin/auth/logout", { method: "POST" }),
    onSettled: () => client.removeQueries({ queryKey: adminKeys.all }),
  });
}

// ---- 대시보드·관제

export function useDashboard() {
  return useQuery({
    queryKey: adminKeys.dashboard,
    queryFn: ({ signal }) => adminApi<Schemas["Dashboard"]>("/api/admin/dashboard", { signal }),
    refetchInterval: 10_000,
  });
}

export function usePipelineOverview() {
  return useQuery({
    queryKey: adminKeys.overview,
    queryFn: ({ signal }) => adminApi<Schemas["Overview"]>("/api/admin/pipeline/overview", { signal }),
    refetchInterval: 10_000,
  });
}

export function useCandidates(filters: CandidateFilters) {
  return useInfiniteQuery({
    queryKey: adminKeys.candidates(filters),
    queryFn: ({ signal, pageParam }) =>
      adminApi<Schemas["CandidateList"]>("/api/admin/pipeline/candidates", {
        signal,
        query: { status: filters.status === "ALL" ? undefined : filters.status, rule: filters.ruleOnly ? "true" : undefined, q: filters.q.trim(), limit: 50, cursor: pageParam },
      }),
    initialPageParam: null as string | null,
    getNextPageParam: (last) => last.nextCursor,
    placeholderData: keepPreviousData,
  });
}

export function useCandidate(id: string | null) {
  return useQuery({
    queryKey: adminKeys.candidate(id ?? ""),
    queryFn: ({ signal }) => adminApi<CandidateDetail>(`/api/admin/pipeline/candidates/${encodeURIComponent(id!)}`, { signal }),
    enabled: Boolean(id),
  });
}

/** 검수 결정은 사용자 그래프를 바꾸므로 관제·대시보드·사용자 그래프 캐시를 모두 새로 받는다. */
function refreshAfterGraphChange(client: QueryClient) {
  client.removeQueries({ queryKey: ["graph"] });
  return client.invalidateQueries({ queryKey: adminKeys.all });
}

export function useDecideCandidate() {
  const client = useQueryClient();
  return useMutation({
    mutationFn: ({ id, ...body }: { id: string } & Schemas["DecisionRequest"]) =>
      adminApi<Schemas["DecisionResponse"]>(`/api/admin/pipeline/candidates/${encodeURIComponent(id)}/decision`, { method: "POST", body }),
    onSuccess: () => refreshAfterGraphChange(client),
  });
}

export function usePipelineRules() {
  return useQuery({
    queryKey: adminKeys.rules,
    queryFn: ({ signal }) => adminApi<Schemas["RuleList"]>("/api/admin/pipeline/rules", { signal }),
    refetchInterval: 10_000,
  });
}

/** 규칙을 켜고 끄면 사용자 그래프가 바뀌므로 결정과 같이 관제·대시보드·사용자 그래프 캐시를 모두 새로 받는다. */
export function useSwitchRule() {
  const client = useQueryClient();
  return useMutation({
    mutationFn: ({ id, ...body }: { id: string } & Schemas["RuleSwitchRequest"]) =>
      adminApi<Schemas["RuleSwitchResponse"]>(`/api/admin/pipeline/rules/${encodeURIComponent(id)}`, { method: "PUT", body }),
    onSuccess: () => refreshAfterGraphChange(client),
  });
}

export function useGraphVersions() {
  return useQuery({
    queryKey: adminKeys.versions,
    queryFn: ({ signal }) => adminApi<Schemas["GraphVersionList"]>("/api/admin/graph/versions", { signal }),
  });
}

export function usePublishVersion() {
  const client = useQueryClient();
  return useMutation({
    mutationFn: (reason: string) => adminApi<Schemas["PublishResponse"]>("/api/admin/graph/versions", { method: "POST", body: { reason } }),
    onSuccess: () => refreshAfterGraphChange(client),
  });
}

export function useActivateVersion() {
  const client = useQueryClient();
  return useMutation({
    mutationFn: ({ id, reason }: { id: string; reason: string }) =>
      adminApi<Schemas["ActivateResponse"]>(`/api/admin/graph/versions/${encodeURIComponent(id)}/activate`, { method: "POST", body: { reason } }),
    onSuccess: () => refreshAfterGraphChange(client),
  });
}

// ---- 작업 러너

export function useJobs() {
  return useQuery({
    queryKey: adminKeys.jobs,
    queryFn: ({ signal }) => adminApi<Schemas["JobList"]>("/api/admin/jobs", { signal, query: { limit: 30 } }),
    // 실행 중 작업이 있으면 5초, 없으면 10초
    refetchInterval: (query) => (query.state.data?.active ? 5_000 : 10_000),
  });
}

export function useJob(id: string | null) {
  return useQuery({
    queryKey: adminKeys.job(id ?? ""),
    queryFn: ({ signal }) => adminApi<Job>(`/api/admin/jobs/${encodeURIComponent(id!)}`, { signal }),
    enabled: Boolean(id),
    refetchInterval: (query) => {
      const status = query.state.data?.status;
      return status === "queued" || status === "running" ? 5_000 : false;
    },
  });
}

export function useCreateJob() {
  const client = useQueryClient();
  return useMutation({
    mutationFn: (body: Schemas["JobCreate"]) => adminApi<Schemas["JobCreated"]>("/api/admin/jobs", { method: "POST", body }),
    onSuccess: () => client.invalidateQueries({ queryKey: adminKeys.all }),
  });
}

export function useRetryJob() {
  const client = useQueryClient();
  return useMutation({
    mutationFn: ({ id, ...body }: { id: string } & Schemas["JobRetry"]) =>
      adminApi<Schemas["JobCreated"]>(`/api/admin/jobs/${encodeURIComponent(id)}/retry`, { method: "POST", body }),
    onSuccess: () => client.invalidateQueries({ queryKey: adminKeys.all }),
  });
}

export function useCancelJob() {
  const client = useQueryClient();
  return useMutation({
    mutationFn: ({ id, reason }: { id: string; reason: string }) =>
      adminApi<Job>(`/api/admin/jobs/${encodeURIComponent(id)}/cancel`, { method: "POST", body: { reason } }),
    onSuccess: () => client.invalidateQueries({ queryKey: adminKeys.all }),
  });
}

// ---- AI 운영

export function useAiUsage(window: string) {
  return useQuery({
    queryKey: adminKeys.aiUsage(window),
    queryFn: ({ signal }) => adminApi<Schemas["AiUsageResponse"]>("/api/admin/ai-usage", { signal, query: { window } }),
    placeholderData: keepPreviousData,
    refetchInterval: 10_000,
  });
}

// ---- 브리핑 운영

export function useAdminBriefings() {
  return useQuery({
    queryKey: adminKeys.briefings,
    queryFn: ({ signal }) => adminApi<Schemas["RoundList"]>("/api/admin/briefings", { signal }),
    refetchInterval: (query) => (query.state.data?.items.some((r) => r.status === "generating" || r.status === "verifying") ? 5_000 : 10_000),
  });
}

export function useAdminBriefing(id: string | null) {
  return useQuery({
    queryKey: adminKeys.briefing(id ?? ""),
    queryFn: ({ signal }) => adminApi<Schemas["RoundDetail"]>(`/api/admin/briefings/${encodeURIComponent(id!)}`, { signal }),
    enabled: Boolean(id),
  });
}

/** 브리핑 운영 변경은 사용자 브리핑 캐시도 비운다. */
function useBriefingMutation<TBody>(path: (id: string) => string) {
  const client = useQueryClient();
  return useMutation({
    mutationFn: ({ id, body }: { id: string; body: TBody }) => adminApi<unknown>(path(id), { method: "POST", body }),
    onSuccess: () => {
      client.removeQueries({ queryKey: ["briefing"] });
      return client.invalidateQueries({ queryKey: adminKeys.all });
    },
  });
}

export const useReprocessBriefing = () => useBriefingMutation<{ reason: string }>((id) => `/api/admin/briefings/${encodeURIComponent(id)}/reprocess`);
export const useCreateCorrection = () => useBriefingMutation<Schemas["CorrectionRequest"]>((id) => `/api/admin/briefings/${encodeURIComponent(id)}/corrections`);
export const useBriefingSuspension = () => useBriefingMutation<Schemas["SuspensionRequest"]>((id) => `/api/admin/briefings/${encodeURIComponent(id)}/suspension`);

// ---- 감사 로그

export function useAuditLog(filters: AuditFilters) {
  return useInfiniteQuery({
    queryKey: adminKeys.audit(filters),
    queryFn: ({ signal, pageParam }) =>
      adminApi<Schemas["AuditPage"]>("/api/admin/audit-log", {
        signal,
        query: { action: filters.action || undefined, q: filters.q.trim(), limit: 50, cursor: pageParam },
      }),
    initialPageParam: null as string | null,
    getNextPageParam: (last) => last.nextCursor,
    placeholderData: keepPreviousData,
  });
}

// ---- 이용 통계·선호도·회원(요구 74·75·78)

export type StatsWindow = "7d" | "30d" | "all";
export type StatsMetric = Schemas["StatsMetric"];
export type MemberStatus = Schemas["MemberRow"]["status"];
export interface MemberFilters {
  status: MemberStatus | "all";
  q: string;
}

export function useInsightsOverview() {
  return useQuery({
    queryKey: ["admin", "insights", "overview"],
    queryFn: ({ signal }) => adminApi<Schemas["InsightsOverview"]>("/api/admin/insights/overview", { signal }),
    refetchInterval: 10_000,
  });
}

export function useStatsSummary(window: StatsWindow) {
  return useQuery({
    queryKey: ["admin", "insights", "summary", window],
    queryFn: ({ signal }) => adminApi<Schemas["StatsSummary"]>("/api/admin/insights/summary", { signal, query: { window } }),
    placeholderData: keepPreviousData,
    refetchInterval: 10_000,
  });
}

export function useCompanyRanking(window: StatsWindow) {
  return useQuery({
    queryKey: ["admin", "insights", "companies", window],
    queryFn: ({ signal }) => adminApi<Schemas["InsightCompanyRanking"]>("/api/admin/insights/companies", { signal, query: { window } }),
    placeholderData: keepPreviousData,
    refetchInterval: 10_000,
  });
}

export function useCompanyStats(id: string, window: StatsWindow) {
  return useQuery({
    queryKey: ["admin", "insights", "company", id, window],
    queryFn: ({ signal }) => adminApi<Schemas["InsightCompanyDetail"]>(`/api/admin/insights/companies/${encodeURIComponent(id)}`, { signal, query: { window } }),
    placeholderData: keepPreviousData,
    refetchInterval: 10_000,
  });
}

/** 선호도 조회 기간(FS066-02): 미리 정한 기간 또는 평가를 마지막으로 바꾼 KST 날짜의 시작·종료일(둘 중 하나라도 있으면 우선). */
export interface FeedbackPeriod {
  window: StatsWindow;
  start: string | null;
  end: string | null;
}

export function useFeedbackSummary({ window, start, end }: FeedbackPeriod) {
  return useQuery({
    queryKey: ["admin", "feedback", "summary", window, start, end],
    queryFn: ({ signal }) => adminApi<Schemas["FeedbackSummary"]>("/api/admin/feedback/summary", { signal, query: { window, start, end } }),
    placeholderData: keepPreviousData,
    refetchInterval: 10_000,
  });
}

export function useDislikes({ window, start, end }: FeedbackPeriod) {
  return useInfiniteQuery({
    queryKey: ["admin", "feedback", "dislikes", window, start, end],
    queryFn: ({ signal, pageParam }) =>
      adminApi<Schemas["DislikePage"]>("/api/admin/feedback/dislikes", { signal, query: { window, start, end, limit: 50, cursor: pageParam } }),
    initialPageParam: null as string | null,
    getNextPageParam: (last) => last.nextCursor,
    placeholderData: keepPreviousData,
  });
}

export function useTranscripts(only: "all" | "disliked") {
  return useInfiniteQuery({
    queryKey: ["admin", "feedback", "transcripts", only],
    queryFn: ({ signal, pageParam }) => adminApi<Schemas["TranscriptPage"]>("/api/admin/transcripts", { signal, query: { only, limit: 30, cursor: pageParam } }),
    initialPageParam: null as string | null,
    getNextPageParam: (last) => last.nextCursor,
    placeholderData: keepPreviousData,
  });
}

/** 대화록을 여는 것 자체가 감사 로그에 남으므로 자동 갱신하지 않는다. */
export function useTranscript(id: string) {
  return useQuery({
    queryKey: ["admin", "feedback", "transcript", id],
    queryFn: ({ signal }) => adminApi<Schemas["TranscriptDetail"]>(`/api/admin/transcripts/${encodeURIComponent(id)}`, { signal }),
    staleTime: Infinity,
    refetchOnMount: false,
  });
}

export function useMembers(filters: MemberFilters) {
  return useInfiniteQuery({
    queryKey: ["admin", "members", "list", filters],
    queryFn: ({ signal, pageParam }) =>
      adminApi<Schemas["MemberList"]>("/api/admin/members", {
        signal,
        query: { status: filters.status === "all" ? undefined : filters.status, q: filters.q.trim(), limit: 50, cursor: pageParam },
      }),
    initialPageParam: null as string | null,
    getNextPageParam: (last) => last.nextCursor,
    placeholderData: keepPreviousData,
  });
}

export function useMember(id: string) {
  return useQuery({
    queryKey: ["admin", "members", "detail", id],
    queryFn: ({ signal }) => adminApi<Schemas["MemberDetail"]>(`/api/admin/members/${encodeURIComponent(id)}`, { signal }),
  });
}

/** 차단·해제 뒤에는 회원 목록·상세·대시보드 요약과 감사 로그를 다시 받는다. */
export function useSetMemberStatus() {
  const client = useQueryClient();
  return useMutation({
    mutationFn: ({ id, action, reason }: { id: string; action: "block" | "unblock"; reason: string }) =>
      adminApi<Schemas["MemberStatusResult"]>(`/api/admin/members/${encodeURIComponent(id)}/${action}`, { method: "POST", body: { reason } }),
    onSuccess: () => client.invalidateQueries({ queryKey: adminKeys.all }),
  });
}
