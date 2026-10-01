// 화면에서 쓰는 모든 BFF 조회/변경 훅. 화면 컴포넌트는 fetch를 직접 부르지 않고 여기의 훅만 쓴다.
//
// 느린 응답 덮어쓰기 방지(TC-16):
//  - 모든 조회는 TanStack Query가 넘겨주는 AbortSignal을 fetch에 전달한다. 사용자가 A 노드를 누른 뒤
//    곧바로 B 노드를 누르면 A 조회는 더 이상 화면에서 쓰이지 않으므로 Query가 요청을 취소(abort)한다.
//  - 결과는 노드 id가 들어간 queryKey별로 따로 저장된다. 늦게 도착한 A 응답은 A 칸에만 들어가고,
//    화면은 현재 선택된 B의 칸만 읽으므로 A 결과가 B 화면을 덮어쓸 수 없다(요청 순번 비교와 같은 효과).
import { keepPreviousData, useMutation, useQueries, useQuery, useQueryClient, type QueryClient } from "@tanstack/react-query";
import { api, type Schemas } from "./client";
import { useSearchParams } from "react-router";
import type { DetailRange } from "@/lib/company-timeline";
import type { GraphMode } from "@/lib/labels";

/** 주소의 ?round=<브리핑 회차 id>: 있으면 그래프 화면의 모든 조회가 그 회차를 발행할 당시의 자료를 쓴다(FS032). 없으면 현재 그래프. */
export function useAsOfRound(): string | null {
  const [params] = useSearchParams();
  return params.get("round");
}

export const queryKeys = {
  health: ["health"] as const,
  session: ["session"] as const,
  settings: ["settings"] as const,
  portfolio: ["portfolio"] as const,
  mockPortfolios: ["mock-portfolios"] as const,
  companies: (q: string) => ["companies", q] as const,
  company: (id: string, round: string | null = null) => ["company", id, round] as const,
  quote: (id: string) => ["quote", id] as const,
  metrics: (id: string) => ["metrics", id] as const,
  prices: (id: string, period: string, to: string) => ["prices", id, period, to] as const,
  graph: (mode: GraphMode, companyId?: string, round: string | null = null) => ["graph", mode, companyId ?? null, round] as const,
  edge: (id: string, round: string | null = null) => ["edge", id, round] as const,
  companyEvents: (companyId: string, from: string, to: string) => ["events", companyId, from, to] as const,
  companyDocuments: (companyId: string) => ["company-documents", companyId] as const,
  event: (id: string, round: string | null = null) => ["event", id, round] as const,
  evidence: (id: string, round: string | null = null) => ["evidence", id, round] as const,
  briefing: (date: string | null, edition: string | null) => ["briefing", date, edition] as const,
  briefingRounds: ["briefing", "rounds"] as const,
  briefingGraphBasis: (round: string) => ["briefing", "graph", round] as const,
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

/** 종목 검색(FS011-01): 실행한 검색어마다 따로 조회한다. 빈 검색어는 요청하지 않고, 이전 검색어 결과를 이어 보이지 않는다. */
export function useCompanySearch(q: string) {
  return useQuery({
    queryKey: queryKeys.companies(q),
    queryFn: ({ signal }) => api<Schemas["CompanyListResponse"]>("/api/companies", { query: { q }, signal }),
    enabled: q.length > 0,
  });
}

export function useCompany(id: string | undefined) {
  const round = useAsOfRound();
  return useQuery({
    queryKey: queryKeys.company(id ?? "", round),
    queryFn: ({ signal }) => api<Schemas["CompanyDetail"]>(`/api/companies/${encodeURIComponent(id!)}`, { query: { round }, signal }),
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

export type QuoteResponse = Schemas["CompanyQuote"] | Schemas["CompanyQuoteUnavailable"];
export type PriceResponse = Schemas["PriceSeries"] | Schemas["PriceSeriesUnavailable"];

/** 기업 상세 시세(현재가·지표). 기업 개요와 따로 조회해 늦거나 실패해도 다른 영역을 막지 않는다(요구 54). 보유 영역도 같은 칸을 쓴다. */
export function useCompanyQuote(id: string) {
  return useQuery({
    queryKey: queryKeys.quote(id),
    queryFn: ({ signal }) => api<QuoteResponse>(`/api/companies/${encodeURIComponent(id)}/quote`, { signal }),
    staleTime: 30_000,
  });
}

export type MetricsResponse = Schemas["CompanyMetrics"] | Schemas["CompanyMetricsUnavailable"];

/** 기업 상세 주요 지표(시가총액·PER·PBR 등). 시세와 다른 출처라 따로 조회하고, 실패해도 시세는 그대로다(요구 39·54). */
export function useCompanyMetrics(id: string) {
  return useQuery({
    queryKey: queryKeys.metrics(id),
    queryFn: ({ signal }) => api<MetricsResponse>(`/api/companies/${encodeURIComponent(id)}/metrics`, { signal }),
    staleTime: 10 * 60_000,
  });
}

/** 주가 차트. 사건 타임라인과 같은 범위(공통 KST 종료 시각·달력 시작)로 조회하고, 범위마다 칸이 달라 마지막 조회 결과만 보인다(FS040). */
export function useCompanyPrices(id: string, range: DetailRange) {
  return useQuery({
    queryKey: queryKeys.prices(id, range.period, range.to),
    queryFn: ({ signal }) =>
      api<PriceResponse>(`/api/companies/${encodeURIComponent(id)}/prices`, { query: { period: range.period, from: range.from, to: range.to }, signal }),
    staleTime: 60_000,
  });
}

/**
 * 지도 전체 연결. depth·limit을 주지 않으면 BFF가 포커스에서 닿는 연결 요소 전체를(전체 모드는 전부, 개인화는 보유+관심에서 닿는 것) 기본 한도 500개까지 준다.
 * 주소에 ?round=가 있으면 그 브리핑 회차를 발행할 당시의 그래프다(FS032, 전체 모드만).
 */
export function useGraph(mode: GraphMode, enabled = true) {
  const round = useAsOfRound();
  return useQuery({
    queryKey: queryKeys.graph(mode, undefined, round),
    queryFn: ({ signal }) => api<Schemas["GraphResponse"]>("/api/graph", { query: { mode, round }, signal }),
    enabled,
    // 모드를 바꾸는 동안 이전 지도를 그대로 두어 캔버스가 다시 만들어지지 않게 한다(남는 노드는 제자리에서 이어진다).
    placeholderData: keepPreviousData,
  });
}

export function useEdge(id: string | undefined) {
  const round = useAsOfRound();
  return useQuery({
    queryKey: queryKeys.edge(id ?? "", round),
    queryFn: ({ signal }) => api<Schemas["EdgeDetail"]>(`/api/graph/edges/${encodeURIComponent(id!)}`, { query: { round }, signal }),
    enabled: Boolean(id),
  });
}

/** 기업 상세 타임라인: 차트와 같은 범위의 사건. 범위마다 따로 캐시해 늦게 온 이전 기간 응답이 지금 기간을 덮지 않는다(FS040). */
export function useCompanyEvents(companyId: string, range: DetailRange) {
  return useQuery({
    queryKey: queryKeys.companyEvents(companyId, range.from, range.to),
    queryFn: ({ signal }) => api<Schemas["EventListResponse"]>("/api/events", { query: { companyId, from: range.from, to: range.to }, signal }),
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

export function useEvent(id: string | undefined) {
  const round = useAsOfRound();
  return useQuery({
    queryKey: queryKeys.event(id ?? "", round),
    queryFn: ({ signal }) => api<Schemas["EventDetail"]>(`/api/events/${encodeURIComponent(id!)}`, { query: { round }, signal }),
    enabled: Boolean(id),
  });
}

/** 기업 상세의 선택 사건(FS040·FS044): 조회 범위(종료 시각)마다 따로 조회한다. 기간을 바꾸거나 상세로 돌아오면 새로 조회하고,
 *  이전 범위의 늦은 응답은 이전 칸에만 들어가 지금 상세를 덮지 않는다. */
export function useEventInRange(id: string | null, rangeTo: string) {
  const round = useAsOfRound();
  return useQuery({
    queryKey: [...queryKeys.event(id ?? "", round), rangeTo] as const,
    queryFn: ({ signal }) => api<Schemas["EventDetail"]>(`/api/events/${encodeURIComponent(id!)}`, { query: { round }, signal }),
    enabled: Boolean(id),
  });
}

/** 여러 사건을 한 번에 조회한다(지도 목록의 사건별 근거 수). useEvent와 캐시를 함께 쓴다. */
export function useEventsByIds(ids: string[]) {
  const round = useAsOfRound();
  return useQueries({
    queries: ids.map((id) => ({
      queryKey: queryKeys.event(id, round),
      queryFn: ({ signal }: { signal: AbortSignal }) =>
        api<Schemas["EventDetail"]>(`/api/events/${encodeURIComponent(id)}`, { query: { round }, signal }),
    })),
  });
}

export function useEvidenceItems(ids: string[]) {
  const round = useAsOfRound();
  return useQueries({
    queries: ids.map((id) => ({
      queryKey: queryKeys.evidence(id, round),
      queryFn: ({ signal }: { signal: AbortSignal }) =>
        api<Schemas["EvidenceResponse"]>(`/api/evidence/${encodeURIComponent(id)}`, { query: { round }, signal }),
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

/** 브리핑 회차 기준 그래프가 무엇에 고정돼 있는지(회차·기준 시점·상태, FS032). available이 아니면 그래프를 읽지 않는다. */
export function useBriefingGraphBasis(round: string | null) {
  return useQuery({
    queryKey: queryKeys.briefingGraphBasis(round ?? ""),
    queryFn: ({ signal }) => api<Schemas["BriefingGraphBasis"]>(`/api/briefings/${encodeURIComponent(round!)}/graph`, { signal }),
    enabled: Boolean(round),
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

/** FS027 관심 단건 토글: 누름 자체가 저장 요청이다. 원하는 최종 상태를 보내 재전송·동시 요청이 멱등이다.
 *  저장에 성공한 뒤에만 설정(관심 목록)을 바꾸고, 개인화 그래프는 다시 조회만 한다(그래프 조회가 실패해도 관심 저장을 다시 보내지 않는다). */
export function useSetWatched() {
  const client = useQueryClient();
  return useMutation({
    mutationFn: ({ companyId, watched }: { companyId: string; watched: boolean }) =>
      api<Schemas["SettingsResponse"]>(`/api/me/watchlist/${encodeURIComponent(companyId)}`, { method: "PUT", body: { watched } }),
    onSuccess: (settings, { companyId }) => {
      client.setQueryData(queryKeys.settings, settings);
      void client.invalidateQueries({ queryKey: ["graph"] });
      void client.invalidateQueries({ queryKey: ["company", companyId] });
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

// ---- AI 질문(FS045–FS053): 질문 하나 = 서버가 저장하는 작업 하나.
// 작업 ID는 화면이 만든다. 응답을 받지 못하면 같은 ID로 상태를 먼저 조회하고, 서버가 "없다"고 확인한 경우에만 같은 내용으로 다시 보낸다.

export type ChatJob = Schemas["ChatJob"];
export type ChatConversation = Schemas["ChatConversation"];
export type ChatJobRequest = Schemas["ChatJobRequest"];

export const chatKeys = {
  current: ["chat", "current"] as const,
  session: (id: string) => ["chat", "session", id] as const,
};

export const isChatJobActive = (job: Pick<ChatJob, "status">) => job.status === "queued" || job.status === "running";

const sessionPath = (id: string) => `/api/chat/sessions/${encodeURIComponent(id)}`;
const jobPath = (id: string) => `/api/chat/jobs/${encodeURIComponent(id)}`;

/** 서버와 주고받는 질문 요청. 상태 변경 호출은 모두 멱등이라 응답을 놓친 뒤 다시 보내도 질문이 늘지 않는다. */
export const chatRequests = {
  createSession: (id: string) => api<Schemas["ChatSessionResponse"]>(sessionPath(id), { method: "PUT" }),
  submit: (sessionId: string, body: ChatJobRequest) => api<ChatJob>(`${sessionPath(sessionId)}/jobs`, { method: "POST", body }),
  job: (jobId: string, signal?: AbortSignal) => api<ChatJob>(jobPath(jobId), { signal }),
  retry: (jobId: string) => api<ChatJob>(`${jobPath(jobId)}/retry`, { method: "POST" }),
  cancel: (jobId: string) => api<ChatJob>(`${jobPath(jobId)}/cancel`, { method: "POST" }),
};

/** 회원의 가장 최근 대화. 패널을 닫았다 다시 열거나 다른 화면에서 열어도 같은 대화를 찾는 방법이다. */
export function useCurrentChat(enabled: boolean) {
  const client = useQueryClient();
  return useQuery({
    queryKey: chatKeys.current,
    queryFn: async ({ signal }) => {
      const { conversation } = await api<Schemas["ChatCurrentResponse"]>("/api/chat/sessions/current", { signal });
      if (conversation) client.setQueryData(chatKeys.session(conversation.session.id), conversation);
      return conversation?.session.id ?? null;
    },
    enabled,
    staleTime: 0,
  });
}

/** 대화 하나와 그 작업들. 처리 중인 작업이 있는 동안(패널이 열려 있을 때) 상태를 계속 확인한다. */
export function useChatConversation(sessionId: string | null, enabled: boolean) {
  return useQuery({
    queryKey: chatKeys.session(sessionId ?? ""),
    queryFn: ({ signal }) => api<ChatConversation>(sessionPath(sessionId!), { signal }),
    enabled: enabled && Boolean(sessionId),
    staleTime: 0,
    refetchInterval: (query) => (query.state.data?.jobs.some(isChatJobActive) ? 800 : false),
  });
}

// ---- AI 결과 평가(FS066-01, D08). 로그인 회원만. 화면은 원하는 최종 상태(up·down·none)를 보내 재전송이 다시 토글되지 않는다.

export type FeedbackFeature = Schemas["FeedbackVote"]["feature"];
export type FeedbackValue = Schemas["FeedbackVote"]["value"];
type FeedbackItem = Schemas["FeedbackItem"];
const feedbackKey = (feature: FeedbackFeature, targetId: string) => ["feedback", feature, targetId] as const;

export function useMyFeedback(feature: FeedbackFeature, targetId: string, enabled: boolean) {
  return useQuery({
    queryKey: feedbackKey(feature, targetId),
    queryFn: ({ signal }) =>
      api<Schemas["FeedbackList"]>("/api/feedback", { query: { feature, targetIds: targetId }, signal }).then((list): FeedbackItem | null => list.items[0] ?? null),
    enabled,
  });
}

export function useRate(feature: FeedbackFeature, targetId: string, targetVersion?: string | null) {
  const client = useQueryClient();
  return useMutation({
    mutationFn: (body: { value: FeedbackValue; reason?: string }) =>
      api<FeedbackItem>("/api/feedback", { method: "PUT", body: { feature, targetId, ...(targetVersion ? { targetVersion } : {}), ...body } }),
    onSuccess: (item) => client.setQueryData(feedbackKey(feature, targetId), item.value === "none" ? null : item),
  });
}
