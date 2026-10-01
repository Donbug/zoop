// 화면에서 쓰는 모든 BFF 조회/변경 훅. 화면 컴포넌트는 fetch를 직접 부르지 않고 여기의 훅만 쓴다.
//
// 느린 응답 덮어쓰기 방지(TC-16):
//  - 모든 조회는 TanStack Query가 넘겨주는 AbortSignal을 fetch에 전달한다. 사용자가 A 노드를 누른 뒤
//    곧바로 B 노드를 누르면 A 조회는 더 이상 화면에서 쓰이지 않으므로 Query가 요청을 취소(abort)한다.
//  - 결과는 노드 id가 들어간 queryKey별로 따로 저장된다. 늦게 도착한 A 응답은 A 칸에만 들어가고,
//    화면은 현재 선택된 B의 칸만 읽으므로 A 결과가 B 화면을 덮어쓸 수 없다(요청 순번 비교와 같은 효과).
import { keepPreviousData, useMutation, useQueries, useQuery, useQueryClient, type QueryClient } from "@tanstack/react-query";
import { api, type Schemas } from "./client";
import type { GraphMode } from "@/lib/labels";

export const queryKeys = {
  health: ["health"] as const,
  session: ["session"] as const,
  settings: ["settings"] as const,
  portfolio: ["portfolio"] as const,
  mockPortfolios: ["mock-portfolios"] as const,
  companies: (q: string) => ["companies", q] as const,
  company: (id: string) => ["company", id] as const,
  prices: (id: string) => ["prices", id] as const,
  graph: (mode: GraphMode, companyId?: string) => ["graph", mode, companyId ?? null] as const,
  edge: (id: string) => ["edge", id] as const,
  companyEvents: (companyId: string, from: string) => ["events", companyId, from] as const,
  companyDocuments: (companyId: string) => ["company-documents", companyId] as const,
  event: (id: string) => ["event", id] as const,
  evidence: (id: string) => ["evidence", id] as const,
  briefing: (date: string | null, edition: string | null) => ["briefing", date, edition] as const,
  briefingRounds: ["briefing", "rounds"] as const,
  terms: ["terms"] as const,
  socialProviders: ["social-providers"] as const,
  recommendations: ["recommendations"] as const,
};

export function useHealth() {
  return useQuery({
    queryKey: queryKeys.health,
    queryFn: ({ signal }) => api<Schemas["HealthResponse"]>("/api/health", { signal }),
    refetchInterval: 30_000,
  });
}

export function useSession() {
  return useQuery({
    queryKey: queryKeys.session,
    queryFn: ({ signal }) => api<Schemas["SessionResponse"]>("/api/auth/session", { signal }),
  });
}

export function useSettings(enabled = true) {
  return useQuery({
    queryKey: queryKeys.settings,
    queryFn: ({ signal }) => api<Schemas["SettingsResponse"]>("/api/me/settings", { signal }),
    enabled,
  });
}

export function usePortfolio(enabled = true) {
  return useQuery({
    queryKey: queryKeys.portfolio,
    queryFn: ({ signal }) => api<Schemas["PortfolioResponse"]>("/api/portfolio", { signal }),
    enabled,
  });
}

export function useMockPortfolios(enabled = true) {
  return useQuery({
    queryKey: queryKeys.mockPortfolios,
    queryFn: ({ signal }) => api<Schemas["MockPortfolioListResponse"]>("/api/portfolio/mock-portfolios", { signal }),
    enabled,
  });
}

export function useTerms() {
  return useQuery({
    queryKey: queryKeys.terms,
    queryFn: ({ signal }) => api<Schemas["TermsResponse"]>("/api/auth/terms", { signal }),
    staleTime: Infinity,
  });
}

export function useSocialProviders() {
  return useQuery({
    queryKey: queryKeys.socialProviders,
    queryFn: ({ signal }) => api<Schemas["SocialProvidersResponse"]>("/api/auth/social/providers", { signal }),
    staleTime: Infinity,
  });
}

/** 관심 종목 추천: 승인된 사건이 많은 기업(근거 문구 포함). 산업·테마 추천은 데이터가 없어 두지 않는다. */
export function useRecommendations(enabled = true) {
  return useQuery({
    queryKey: queryKeys.recommendations,
    queryFn: ({ signal }) => api<Schemas["RecommendationResponse"]>("/api/me/recommendations", { signal }),
    enabled,
  });
}

export function useCompanySearch(q: string) {
  return useQuery({
    queryKey: queryKeys.companies(q),
    queryFn: ({ signal }) => api<Schemas["CompanyListResponse"]>("/api/companies", { query: { q, limit: 20 }, signal }),
    placeholderData: keepPreviousData,
  });
}

export function useCompany(id: string | undefined) {
  return useQuery({
    queryKey: queryKeys.company(id ?? ""),
    queryFn: ({ signal }) => api<Schemas["CompanyDetail"]>(`/api/companies/${encodeURIComponent(id!)}`, { signal }),
    enabled: Boolean(id),
  });
}

/** 여러 기업을 한 번에 조회한다(사이드바 관심 종목 이름 표시용). */
export function useCompanies(ids: string[]) {
  return useQueries({
    queries: ids.map((id) => ({
      queryKey: queryKeys.company(id),
      queryFn: ({ signal }: { signal: AbortSignal }) =>
        api<Schemas["CompanyDetail"]>(`/api/companies/${encodeURIComponent(id)}`, { signal }),
    })),
  });
}

export function useCompanyPrices(id: string | undefined) {
  return useQuery({
    queryKey: queryKeys.prices(id ?? ""),
    queryFn: ({ signal }) =>
      api<Schemas["PriceResponse"]>(`/api/companies/${encodeURIComponent(id!)}/prices`, { query: { period: "1m" }, signal }),
    enabled: Boolean(id),
  });
}

/** 지도 전체 연결. depth·limit을 주지 않으면 BFF가 포커스에서 닿는 연결 요소 전체를(전체 모드는 전부, 개인화는 보유+관심에서 닿는 것) 기본 한도 500개까지 준다. */
export function useGraph(mode: GraphMode, enabled = true) {
  return useQuery({
    queryKey: queryKeys.graph(mode),
    queryFn: ({ signal }) => api<Schemas["GraphResponse"]>("/api/graph", { query: { mode }, signal }),
    enabled,
    // 모드를 바꾸는 동안 이전 지도를 그대로 두어 캔버스가 다시 만들어지지 않게 한다(남는 노드는 제자리에서 이어진다).
    placeholderData: keepPreviousData,
  });
}

export function useEdge(id: string | undefined) {
  return useQuery({
    queryKey: queryKeys.edge(id ?? ""),
    queryFn: ({ signal }) => api<Schemas["EdgeDetail"]>(`/api/graph/edges/${encodeURIComponent(id!)}`, { signal }),
    enabled: Boolean(id),
  });
}

/** 기업 상세 타임라인: from(KST 날짜) 이후 사건. 기간마다 따로 캐시해 늦게 온 이전 기간 응답이 지금 기간을 덮지 않는다. */
export function useCompanyEvents(companyId: string, from: string) {
  return useQuery({
    queryKey: queryKeys.companyEvents(companyId, from),
    queryFn: ({ signal }) => api<Schemas["EventListResponse"]>("/api/events", { query: { companyId, from }, signal }),
  });
}

/** 기업 상세 문서 탭: 이 기업 사건들의 근거 기사(중복 없이, 최신 발행순). */
export function useCompanyDocuments(companyId: string) {
  return useQuery({
    queryKey: queryKeys.companyDocuments(companyId),
    queryFn: ({ signal }) =>
      api<Schemas["CompanyDocumentsResponse"]>(`/api/companies/${encodeURIComponent(companyId)}/documents`, { signal }),
  });
}

/** revalidate: 화면에 들어올 때마다 다시 조회해 사건이 아직 있는지 확인한다(기업 상세 복귀). */
export function useEvent(id: string | undefined, { revalidate = false }: { revalidate?: boolean } = {}) {
  return useQuery({
    queryKey: queryKeys.event(id ?? ""),
    queryFn: ({ signal }) => api<Schemas["EventDetail"]>(`/api/events/${encodeURIComponent(id!)}`, { signal }),
    enabled: Boolean(id),
    refetchOnMount: revalidate ? "always" : true,
  });
}

/** 여러 사건을 한 번에 조회한다(지도 목록의 사건별 근거 수). useEvent와 캐시를 함께 쓴다. */
export function useEventsByIds(ids: string[]) {
  return useQueries({
    queries: ids.map((id) => ({
      queryKey: queryKeys.event(id),
      queryFn: ({ signal }: { signal: AbortSignal }) => api<Schemas["EventDetail"]>(`/api/events/${encodeURIComponent(id)}`, { signal }),
    })),
  });
}

export function useEvidenceItems(ids: string[]) {
  return useQueries({
    queries: ids.map((id) => ({
      queryKey: queryKeys.evidence(id),
      queryFn: ({ signal }: { signal: AbortSignal }) =>
        api<Schemas["EvidenceResponse"]>(`/api/evidence/${encodeURIComponent(id)}`, { signal }),
    })),
  });
}

/** 발행된 공통 브리핑 한 회차. 날짜·구분을 비우면 지금(KST) 기준 가장 최근에 시작된 회차를 받는다. */
export function useBriefing(date: string | null, edition: "morning" | "evening" | null) {
  return useQuery({
    queryKey: queryKeys.briefing(date, edition),
    queryFn: ({ signal }) => api<Schemas["BriefingResponse"]>("/api/briefings", { query: { date, edition }, signal }),
    placeholderData: keepPreviousData,
  });
}

/** 발행됐거나 제공 중단된 회차 목록(날짜 고르기용). */
export function useBriefingRounds() {
  return useQuery({
    queryKey: queryKeys.briefingRounds,
    queryFn: ({ signal }) => api<Schemas["BriefingRoundsResponse"]>("/api/briefings/rounds", { query: { limit: 30 }, signal }),
  });
}

// ---- 변경(mutation)

// 개인 데이터 캐시(보유·관심·대화·추천 등)를 비운다. 공용 데이터(health)와 헤더가 구독 중인 session만 남긴다.
export function clearPersonalCache(client: QueryClient) {
  client.removeQueries({ predicate: (q) => !["health", "session", "terms", "social-providers"].includes(String(q.queryKey[0])) });
}

export function useLogin() {
  const client = useQueryClient();
  return useMutation({
    mutationFn: (body: Schemas["LoginRequest"]) =>
      api<Schemas["SessionResponse"]>("/api/auth/login", { method: "POST", body }),
    onSuccess: (session) => {
      clearPersonalCache(client);
      client.setQueryData(queryKeys.session, session);
    },
  });
}

export function useSignup() {
  const client = useQueryClient();
  return useMutation({
    mutationFn: (body: Schemas["SignupRequest"]) =>
      api<Schemas["SessionResponse"]>("/api/auth/signup", { method: "POST", body }),
    onSuccess: (session) => {
      clearPersonalCache(client);
      client.setQueryData(queryKeys.session, session);
    },
  });
}

export function useGuestStart() {
  const client = useQueryClient();
  return useMutation({
    mutationFn: () => api<Schemas["SessionResponse"]>("/api/auth/guest", { method: "POST" }),
    onSuccess: (session) => {
      clearPersonalCache(client);
      client.setQueryData(queryKeys.session, session);
    },
  });
}

export function useLogout() {
  const client = useQueryClient();
  return useMutation({
    mutationFn: () => api<void>("/api/auth/logout", { method: "POST" }),
    onSettled: () => {
      clearPersonalCache(client);
      return client.invalidateQueries({ queryKey: queryKeys.session });
    },
  });
}

/** 튜토리얼 완료·건너뛰기 저장(회원은 계정, 비회원은 비회원 세션에만). 같은 값을 다시 보내도 바뀌지 않는다. */
export function useSetTutorial() {
  const client = useQueryClient();
  return useMutation({
    mutationFn: (completed: boolean) =>
      api<Schemas["SessionResponse"]>("/api/auth/tutorial", { method: "PUT", body: { completed } }),
    onSuccess: (session) => {
      client.setQueryData(queryKeys.session, session);
      return client.invalidateQueries({ queryKey: queryKeys.settings });
    },
  });
}

export function useUpdateSettings() {
  const client = useQueryClient();
  return useMutation({
    mutationFn: (body: Schemas["SettingsUpdate"]) =>
      api<Schemas["SettingsResponse"]>("/api/me/settings", { method: "PUT", body }),
    onSuccess: (settings) => {
      client.setQueryData(queryKeys.settings, settings);
      client.removeQueries({ queryKey: ["graph"] });
      return client.invalidateQueries({ queryKey: queryKeys.session });
    },
  });
}

export function useConnectPortfolio() {
  const client = useQueryClient();
  return useMutation({
    mutationFn: (mockPortfolioId: string) =>
      api<Schemas["ConnectionResponse"]>("/api/portfolio/connections", { method: "POST", body: { mockPortfolioId } }),
    onSuccess: () => refreshAfterConnectionChange(client),
  });
}

export function useDisconnectPortfolio() {
  const client = useQueryClient();
  return useMutation({
    mutationFn: (connectionId: string) =>
      api<void>(`/api/portfolio/connections/${encodeURIComponent(connectionId)}`, { method: "DELETE" }),
    onSuccess: () => refreshAfterConnectionChange(client),
  });
}

/** 계좌 연결이 바뀌면 보유 표시가 들어간 조회(자산 지도·기업 보유 여부)를 모두 새로 받는다. */
function refreshAfterConnectionChange(client: QueryClient) {
  client.removeQueries({ queryKey: ["graph"] });
  void client.invalidateQueries({ queryKey: ["company"] });
  return client.invalidateQueries({ queryKey: queryKeys.portfolio });
}

export function useCreateChatSession() {
  return useMutation({
    mutationFn: (contextIds: string[]) =>
      api<Schemas["ChatSessionResponse"]>("/api/chat/sessions", { method: "POST", body: { contextIds } }),
  });
}

/** contextIds: 사용자가 이번 질문에 연결해 둔 대상(세션 대상 중 확인·해제 후 남은 것). */
export function useAskQuestion() {
  return useMutation({
    mutationFn: ({ sessionId, question, contextIds }: { sessionId: string; question: string; contextIds: string[] }) =>
      api<Schemas["ChatMessageResponse"]>(`/api/chat/sessions/${encodeURIComponent(sessionId)}/messages`, {
        method: "POST",
        body: { question, contextIds },
      }),
  });
}

// ---- AI 출력 좋아요/싫어요(요구 75). 한 사람이 대상마다 표 하나: 같은 값을 다시 누르면 취소, 다른 값을 누르면 바뀐다.

export type FeedbackFeature = Schemas["FeedbackVote"]["feature"];
type FeedbackItem = Schemas["FeedbackItem"];
const feedbackKey = (feature: FeedbackFeature, targetId: string) => ["feedback", feature, targetId] as const;

export function useMyFeedback(feature: FeedbackFeature, targetId: string) {
  return useQuery({
    queryKey: feedbackKey(feature, targetId),
    queryFn: ({ signal }) => api<Schemas["FeedbackList"]>("/api/feedback", { query: { feature, targetIds: targetId }, signal }).then((list) => list.items[0] ?? null),
  });
}

export function useVote(feature: FeedbackFeature, targetId: string) {
  const client = useQueryClient();
  return useMutation({
    mutationFn: (body: { value: "up" | "down"; reason?: string }) => api<FeedbackItem>("/api/feedback", { method: "PUT", body: { feature, targetId, ...body } }),
    onSuccess: (item) => client.setQueryData(feedbackKey(feature, targetId), item),
  });
}

export function useCancelVote(feature: FeedbackFeature, targetId: string) {
  const client = useQueryClient();
  return useMutation({
    mutationFn: () => api<void>("/api/feedback", { method: "DELETE", query: { feature, targetId } }),
    onSuccess: () => client.setQueryData(feedbackKey(feature, targetId), null),
  });
}
