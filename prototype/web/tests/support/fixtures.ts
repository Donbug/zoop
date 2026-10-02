// 시험용 세계: 가상의 두 기업(알파전자·베타화학)과 로그인한 회원 한 명.
// 응답 타입은 BFF에서 생성한 schema.d.ts를 그대로 써서, 계약이 바뀌면 이 파일이 먼저 타입 오류를 낸다.
// 기업마다 기간별 사건·차트 값이 서로 달라서, 화면에 어느 기업·어느 기간의 값이 들어왔는지 값만 보고 알 수 있다.
import type { Schemas } from "@/api/client";
import type { Period } from "@/lib/company-timeline";
import { apiError, json, noContent, type FakeBff, type Handler } from "./fake-bff";

type Metadata = Schemas["Metadata"];

export const metadata: Metadata = {
  datasetKind: "synthetic-preview",
  source: "test",
  asOf: "2026-10-02T09:00:00+09:00",
  sourceMode: "snapshot",
  synthetic: true,
  generatedBy: null,
  graphVersion: "v1",
};

export interface TestEvent {
  id: string;
  title: string;
  eventTime: string;
}

export interface TestCompany {
  id: string;
  name: string;
  ticker: string;
  /** 시세 영역의 현재가(원) */
  price: number;
  /** 주요 지표 영역의 PER */
  per: string;
  /** 기간별 사건. 기간마다 제목이 달라 어느 기간의 응답인지 알 수 있다. */
  events: Record<Period, TestEvent[]>;
  /** 기간별 차트 종가. 마지막 값이 그 기간 차트의 마지막 종가다. */
  closes: Record<Period, number[]>;
}

export const ALPHA: TestCompany = {
  id: "KRX:100001",
  name: "알파전자",
  ticker: "100001",
  price: 71_000,
  per: "12.35",
  events: {
    "1d": [{ id: "ev-alpha-1d", title: "알파전자 신공장 착공 발표", eventTime: "2026-10-02" }],
    "1m": [{ id: "ev-alpha-1m", title: "알파전자 장비 공급 계약 체결", eventTime: "2026-09-20" }],
    "1y": [{ id: "ev-alpha-1y", title: "알파전자 해외 법인 설립", eventTime: "2026-03-10" }],
  },
  closes: { "1d": [70_800, 71_400], "1m": [69_900, 70_200], "1y": [64_100, 64_800] },
};

export const BETA: TestCompany = {
  id: "KRX:100002",
  name: "베타화학",
  ticker: "100002",
  price: 205_000,
  per: "8.10",
  events: {
    "1d": [{ id: "ev-beta-1d", title: "베타화학 오늘의 공시", eventTime: "2026-10-02" }],
    "1m": [{ id: "ev-beta-1m", title: "베타화학 배터리 소재 증설", eventTime: "2026-09-21" }],
    "1y": [{ id: "ev-beta-1y", title: "베타화학 연간 생산 목표 상향", eventTime: "2026-02-14" }],
  },
  closes: { "1d": [204_000, 205_600], "1m": [198_000, 203_300], "1y": [150_000, 199_900] },
};

export const MEMBER_NAME = "시험회원";
export const OTHER_MEMBER_NAME = "다른회원";
export const memberSession = (user: { id: string; displayName: string } = { id: "member-1", displayName: MEMBER_NAME }): Schemas["SessionResponse"] => ({
  authenticated: true,
  kind: "member",
  user: { id: user.id, email: `${user.id}@zoop.test`, displayName: user.displayName },
  setup: { completed: true, tutorialCompleted: true },
  metadata,
});
export const anonymousSession = (): Schemas["SessionResponse"] => ({ authenticated: false, kind: "anonymous", user: null, setup: null, metadata });

export const companySummary = (c: TestCompany): Schemas["CompanySummary"] => ({
  id: c.id,
  name: c.name,
  ticker: c.ticker,
  aliases: [],
  sector: "전자",
  brandColor: null,
  logoUrl: null,
  issueCount: c.events["1m"].length,
});

export const companyDetail = (c: TestCompany): Schemas["CompanyDetail"] => ({
  ...companySummary(c),
  directIssues: Object.values(c.events)
    .flat()
    .map((e) => ({ issueId: e.id, title: e.title, eventTime: e.eventTime, timePrecision: "day", role: null, assertionStatus: null, evidenceCount: 0, basis: [] })),
  structuralIssues: [],
  summary: { status: "unavailable", reason: "요약 없음" },
  holding: null,
  watch: null,
  metadata,
});

const source: Schemas["QuoteSourceOut"] = { provider: "toss", name: "시험 시세", official: false, delayNote: null, symbol: "TEST", url: null };

export const quoteOf = (c: TestCompany): Schemas["CompanyQuote"] => ({
  status: "available",
  companyId: c.id,
  source,
  quote: {
    currency: "KRW",
    price: c.price,
    asOf: "2026-10-02T09:00:00+09:00",
    previousClose: null,
    change: null,
    changeRate: null,
    dayHigh: null,
    dayLow: null,
    volume: null,
    fiftyTwoWeekHigh: null,
    fiftyTwoWeekLow: null,
    marketCap: null,
    sharesOutstanding: null,
    derived: [],
  },
});

export const metricsOf = (c: TestCompany): Schemas["CompanyMetrics"] => ({
  status: "available",
  companyId: c.id,
  source: { ...source, provider: "naver", name: "시험 지표" },
  asOf: "2026-10-02T09:00:00+09:00",
  items: [{ code: "per", label: "PER", value: c.per, basis: null }],
});

export const pricesOf = (c: TestCompany, period: Period): Schemas["PriceSeries"] => ({
  status: "available",
  companyId: c.id,
  period,
  source,
  currency: "KRW",
  interval: period === "1d" ? "5m" : "1d",
  points: c.closes[period].map((close, i) => ({
    time: period === "1d" ? `2026-10-02T09:${String(i * 5).padStart(2, "0")}:00+09:00` : `2026-09-${String(20 + i).padStart(2, "0")}T00:00:00+09:00`,
    open: close,
    high: close,
    low: close,
    close,
    volume: null,
  })),
});

/** 사건 목록 요청(from·to)이 어느 기간인지: 하루 안이면 1일, 한 달 안이면 1개월, 그보다 길면 1년. */
export function periodOfRange(from: string, to: string): Period {
  const days = (Date.parse(to) - Date.parse(from)) / 86_400_000;
  if (days < 1) return "1d";
  return days <= 32 ? "1m" : "1y";
}

export const eventList = (events: TestEvent[]): Schemas["EventListResponse"] => ({
  items: events.map((e) => ({
    id: e.id,
    title: e.title,
    action: null,
    target: null,
    eventTime: e.eventTime,
    timePrecision: "day",
    period: null,
    companyIds: [],
    articleCount: 1,
    reportedAt: `${e.eventTime}T09:00:00+09:00`,
  })),
  unknownTimeItems: [],
  metadata: { ...metadata, total: events.length, excludedUnknownTime: 0, latestEventTime: events[0]?.eventTime ?? null, latestReportedAt: null },
});

export const eventDetail = (event: TestEvent, company: TestCompany): Schemas["EventDetail"] => ({
  id: event.id,
  title: event.title,
  eventTime: event.eventTime,
  timePrecision: "day",
  period: null,
  mentions: [],
  articles: [],
  relations: [],
  companies: [{ id: company.id, name: company.name, role: null, roleUnconfirmed: false, relationType: "INVOLVES" }],
  sourceSupport: { articleCount: 0, knownLineageCount: null, unknownLineageArticles: [], independentSourceCount: null, duplicateGroups: [] },
  fieldDecisions: [],
  evidenceIds: [],
  follows: { previous: [], next: [] },
  approval: null,
  summary: { status: "unavailable", reason: "요약 없음" },
  metadata,
});

/** 가상 계좌에서 기업 c를 보유한 상태 */
export const holdingsPortfolio = (c: TestCompany = ALPHA): Schemas["PortfolioResponse"] => ({
  connected: true,
  connection: {
    id: "conn-1",
    mockPortfolioId: "mock-1",
    accountId: "MOCK-TEST",
    label: "시험 가상 계좌",
    connectedAt: "2026-10-01T09:00:00+09:00",
    cash: null,
    status: "connected",
  },
  holdings: [
    {
      companyId: c.id,
      name: c.name,
      ticker: c.ticker,
      quantity: 10,
      avgPrice: 68_000,
      avgPriceCurrency: "KRW",
      quote: { status: "unavailable", reason: "시세 없음" },
      marketValue: null,
      weight: null,
    },
  ],
  mockAsOf: null,
  valuation: {
    calculatedAt: "2026-10-02T09:00:00+09:00",
    currency: null,
    totalMarketValue: null,
    weightStatus: "unavailable",
    weightUnavailableCode: "missing_price",
    weightUnavailableReason: "시세 없음",
  },
  metadata,
});

/** 가상 계좌를 연결하지 않은 상태 */
export const disconnectedPortfolio = (): Schemas["PortfolioResponse"] => ({
  connected: false,
  connection: null,
  holdings: [],
  mockAsOf: null,
  valuation: null,
  metadata,
});

export const watchSettings = (watchlistIds: string[]): Schemas["SettingsResponse"] => ({
  mode: "watchlist",
  watchlistIds,
  tutorialCompleted: true,
  completed: true,
  investor: true,
  version: 1,
  metadata,
});

const health: Schemas["HealthResponse"] = {
  status: "ok",
  source: { mode: "snapshot", label: "시험", connected: true, error: null },
  datasetKind: "synthetic-preview",
  asOf: metadata.asOf,
  graphVersion: "v1",
  counts: null,
  sourceErrors: [],
  warnings: [],
};

/** 지도 조회 응답. 전체는 두 기업과 사건 하나, 개인화(보유·관심)는 알파전자와 그 사건만 담아 어느 모드의 지도인지 노드로 알 수 있다. */
export const graphOf = (mode: "all" | "personal"): Schemas["GraphResponse"] => {
  const issue = ALPHA.events["1m"][0]!;
  const company = (c: TestCompany, mine: boolean): Schemas["GraphNode"] => ({
    id: c.id,
    kind: "company",
    label: c.name,
    isFocus: false,
    holding: mine,
    watch: mine,
    brandColor: null,
    logoUrl: null,
    eventTime: null,
    timePrecision: null,
    action: null,
    target: null,
    evidenceCount: null,
  });
  const edge = (c: TestCompany): Schemas["GraphEdge"] => ({
    id: `edge-${c.ticker}`,
    source: c.id,
    target: issue.id,
    relationType: "INVOLVES",
    role: null,
    summary: "관련",
    assertionStatus: null,
    derived: false,
    via: [],
    evidenceIds: [],
  });
  const members = mode === "all" ? [ALPHA, BETA] : [ALPHA];
  return {
    nodes: [
      ...members.map((c) => company(c, mode === "personal")),
      { ...company(ALPHA, false), id: issue.id, kind: "issue", label: issue.title, eventTime: issue.eventTime, timePrecision: "day", evidenceCount: 1 },
    ],
    edges: members.map(edge),
    metadata: {
      datasetKind: "synthetic-preview",
      source: "test",
      asOf: metadata.asOf,
      sourceMode: "snapshot",
      synthetic: true,
      generatedBy: null,
      graphVersion: "v1",
      mode,
      truncated: false,
      emptyReason: null,
      focusCompanyIds: [],
      depth: null,
      limit: 500,
    },
  };
};

/** 시험 세계의 서버 쪽 상태. 시험이 로그인 상태·보유·관심을 바꾸면 이후 응답에 반영된다. */
export class World {
  readonly companies = new Map([ALPHA, BETA].map((c) => [c.id, c]));
  session = memberSession();
  portfolio = holdingsPortfolio();
  settings = watchSettings([ALPHA.id]);
  /** 로그인 요청이 만들 세션(다른 회원으로 들어오는 시험용) */
  nextLogin: Schemas["SessionResponse"] | null = null;

  #company(id: string) {
    return this.companies.get(id);
  }

  /** 기본 응답을 BFF 대역에 등록한다. 시험은 `bff.on`/`bff.hold`로 필요한 경로만 덮어쓴다. */
  serve(bff: FakeBff) {
    const notFound = () => apiError(404, "company_not_found", "기업을 찾을 수 없어요");
    const memberOnly =
      (reply: Handler): Handler =>
      (request, params) =>
        this.session.kind === "member" ? reply(request, params) : apiError(401, "auth_required", "로그인이 필요해요");

    bff.on("GET", "/api/health", json(health));
    bff.on("GET", "/api/auth/session", () => json(this.session));
    bff.on("POST", "/api/auth/logout", () => {
      this.session = anonymousSession();
      return noContent();
    });
    bff.on("POST", "/api/auth/login", () => {
      this.session = this.nextLogin ?? memberSession();
      return json(this.session);
    });
    bff.on("GET", "/api/me/settings", memberOnly(() => json(this.settings)));
    bff.on(
      "PUT",
      "/api/me/settings",
      memberOnly((request) => {
        const { watchlistIds } = request.body as { watchlistIds?: string[] };
        this.settings = { ...this.settings, watchlistIds: watchlistIds ?? this.settings.watchlistIds, version: this.settings.version + 1 };
        return json(this.settings);
      }),
    );
    bff.on("GET", "/api/portfolio", memberOnly(() => json(this.portfolio)));
    bff.on("GET", "/api/portfolio/mock-portfolios", json({ items: [], metadata }));
    bff.on("GET", "/api/auth/social/providers", json({ items: [] }));

    bff.on("GET", "/api/companies", (request) => {
      const q = request.query.get("q") ?? "";
      return json({ items: [...this.companies.values()].filter((c) => c.name.includes(q) || c.ticker.includes(q)).map(companySummary), metadata });
    });
    bff.on("GET", "/api/companies/:id", (_, { id }) => {
      const c = this.#company(id!);
      return c ? json(companyDetail(c)) : notFound();
    });
    bff.on("GET", "/api/companies/:id/quote", (_, { id }) => {
      const c = this.#company(id!);
      return c ? json(quoteOf(c)) : notFound();
    });
    bff.on("GET", "/api/companies/:id/metrics", (_, { id }) => {
      const c = this.#company(id!);
      return c ? json(metricsOf(c)) : notFound();
    });
    bff.on("GET", "/api/companies/:id/prices", (request, { id }) => {
      const c = this.#company(id!);
      return c ? json(pricesOf(c, request.query.get("period") as Period)) : notFound();
    });
    bff.on("GET", "/api/companies/:id/documents", json({ items: [], metadata }));
    bff.on("GET", "/api/events", (request) => {
      const c = this.#company(request.query.get("companyId") ?? "");
      if (!c) return notFound();
      return json(eventList(c.events[periodOfRange(request.query.get("from")!, request.query.get("to")!)]));
    });
    bff.on("GET", "/api/events/:id", (_, { id }) => {
      for (const c of this.companies.values()) {
        const e = Object.values(c.events).flat().find((x) => x.id === id);
        if (e) return json(eventDetail(e, c));
      }
      return apiError(404, "event_not_found", "사건을 찾을 수 없어요");
    });
    bff.on("GET", "/api/graph", (request) => json(graphOf(request.query.get("mode") === "personal" ? "personal" : "all")));
    bff.on("POST", "/api/telemetry", noContent());
  }
}
