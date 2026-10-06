// 화면에서 쓰는 모든 BFF 조회/변경 훅. 화면 컴포넌트는 fetch를 직접 부르지 않고 여기의 훅만 쓴다.
//
// 느린 응답 덮어쓰기 방지(TC-16):
//  - 모든 조회는 TanStack Query가 넘겨주는 AbortSignal을 fetch에 전달한다. 사용자가 A 노드를 누른 뒤
//    곧바로 B 노드를 누르면 A 조회는 더 이상 화면에서 쓰이지 않으므로 Query가 요청을 취소(abort)한다.
//  - 결과는 노드 id가 들어간 queryKey별로 따로 저장된다. 늦게 도착한 A 응답은 A 칸에만 들어가고,
//    화면은 현재 선택된 B의 칸만 읽으므로 A 결과가 B 화면을 덮어쓸 수 없다(요청 순번 비교와 같은 효과).
//
// 로그아웃 뒤 늦은 개인 응답(FS007):
//  - 개인 조회(설정·보유·가상 계좌·추천·대화·평가)의 키에는 세션 세대(personalEpoch)가 들어간다. 로그인·가입·비회원 시작·로그아웃마다
//    세대가 바뀌므로, 이전 회원의 요청이 늦게 끝나도 그 응답은 지금 화면이 읽지 않는 이전 세대 칸에만 들어간다.
//  - 로그아웃은 누르는 즉시 개인 캐시를 비우고(진행 중인 요청은 취소된다) 세션을 미로그인으로 표시해 개인 조회를 멈춘다.
//    서버 처리가 끝나면 그 사이에 받은 응답까지 한 번 더 비우고 세션을 서버에서 다시 확인한다.
//  - 로그아웃은 화면 캐시만 비운다. 서버의 대화 기록은 지우지 않는다(삭제가 아니다).
import { keepPreviousData, useMutation, useQueries, useQuery, useQueryClient, type QueryClient } from "@tanstack/react-query";
import { useSyncExternalStore } from "react";
import { api, type Schemas } from "./client";
import { useSearchParams } from "react-router";
import type { DetailRange } from "@/lib/company-timeline";
import type { GraphMode } from "@/lib/labels";
import { savePersonalFilter } from "@/lib/personal-filter";

let personalEpoch = 0;
const epochListeners = new Set<() => void>();
function subscribeEpoch(listener: () => void) {
  epochListeners.add(listener);
  return () => epochListeners.delete(listener);
}
/** 개인 조회 훅이 세대가 바뀔 때 새 키로 다시 그리도록 구독한다. */
export function usePersonalEpoch() {
  return useSyncExternalStore(subscribeEpoch, () => personalEpoch);
}
/** 비동기 작업이 시작될 때의 세대를 기억해 두었다가, 끝났을 때 세대가 바뀌었는지(로그아웃·다른 회원 로그인) 확인하는 데 쓴다. */
export const currentPersonalEpoch = () => personalEpoch;

/** 주소의 ?round=<브리핑 회차 id>: 있으면 그래프 화면의 모든 조회가 그 회차를 발행할 당시의 자료를 쓴다(FS032). 없으면 현재 그래프. */
export function useAsOfRound(): string | null {
  const [params] = useSearchParams();
  return params.get("round");
}

export const queryKeys = {
  health: ["health"] as const,
  session: ["session"] as const,
  settings: (epoch = personalEpoch) => ["settings", epoch] as const,
  portfolio: (epoch = personalEpoch) => ["portfolio", epoch] as const,
  mockPortfolios: (epoch = personalEpoch) => ["mock-portfolios", epoch] as const,
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
  recommendations: (epoch = personalEpoch) => ["recommendations", epoch] as const,
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
  const epoch = usePersonalEpoch();
  return useQuery({
    queryKey: queryKeys.settings(epoch),
    queryFn: ({ signal }) => api<Schemas["SettingsResponse"]>("/api/me/settings", { signal }),
    enabled,
  });
}

/** 연결한 가상 계좌의 모의 보유와 평가(같은 계산 시점 시세의 평가 금액·자산 비중, FS039·FS054). */
export function usePortfolio(enabled = true) {
  const epoch = usePersonalEpoch();
  return useQuery({
    queryKey: queryKeys.portfolio(epoch),
    queryFn: ({ signal }) => api<Schemas["PortfolioResponse"]>("/api/portfolio", { signal }),
    enabled,
  });
}

export function useMockPortfolios(enabled = true) {
  const epoch = usePersonalEpoch();
  return useQuery({
    queryKey: queryKeys.mockPortfolios(epoch),
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
  const epoch = usePersonalEpoch();
  return useQuery({
    queryKey: queryKeys.recommendations(epoch),
    queryFn: ({ signal }) => api<Schemas["RecommendationResponse"]>("/api/me/recommendations", { signal }),
    enabled,
  });
}

/** 종목 메뉴(FS037): 검색어가 없으면 전체 카탈로그. 검색 컴포넌트와 같은 키를 공유한다. */
export function useCompanyList(q: string) {
  return useQuery({
    queryKey: queryKeys.companies(q),
    queryFn: ({ signal }) => api<Schemas["CompanyListResponse"]>("/api/companies", { query: { q }, signal }),
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

export function useCompany(id: string | undefined, asOfOverride?: string | null) {
  const round = useAsOfRound();
  const [params] = useSearchParams();
  const asOf = asOfOverride === undefined ? params.get("asOf") : asOfOverride;
  return useQuery({
    queryKey: asOf ? [...queryKeys.company(id ?? "", round), asOf] : queryKeys.company(id ?? "", round),
    queryFn: ({ signal }) => api<Schemas["CompanyDetail"]>(`/api/companies/${encodeURIComponent(id!)}`, { query: { round, asOf }, signal }),
    enabled: Boolean(id),
  });
}

/** 여러 기업을 한 번에 조회한다(사이드바 관심 종목 이름 표시용). */
export function useCompanies(ids: string[], asOfOverride?: string | null) {
  const round = useAsOfRound();
  const [params] = useSearchParams();
  const asOf = asOfOverride === undefined ? params.get("asOf") : asOfOverride;
  return useQueries({
    queries: ids.map((id) => ({
      queryKey: asOf ? [...queryKeys.company(id, round), asOf] : queryKeys.company(id, round),
      queryFn: ({ signal }: { signal: AbortSignal }) =>
        api<Schemas["CompanyDetail"]>(`/api/companies/${encodeURIComponent(id)}`, { query: { round, asOf }, signal }),
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
 * round가 있으면 그 브리핑 회차를 발행할 당시의 그래프다(FS032, 전체 모드만).
 * 메인 지도의 모드 전환(FS019)은 이 옵션으로 대상 모드를 먼저 받아 두고, 성공한 뒤에만 모드를 바꾼다.
 */
export function graphQuery(mode: GraphMode, round: string | null, asOf: string | null = null) {
  return {
    queryKey: asOf ? [...queryKeys.graph(mode, undefined, round), asOf] : queryKeys.graph(mode, undefined, round),
    queryFn: ({ signal }: { signal: AbortSignal }) => api<Schemas["GraphResponse"]>("/api/graph", { query: { mode, round, asOf }, signal }),
  };
}

/** 키가 바뀌면(모드·회차) 이전 지도를 이어 쓰지 않는다. 다른 모드·회차의 데이터에 지금 이름이 붙지 않게 하기 위해서다. */
export function useGraph(mode: GraphMode, enabled = true) {
  const round = useAsOfRound();
  const [params] = useSearchParams();
  return useQuery({ ...graphQuery(mode, round, params.get("asOf")), enabled });
}

export function useEdge(id: string | undefined) {
  const round = useAsOfRound();
  const [params] = useSearchParams();
  const asOf = params.get("asOf");
  return useQuery({
    queryKey: asOf ? [...queryKeys.edge(id ?? "", round), asOf] : queryKeys.edge(id ?? "", round),
    queryFn: ({ signal }) => api<Schemas["EdgeDetail"]>(`/api/graph/edges/${encodeURIComponent(id!)}`, { query: { round, asOf }, signal }),
    enabled: Boolean(id),
  });
}

/** 기업 상세 타임라인: 차트와 같은 범위의 사건. 범위마다 따로 캐시해 늦게 온 이전 기간 응답이 지금 기간을 덮지 않는다(FS040). */
export function useCompanyEvents(companyId: string, range: DetailRange, depth: 1 | 2 = 1) {
  return useQuery({
    queryKey: depth === 1 ? queryKeys.companyEvents(companyId, range.from, range.to) : [...queryKeys.companyEvents(companyId, range.from, range.to), depth],
    queryFn: ({ signal }) => api<Schemas["EventListResponse"]>("/api/events", { query: { companyId, from: range.from, to: range.to, depth }, signal }),
  });
}

/** 기업 중심 최대 2-hop. 지도의 현재 데이터 조회와 분리된 시점별 캐시. */
export function useCompanyGraph(companyId: string, asOf: string, depth: 1 | 2) {
  return useQuery({
    queryKey: ["company-graph", companyId, asOf, depth],
    queryFn: ({ signal }) => api<Schemas["GraphResponse"]>(`/api/companies/${encodeURIComponent(companyId)}/graph`, { query: { asOf, depth }, signal }),
  });
}

/** 기업 상세 문서 탭: 이 기업 사건들의 근거 기사(중복 없이, 최신 발행순). */
export function useCompanyDocuments(companyId: string, range?: DetailRange) {
  const round = useAsOfRound();
  const [params] = useSearchParams();
  const asOf = range ? null : params.get("asOf");
  return useQuery({
    queryKey: [...queryKeys.companyDocuments(companyId), ...(range ? [range.from, range.to] : asOf ? [asOf] : []), ...(round ? [round] : [])],
    queryFn: ({ signal }) =>
      api<Schemas["CompanyDocumentsResponse"]>(`/api/companies/${encodeURIComponent(companyId)}/documents`, { query: { from: range?.from, to: range?.to ?? asOf, round }, signal }),
  });
}

export function useEvent(id: string | undefined) {
  const round = useAsOfRound();
  const [params] = useSearchParams();
  const asOf = params.get("asOf");
  return useQuery({
    queryKey: asOf ? [...queryKeys.event(id ?? "", round), asOf] : queryKeys.event(id ?? "", round),
    queryFn: ({ signal }) => api<Schemas["EventDetail"]>(`/api/events/${encodeURIComponent(id!)}`, { query: { round, asOf }, signal }),
    enabled: Boolean(id),
  });
}

/** 기업 상세의 선택 사건(FS040·FS044): 조회 범위(종료 시각)마다 따로 조회한다. 기간을 바꾸거나 상세로 돌아오면 새로 조회하고,
 *  이전 범위의 늦은 응답은 이전 칸에만 들어가 지금 상세를 덮지 않는다. */
export function useEventInRange(id: string | null, rangeTo: string) {
  const round = useAsOfRound();
  return useQuery({
    queryKey: [...queryKeys.event(id ?? "", round), rangeTo] as const,
    queryFn: ({ signal }) => api<Schemas["EventDetail"]>(`/api/events/${encodeURIComponent(id!)}`, { query: { round, asOf: rangeTo }, signal }),
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

export function useEvidenceItems(ids: string[], companyId?: string) {
  const round = useAsOfRound();
  return useQueries({
    queries: ids.map((id) => ({
      queryKey: companyId ? [...queryKeys.evidence(id, round), companyId] : queryKeys.evidence(id, round),
      queryFn: ({ signal }: { signal: AbortSignal }) =>
        api<Schemas["EvidenceResponse"]>(`/api/evidence/${encodeURIComponent(id)}`, { query: { round, companyId }, signal }),
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

// 개인 데이터 캐시(보유·관심·대화·추천 등)를 비우고 세션 세대를 바꾼다. 공용 데이터(health)와 헤더가 구독 중인 session만 남긴다.
// 지우는 조회의 진행 중인 요청은 취소되고, 그 응답이 늦게 와도 캐시에 다시 들어가지 않는다.
export function clearPersonalCache(client: QueryClient) {
  personalEpoch += 1;
  // 개인화 지도 필터는 로그인 세션 범위(FS017): 새 로그인·로그아웃이면 전체로 시작한다.
  savePersonalFilter("all");
  client.removeQueries({ predicate: (q) => !["health", "session", "terms", "social-providers"].includes(String(q.queryKey[0])) });
  for (const listener of epochListeners) listener();
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

/** 로그아웃(FS007): 누르는 즉시 이전 회원의 개인 표시를 거두고, 서버 처리가 끝나면 그 사이 받은 응답까지 비운 뒤 세션을 다시 확인한다. */
export function useLogout() {
  const client = useQueryClient();
  return useMutation({
    mutationFn: () => api<void>("/api/auth/logout", { method: "POST" }),
    onMutate: () => {
      client.setQueryData<Schemas["SessionResponse"]>(queryKeys.session, (prev) =>
        prev && { ...prev, authenticated: false, kind: "anonymous", user: null, setup: null },
      );
      clearPersonalCache(client);
    },
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
      return client.invalidateQueries({ queryKey: ["settings"] });
    },
  });
}

export function useUpdateSettings() {
  const client = useQueryClient();
  return useMutation({
    mutationFn: (body: Schemas["SettingsUpdate"]) =>
      api<Schemas["SettingsResponse"]>("/api/me/settings", { method: "PUT", body }),
    // 보낸 세대의 칸에 넣는다: 저장 중 로그아웃했으면 이전 회원 설정이 새 세대에 들어가지 않는다.
    onMutate: () => ({ epoch: personalEpoch }),
    onSuccess: (settings, _body, context) => {
      client.setQueryData(queryKeys.settings(context.epoch), settings);
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
    onMutate: () => ({ epoch: personalEpoch }),
    onSuccess: (settings, { companyId }, context) => {
      client.setQueryData(queryKeys.settings(context.epoch), settings);
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
  return client.invalidateQueries({ queryKey: ["portfolio"] });
}

// ---- AI 질문(FS045–FS053): 질문 하나 = 서버가 저장하는 작업 하나.
// 작업 ID는 화면이 만든다. 응답을 받지 못하면 같은 ID로 상태를 먼저 조회하고, 서버가 "없다"고 확인한 경우에만 같은 내용으로 다시 보낸다.

export type ChatJob = Schemas["ChatJob"];
export type ChatConversation = Schemas["ChatConversation"];
export type ChatJobRequest = Schemas["ChatJobRequest"];

/** 대화 키도 세션 세대별이다(FS007). use-chat의 setQueryData는 부르는 시점의 세대 칸을 쓴다. */
export const chatKeys = {
  current: (epoch = personalEpoch) => ["chat", epoch, "current"] as const,
  session: (id: string, epoch = personalEpoch) => ["chat", epoch, "session", id] as const,
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
  const epoch = usePersonalEpoch();
  return useQuery({
    queryKey: chatKeys.current(epoch),
    queryFn: async ({ signal }) => {
      const { conversation } = await api<Schemas["ChatCurrentResponse"]>("/api/chat/sessions/current", { signal });
      if (conversation) client.setQueryData(chatKeys.session(conversation.session.id, epoch), conversation);
      return conversation?.session.id ?? null;
    },
    enabled,
    staleTime: 0,
  });
}

/** 대화 하나와 그 작업들. 처리 중인 작업이 있는 동안(패널이 열려 있을 때) 상태를 계속 확인한다. */
export function useChatConversation(sessionId: string | null, enabled: boolean) {
  const epoch = usePersonalEpoch();
  return useQuery({
    queryKey: chatKeys.session(sessionId ?? "", epoch),
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
const feedbackKey = (feature: FeedbackFeature, targetId: string, epoch = personalEpoch) => ["feedback", epoch, feature, targetId] as const;

export function useMyFeedback(feature: FeedbackFeature, targetId: string, enabled: boolean) {
  const epoch = usePersonalEpoch();
  return useQuery({
    queryKey: feedbackKey(feature, targetId, epoch),
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
    onMutate: () => ({ epoch: personalEpoch }),
    onSuccess: (item, _body, context) => client.setQueryData(feedbackKey(feature, targetId, context.epoch), item.value === "none" ? null : item),
  });
}
