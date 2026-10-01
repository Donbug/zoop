// 디자인시스템(/design-system): 원칙 → 색 → 글꼴 → 형태 → 간격 → 컴포넌트 → 그래프 → 모션 → 아이콘 → 라이팅 → 슬롭 금지.
// 컴포넌트는 앱에서 쓰는 코드를 그대로 렌더링한다. 데이터는 모두 정적 예시다(서버를 부르지 않는다).
import {
  ArrowUpRight,
  Bookmark,
  Building2,
  CalendarClock,
  Clock,
  FileText,
  FlaskConical,
  Globe,
  Info,
  Link2,
  Map as MapIcon,
  MessageCircleQuestion,
  Network,
  Newspaper,
  ShieldCheck,
  SlidersHorizontal,
  Sparkles,
  Star,
  Wallet,
  Zap,
  type LucideIcon,
} from "lucide-react";
import { useEffect, useState, type ReactNode } from "react";
import type { Schemas } from "@/api/client";
import { ApiError } from "@/api/client";
import { AiBadge, AiDisclosure, AiNotice } from "@/components/domain/ai";
import { BriefingCard } from "@/components/domain/briefing-card";
import { CompanyHeader } from "@/components/domain/company-header";
import { CompanyMark } from "@/components/domain/company-mark";
import { EventRow, IconCount } from "@/components/domain/event-row";
import { DocumentItem, documentRelationLabel } from "@/components/domain/document-item";
import { EvidenceList, VerificationBadge } from "@/components/domain/evidence";
import { GraphCanvas, type GraphSelection } from "@/components/domain/graph-canvas";
import { FocusBar } from "@/components/domain/focus-bar";
import { PathBar } from "@/components/domain/path-bar";
import { GraphLegend, GraphModeSwitch, MarkRing } from "@/components/domain/graph-legend";
import { RelationList } from "@/components/domain/relation-list";
import { EdgeGlyph } from "@/components/domain/relation-type-tag";
import { SourceIndicator } from "@/components/domain/source-indicator";
import { DisclaimerNote, PriceChange, SentimentLabel } from "@/components/domain/status-labels";
import { AppBar } from "@/components/ui/app-bar";
import { Badge } from "@/components/ui/badge";
import { BottomSheet } from "@/components/ui/bottom-sheet";
import { BottomTabBar } from "@/components/ui/bottom-tab-bar";
import { Button } from "@/components/ui/button";
import { Dialog, Sheet } from "@/components/ui/dialog";
import { EmptyState, ErrorState, SkeletonLines, SkeletonRows } from "@/components/ui/feedback";
import { IconHint } from "@/components/ui/icon-hint";
import { Input } from "@/components/ui/input";
import { ListRow } from "@/components/ui/list-row";
import { Popover } from "@/components/ui/popover";
import { SectionHeader } from "@/components/ui/section-header";
import { Segmented } from "@/components/ui/segmented";
import { Select } from "@/components/ui/select";
import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/ui/tabs";
import { useToast } from "@/components/ui/toast";
import { Tooltip } from "@/components/ui/tooltip";
import { shortestPath } from "@/lib/graph-path";
import type { GraphFocus, LegendKey } from "@/lib/graph-view";
import { datasetDescription, datasetLabel, relationDescription, relationLabel, type DatasetKind, type GraphMode, type RelationType } from "@/lib/labels";
import { cn } from "@/lib/utils";
import { colorTokens, fontFamilyTokens, motionTokens, spacingTokens } from "@/styles/tokens.generated";

// ---------- 목차와 공통 틀

const toc = [
  { id: "principles", label: "원칙" },
  { id: "colors", label: "색" },
  { id: "typography", label: "글꼴" },
  { id: "shape", label: "형태" },
  { id: "spacing", label: "간격" },
  { id: "components", label: "기본 컴포넌트" },
  { id: "domain", label: "줍 컴포넌트" },
  { id: "graph", label: "그래프" },
  { id: "motion", label: "모션" },
  { id: "icons", label: "아이콘" },
  { id: "writing", label: "UX 라이팅" },
  { id: "slop", label: "슬롭 금지 체크리스트" },
];

function Section({ id, title, description, children }: { id: string; title: string; description?: ReactNode; children: ReactNode }) {
  return (
    <section id={id} aria-labelledby={`${id}-title`} className="flex scroll-mt-32 flex-col gap-6 border-t border-border-subtle pt-10 first-of-type:border-t-0 first-of-type:pt-0 lg:scroll-mt-20">
      <div className="flex max-w-prose flex-col gap-2">
        <h2 id={`${id}-title`} className="text-xl font-bold text-text-primary">
          {title}
        </h2>
        {description && <p className="text-base text-text-secondary">{description}</p>}
      </div>
      {children}
    </section>
  );
}

/** 컴포넌트 1개 = 제목 + 언제 쓰는지 + 1px 프레임 안 실제 렌더링 + 코드 한 줄. frame=false는 자기 경계가 있는 컴포넌트용. */
function Demo({ id, name, when, code, frame = true, children }: { id: string; name: string; when: ReactNode; code: string; frame?: boolean; children: ReactNode }) {
  return (
    <article id={id} aria-labelledby={`${id}-title`} className="flex scroll-mt-32 flex-col gap-3 lg:scroll-mt-20">
      <h3 id={`${id}-title`} className="text-lg font-semibold text-text-primary">
        {name}
      </h3>
      <p className="max-w-prose text-base text-text-secondary">{when}</p>
      <div className={cn("flex min-w-0 flex-col gap-4", frame && "border border-border-subtle p-4 md:p-6")}>{children}</div>
      <p className="max-w-prose text-sm text-text-secondary">
        <span className="sr-only">코드: </span>
        <code className="font-mono break-all">{code}</code>
      </p>
    </article>
  );
}

/** 프레임 안에서 '상태 이름 | 예시들' 한 줄 */
function StateRow({ label, children }: { label: string; children: ReactNode }) {
  return (
    <div className="flex flex-col gap-2 sm:flex-row sm:items-center sm:gap-4">
      <span className="shrink-0 text-sm text-text-secondary sm:w-20">{label}</span>
      <div className="flex min-w-0 flex-wrap items-center gap-3">{children}</div>
    </div>
  );
}

/** 좁은 화면에서 표만 가로로 밀리게 하는 국소 스크롤 컨테이너 */
function TableScroll({ label, children }: { label: string; children: ReactNode }) {
  return (
    <div role="region" aria-label={label} tabIndex={0} className="max-w-full overflow-x-auto">
      {children}
    </div>
  );
}

const th = "border-b border-border-strong px-3 py-2 text-left align-bottom text-sm font-semibold text-text-secondary";
const td = "border-b border-border-subtle px-3 py-3 align-top";

// ---------- 색

type Theme = "light" | "dark";
const colorByName: Record<string, (typeof colorTokens)[number]> = Object.fromEntries(colorTokens.map((t) => [t.name, t]));
function hexOf(name: string, theme: Theme) {
  const t = colorByName[name];
  return (theme === "dark" ? (t?.dark ?? t?.light) : t?.light) ?? "";
}

function luminance(hex: string) {
  const m = /^#([0-9a-f]{6})$/i.exec(hex.trim());
  if (!m) return null;
  const n = Number.parseInt(m[1]!, 16);
  const channel = (c: number) => {
    const s = c / 255;
    return s <= 0.04045 ? s / 12.92 : ((s + 0.055) / 1.055) ** 2.4;
  };
  return 0.2126 * channel((n >> 16) & 255) + 0.7152 * channel((n >> 8) & 255) + 0.0722 * channel(n & 255);
}

function contrast(a: string, b: string) {
  const la = luminance(a);
  const lb = luminance(b);
  if (la === null || lb === null) return null;
  const [hi, lo] = la > lb ? [la, lb] : [lb, la];
  return (hi + 0.05) / (lo + 0.05);
}

/** use: 어디에 쓰는지. against·min: 대비를 잴 바탕과 기준(글자 4.5, 선·테두리 3). against가 없으면 바탕·구분선이라 기준이 없다. */
interface ColorSpec {
  name: string;
  use: string;
  against?: string;
  min?: number;
}

const colorGroups: { title: string; items: ColorSpec[] }[] = [
  {
    title: "브랜드",
    items: [
      { name: "brand-primary", use: "주 행동 버튼 1개, 선택된 탭·행 표시", against: "surface-raised", min: 4.5 },
      { name: "brand-primary-hover", use: "주 행동 버튼에 마우스를 올렸을 때", against: "brand-primary-foreground", min: 4.5 },
      { name: "brand-primary-active", use: "주 행동 버튼을 누르는 동안", against: "brand-primary-foreground", min: 4.5 },
      { name: "brand-primary-foreground", use: "브랜드 바탕 위 글자·아이콘", against: "brand-primary", min: 4.5 },
    ],
  },
  {
    title: "바탕",
    items: [
      { name: "surface-base", use: "앱 바탕, 지도 캔버스" },
      { name: "surface-raised", use: "헤더, 패널, 목록 바탕" },
      { name: "surface-overlay", use: "시트, 다이얼로그, 팝오버처럼 떠 있는 면" },
      { name: "surface-sunken", use: "입력창 안, 배지 바탕, 눌린 면" },
      { name: "surface-selected", use: "선택된 행·항목 바탕" },
    ],
  },
  {
    title: "선",
    items: [
      { name: "border-subtle", use: "행과 영역 사이 구분선" },
      { name: "border-strong", use: "표 머리글 아래처럼 조금 더 뚜렷한 구분선" },
      { name: "border-control", use: "입력창·버튼처럼 누를 수 있는 것의 테두리", against: "surface-raised", min: 3 },
      { name: "border-focus", use: "키보드 포커스 링", against: "surface-raised", min: 3 },
    ],
  },
  {
    title: "글자",
    items: [
      { name: "text-primary", use: "제목, 본문", against: "surface-raised", min: 4.5 },
      { name: "text-secondary", use: "보조 설명, 시각, 출처", against: "surface-raised", min: 4.5 },
      { name: "text-tertiary", use: "플레이스홀더, 비활성 글자", against: "surface-raised", min: 4.5 },
      { name: "text-inverse", use: "어두운 바탕 위 글자", against: "text-primary", min: 4.5 },
    ],
  },
  {
    title: "상태",
    items: [
      { name: "up", use: "상승(▲ + 부호와 함께)", against: "surface-raised", min: 4.5 },
      { name: "down", use: "하락(▼ − 부호와 함께)", against: "surface-raised", min: 4.5 },
      { name: "warning", use: "원문 대조 필요 같은 확인 요청", against: "surface-sunken", min: 4.5 },
      { name: "error", use: "오류, 입력 오류 문장", against: "surface-sunken", min: 4.5 },
    ],
  },
  {
    title: "그래프",
    items: [
      { name: "graph-node-issue", use: "사건 노드 범주색(원 + 번개 아이콘)", against: "surface-base", min: 3 },
      { name: "graph-node-glyph", use: "사건 노드 안 아이콘", against: "graph-node-issue", min: 3 },
      { name: "graph-node-mark", use: "보유·관심 기업 노드의 3px 바깥 테두리", against: "surface-base", min: 3 },
      { name: "graph-company-fallback-1", use: "상징색 없는 기업 폴백 1~8(company_id 해시). 두 테마 모두 흰 이니셜과 4.9:1 이상" },
      { name: "graph-company-fallback-2", use: "폴백 2" },
      { name: "graph-company-fallback-3", use: "폴백 3" },
      { name: "graph-company-fallback-4", use: "폴백 4" },
      { name: "graph-company-fallback-5", use: "폴백 5" },
      { name: "graph-company-fallback-6", use: "폴백 6" },
      { name: "graph-company-fallback-7", use: "폴백 7" },
      { name: "graph-company-fallback-8", use: "폴백 8" },
      { name: "graph-focus-ring", use: "선택한 노드의 실선 링", against: "surface-base", min: 3 },
      { name: "graph-edge-involves", use: "직접 관련 선", against: "surface-base", min: 3 },
      { name: "graph-edge-structurally-related", use: "구조적 관련 선", against: "surface-base", min: 3 },
      { name: "graph-edge-follows", use: "후속 사건 선", against: "surface-base", min: 3 },
      { name: "graph-edge-shares-issue", use: "사건 공유(파생) 선. 일부러 흐리게 둬요", against: "surface-base", min: 3 },
      { name: "graph-edge-label", use: "선 가운데 관계 요약 글자", against: "surface-base", min: 4.5 },
    ],
  },
];

function Swatch({ hex }: { hex: string }) {
  return <span className="size-4 shrink-0 border border-border-strong" style={{ background: hex }} aria-hidden="true" />;
}

function ContrastCell({ spec }: { spec: ColorSpec }) {
  if (!spec.against || !spec.min) return <span className="text-text-secondary">바탕·구분선이라 기준 없음</span>;
  const light = contrast(hexOf(spec.name, "light"), hexOf(spec.against, "light"));
  const dark = contrast(hexOf(spec.name, "dark"), hexOf(spec.against, "dark"));
  const pass = light !== null && dark !== null && light >= spec.min && dark >= spec.min;
  return (
    <span className="flex flex-col gap-1">
      <span className="text-text-primary">
        {light?.toFixed(2)} · {dark?.toFixed(2)}
      </span>
      <span className="text-text-secondary">
        {spec.against} 위, 기준 {spec.min}:1 {pass ? "통과" : "미달"}
      </span>
    </span>
  );
}

function ColorTable() {
  return (
    <TableScroll label="색 토큰 표">
      <table className="w-full min-w-[640px] border-collapse text-sm">
        <caption className="sr-only">색 토큰의 라이트·다크 값과 명도 대비</caption>
        <thead>
          <tr>
            <th scope="col" className={cn(th, "w-[34%]")}>
              이름
            </th>
            <th scope="col" className={th}>
              라이트
            </th>
            <th scope="col" className={th}>
              다크
            </th>
            <th scope="col" className={th}>
              대비 (라이트 · 다크)
            </th>
          </tr>
        </thead>
        {colorGroups.map((group) => (
          <tbody key={group.title}>
            <tr>
              <th scope="colgroup" colSpan={4} className="px-3 pt-6 pb-2 text-left text-base font-semibold text-text-primary">
                {group.title}
              </th>
            </tr>
            {group.items.map((spec) => (
              <tr key={spec.name}>
                <th scope="row" className={cn(td, "text-left font-normal")}>
                  <code className="font-mono text-sm break-all text-text-primary">{spec.name}</code>
                  <span className="mt-1 block text-text-secondary">{spec.use}</span>
                </th>
                {(["light", "dark"] as const).map((theme) => (
                  <td key={theme} className={td}>
                    <span className="flex items-center gap-2">
                      <Swatch hex={hexOf(spec.name, theme)} />
                      <code className="font-mono text-sm text-text-primary">{hexOf(spec.name, theme)}</code>
                    </span>
                  </td>
                ))}
                <td className={td}>
                  <ContrastCell spec={spec} />
                </td>
              </tr>
            ))}
          </tbody>
        ))}
      </table>
    </TableScroll>
  );
}

// ---------- 글꼴

const typeScale = [
  { token: "text-2xl", size: "28px", weight: "Bold 700", className: "text-2xl font-bold", sample: "내 종목 지도", use: "화면 대표 제목. 화면에 한 번만 써요." },
  { token: "text-xl", size: "22px", weight: "Semibold 600 · Bold 700", className: "text-xl font-semibold", sample: "예시전자 2분기 실적 발표", use: "패널·다이얼로그 제목, 주요 수치" },
  { token: "text-lg", size: "18px", weight: "Semibold 600", className: "text-lg font-semibold", sample: "관련 사건", use: "섹션 제목, 기업명" },
  { token: "text-md", size: "16px", weight: "Regular 400 · Medium 500", className: "text-md", sample: "관심 종목을 검색해 보세요", use: "모바일 본문, 입력창(아이폰 확대 방지)" },
  { token: "text-base", size: "15px", weight: "Regular 400", className: "text-base", sample: "예시전자는 2분기 메모리 실적을 발표했어요.", use: "데스크톱 본문, 목록 행" },
  { token: "text-sm", size: "13px", weight: "Regular 400", className: "text-sm", sample: "예시일보 · 2026.07.10 09:20", use: "출처, 시각, 고지. 이보다 작은 글자는 쓰지 않아요." },
];

const numberSamples = ["1,111.11", "88,888.80", "+12.30%"];

// ---------- 형태·간격

const radiusRules = [
  { token: "rounded-none", value: "0px", radius: "0px", on: "목록 행, 섹션, 패널 안 항목, 표, 지도 캔버스", off: "버튼, 팝오버" },
  { token: "rounded-sm", value: "8px", radius: "8px", on: "버튼, 입력창, 세그먼트 선택 배경", off: "카드 틀, 목록 행" },
  { token: "rounded-lg", value: "16px", radius: "16px", on: "바텀시트 위 모서리, 다이얼로그, 토스트, 팝오버", off: "일반 패널, 안쪽 항목" },
  { token: "rounded-full", value: "9999px", radius: "9999px", on: "원형 조작 버튼, 스위치 손잡이, 기업 노드", off: "상태 배지, 목록 항목" },
];

const spacingUse: Record<string, string> = {
  "1": "아이콘과 글자 사이",
  "2": "배지·버튼끼리",
  "3": "목록 행 위아래",
  "4": "모바일 화면 좌우, 행 좌우",
  "6": "데스크톱 화면 좌우",
  "8": "묶음과 묶음 사이",
  "10": "섹션 사이",
  "12": "앱 바 높이, 행 최소 높이",
};

// ---------- 예시 데이터 (정적)

const exampleEvidence = [
  {
    id: "ex-1",
    quote: "예시전자는 2분기 메모리 실적을 7월 10일 발표했다.",
    quoteVerified: true,
    article: { title: "예시전자, 2분기 실적 발표", publisher: "예시일보", url: null, publishedAt: "2026-07-10T00:20:00Z", synthetic: true },
  },
  {
    id: "ex-2",
    quote: "예시전자는 4월 11일 예시공장 가동을 중단했다.",
    quoteVerified: null,
    article: { title: "예시공장 가동 중단", publisher: "예시경제", url: null, publishedAt: null, synthetic: true },
  },
] satisfies Pick<Schemas["EvidenceResponse"], "id" | "quote" | "quoteVerified" | "article">[];

function exampleNode(id: string, kind: "company" | "issue", label: string, extra: Partial<Schemas["GraphNode"]> = {}): Schemas["GraphNode"] {
  return { id, kind, label, isFocus: false, holding: false, watch: false, brandColor: null, logoUrl: null, eventTime: null, timePrecision: null, action: null, target: null, evidenceCount: kind === "issue" ? 1 : null, ...extra };
}

function exampleEdge(id: string, source: string, target: string, relationType: RelationType, summary: string, evidenceIds: string[] = []): Schemas["GraphEdge"] {
  return { id, source, target, relationType, summary, role: null, assertionStatus: null, derived: relationType === "SHARES_ISSUE", via: [], evidenceIds };
}

const demoNodes = [
  exampleNode("a", "company", "예시전자", { isFocus: true, watch: true, brandColor: "#1F4E9E" }),
  exampleNode("b", "company", "예시반도체", { holding: true }),
  exampleNode("c", "company", "예시소재"),
  exampleNode("i1", "issue", "예시: 2분기 실적 발표", { action: "실적 발표", eventTime: "2026-07-10", timePrecision: "day" }),
  exampleNode("i2", "issue", "예시: 공장 가동 중단", { action: "가동 중단", evidenceCount: 2 }),
  exampleNode("i3", "issue", "예시: 가동 재개 보도", { action: "가동 재개" }),
  // 연결이 없는 예시 사건 2건: 그래프에서는 묶음 노드 하나로 모인다.
  exampleNode("i4", "issue", "예시: 신제품 공개", { action: "신제품 공개" }),
  exampleNode("i5", "issue", "예시: 인사 발표", { action: "인사 발표" }),
];
const demoEdges = [
  exampleEdge("e1", "i1", "a", "INVOLVES", "발표자", ["ex-1"]),
  exampleEdge("e2", "i1", "b", "INVOLVES", "직접 관련"),
  exampleEdge("e3", "i2", "c", "STRUCTURALLY_RELATED_TO", "공급 계약 상대 기업(예시 설명이 긴 요약)", ["ex-2"]),
  exampleEdge("e4", "i2", "i3", "FOLLOWS", "후속 사건"),
  exampleEdge("e5", "i3", "a", "INVOLVES", "대상 기업"),
  exampleEdge("e6", "a", "b", "SHARES_ISSUE", "같은 사건 1건"),
];
/** 예시전자 → 예시소재: 사건 공유(파생) 선은 건너뛰고 사건 두 개를 거치는 3단계 경로 */
const demoPath = shortestPath(demoNodes, demoEdges, "a", "c");

/** 큰 지도(라벨 LOD·성능 확인용): 예시 기업 40곳, 사건 110건. 같은 입력이면 항상 같은 모양. */
function bigDemo() {
  const companies = Array.from({ length: 40 }, (_, i) => exampleNode(`bc${i}`, "company", `예시기업 ${i + 1}`));
  const issues = Array.from({ length: 110 }, (_, i) => exampleNode(`bi${i}`, "issue", `예시 사건 ${i + 1}`, { action: `예시 사건 ${i + 1}` }));
  const edges: Schemas["GraphEdge"][] = [];
  issues.forEach((issue, i) => {
    edges.push(exampleEdge(`be${i}a`, issue.id, companies[(i * 7) % 40]!.id, "INVOLVES", "직접 관련"));
    if (i % 3 === 0) edges.push(exampleEdge(`be${i}b`, issue.id, companies[(i * 11 + 5) % 40]!.id, "STRUCTURALLY_RELATED_TO", "공급"));
    if (i % 5 === 0 && i > 0) edges.push(exampleEdge(`be${i}c`, issues[i - 1]!.id, issue.id, "FOLLOWS", "후속 사건"));
  });
  return { nodes: [...companies, ...issues], edges };
}
const bigGraph = bigDemo();

const edgeRules: { type: RelationType; shape: string; approved: boolean }[] = [
  { type: "INVOLVES", shape: "2px 실선 + 화살표", approved: true },
  { type: "STRUCTURALLY_RELATED_TO", shape: "2px 파선 + 화살표", approved: true },
  { type: "FOLLOWS", shape: "1.5px 실선 + 화살표", approved: true },
  { type: "SHARES_ISSUE", shape: "1.5px 점선, 방향 없음, 낮은 대비", approved: false },
];

/** 실제 기업 카탈로그(bff/fixtures/poc-real-companies.json)의 표지 네 가지 경우 */
const markExamples = [
  { id: "NASDAQ:NVDA", name: "NVIDIA", brandColor: "#76B900", logoUrl: "/logos/nvidia.svg", note: "상징색 + 로고" },
  { id: "NASDAQ:AMZN", name: "Amazon", brandColor: "#FF9900", logoUrl: null, note: "상징색 + 이니셜(로고 없음)" },
  { id: "KRX:000660", name: "SK하이닉스", brandColor: null, logoUrl: null, note: "폴백 팔레트 + 이니셜" },
  { id: "NASDAQ:AAPL", name: "Apple", brandColor: "#000000", logoUrl: "/logos/apple.svg", note: "어두운 상징색: 다크 테마에서 윤곽선" },
];

const iconRules: { icon: LucideIcon; name: string; meaning: string }[] = [
  { icon: MapIcon, name: "Map", meaning: "지도 탭" },
  { icon: Newspaper, name: "Newspaper", meaning: "브리핑 탭, 보도 기사 수" },
  { icon: Bookmark, name: "Bookmark", meaning: "내 종목 탭" },
  { icon: Globe, name: "Globe", meaning: "시장 전체 모드" },
  { icon: Star, name: "Star", meaning: "관심 종목(모드·배지·섹션)" },
  { icon: Wallet, name: "Wallet", meaning: "내 자산·보유 종목" },
  { icon: Building2, name: "Building2", meaning: "기업(범례·섹션)" },
  { icon: Zap, name: "Zap", meaning: "사건(노드·범례·섹션). 앱 전체에서 사건은 번개" },
  { icon: Link2, name: "Link2", meaning: "지도의 연결·연결된 두 대상" },
  { icon: FileText, name: "FileText", meaning: "근거 문서" },
  { icon: ShieldCheck, name: "ShieldCheck", meaning: "데이터 출처: 실제 기사(검증 통과)" },
  { icon: FlaskConical, name: "FlaskConical", meaning: "데이터 출처: 합성 데이터" },
  { icon: Sparkles, name: "Sparkles", meaning: "AI가 만든 글" },
  { icon: MessageCircleQuestion, name: "MessageCircleQuestion", meaning: "AI에게 묻기, 추천 질문" },
  { icon: CalendarClock, name: "CalendarClock", meaning: "발행 시각 미확정" },
  { icon: Clock, name: "Clock", meaning: "기준 시각" },
  { icon: Info, name: "Info", meaning: "관계 유형·편성 기준 설명(누르면 팝오버)" },
  { icon: ArrowUpRight, name: "ArrowUpRight", meaning: "기업 상세로 이동" },
];

const motionUses: Record<string, string> = {
  "duration.fast": "호버·눌림 색 전환, 눌림 축소, 팝오버·툴팁 등장",
  "duration.d4": "세그먼트 선택 표시가 미끄러질 때",
  "duration.exit": "시트·다이얼로그·토스트 퇴장",
  "duration.normal": "화면 전환, 시트·다이얼로그·토스트 진입, 탭 밑줄 이동, 목록 첫 표시",
  "duration.slow": "데스크톱 오른쪽 시트 진입, 그래프 선택 시 카메라 이동",
  "duration.graph-layout": "그래프 초기 배치·모드 전환 재배치",
  "duration.stagger": "목록 행 사이 지연(8행까지)",
  "easing.standard": "제자리 이동(세그먼트·탭 표시, 그래프 카메라), 색 전환",
  "easing.enter": "나타날 때, 눌림 축소",
  "easing.exit": "사라질 때",
  "easing.enter-expressive": "그래프 노드가 퍼져 나오는 첫 배치",
};

const datasetKinds: DatasetKind[] = ["approved-live", "approved-snapshot", "synthetic-preview"];

// ---------- 라이팅·체크리스트

const writingRules = [
  { rule: "해요체로 써요", bad: "확인되었습니다", good: "확인했어요" },
  { rule: "해야 할 일을 긍정형으로", bad: "기업이 선택되지 않았습니다", good: "기업을 골라 주세요" },
  { rule: "없어도 뜻이 통하는 말은 빼요", bad: "해당 기능을 이용하시려면 로그인을 진행해 주시기 바랍니다", good: "로그인하면 쓸 수 있어요" },
  { rule: "기술 사정은 설명하지 않아요", bad: "브라우저 저장소를 초기화해요", good: "(문장을 쓰지 않아요)" },
  { rule: "버튼에는 누른 뒤 결과를 적어요", bad: "확인", good: "내 종목 지도 보기" },
  { rule: "오류는 상황 + 이유 + 해결책", bad: "오류가 발생했습니다", good: "네트워크 연결이 불안정해요. 잠시 후 다시 시도해 주세요." },
  { rule: "창을 닫는 버튼은 [닫기]", bad: "취소", good: "닫기" },
];

const bannedWords = [
  { bad: "무조건 상승, 급등 예상", why: "이익을 보장하는 것처럼 읽혀요", good: "관련 사건이 보도됐어요" },
  { bad: "지금이 매수 타이밍", why: "매매를 권하는 말이에요", good: "관련 보도를 확인해 보세요" },
  { bad: "목표가, 상승 확률 85%", why: "없는 수치를 지어낸 거예요", good: "(값이 없으면 그 자리를 그리지 않아요)" },
  { bad: "~때문에 주가가 올랐다", why: "원인을 단정해요", good: "~ 이후 함께 보도됐어요" },
  { bad: "국내 1위, 최고의 종목", why: "근거 없는 최상급이에요", good: "기준을 함께 적어요 (예: 시가총액 기준)" },
  { bad: "BFF, PoC, Mock", why: "개발 내부 용어예요", good: "화면에 쓰지 않아요" },
  { bad: "announced", why: "내부 상태값이에요", good: "보도 언급" },
  { bad: "Node, Edge", why: "개발 용어예요", good: "기업·사건, 연결" },
];

const slopChecklist = [
  "카드 안에 카드를 넣지 않았나요? 행과 구분선으로 펼쳐요.",
  "한 요소에 테두리와 그림자를 같이 주지 않았나요?",
  "카드·패널 왼쪽에 두꺼운 색 줄을 긋지 않았나요?",
  "아이콘을 둥근 상자 안에 가두지 않았나요? 아이콘은 글자 옆에 그대로 둬요.",
  "지도나 배경에 뜻 없는 점·격자 무늬를 깔지 않았나요?",
  "다크 테마 노드·버튼 주위에 번지는 빛(글로우)을 넣지 않았나요?",
  "제목 위에 '방식 1' 같은 알약 라벨을 달지 않았나요?",
  "390px 화면에서 가로 스크롤이 생기지 않나요? (scrollWidth ≤ 390)",
  "아이콘만 있는 컨트롤에 aria-label과 툴팁이 있나요?",
  "‘준비 중’, ‘합성 데이터’ 같은 메타 문구를 글자로 늘어놓지 않았나요? 없는 값은 자리를 빼고, 출처는 아이콘으로.",
  "개발 내부 용어가 화면에 보이지 않나요?",
  "데이터에 없는 시세, 상승 확률, 감성 점수를 지어내지 않았나요?",
  "튜토리얼이 대상을 덮지 않나요? 패널은 목록 자리·지도 위 흐름에 두고, 대상은 점선 테두리로만 가리켜요. 직접 해 보면 넘어가고 [다음]·[건너뛰기]는 늘 있어요.",
];

// ---------- 페이지

export function DesignSystemPage() {
  const toast = useToast();
  const [active, setActive] = useState(toc[0]!.id);
  const [search, setSearch] = useState("예시");
  const [period, setPeriod] = useState("1w");
  const [view, setView] = useState<"map" | "list">("map");
  const [dialogOpen, setDialogOpen] = useState(false);
  const [sheetOpen, setSheetOpen] = useState(false);
  const [bottomSheetOpen, setBottomSheetOpen] = useState(false);
  const [rowSelected, setRowSelected] = useState("a");
  const [mode, setMode] = useState<GraphMode>("personal");
  const [selection, setSelection] = useState<GraphSelection | null>({ kind: "node", id: "a" });
  const [graphSize, setGraphSize] = useState<"small" | "big">("small");
  const [legendHidden, setLegendHidden] = useState<ReadonlySet<LegendKey>>(() => new Set());
  const [demoFocus, setDemoFocus] = useState<GraphFocus | null>(null);
  const [demoPathOn, setDemoPathOn] = useState(false);
  const [demoEvidence, setDemoEvidence] = useState<string | null>(null);
  const toggleLegend = (key: LegendKey) =>
    setLegendHidden((prev) => {
      const next = new Set(prev);
      if (next.has(key)) next.delete(key);
      else next.add(key);
      return next;
    });
  const [staggerKey, setStaggerKey] = useState(0);
  const demoGraph = graphSize === "small" ? { nodes: demoNodes, edges: demoEdges } : bigGraph;

  // 목차에서 지금 보고 있는 절을 표시한다: 화면 위쪽 기준선(140px)을 지난 마지막 절.
  useEffect(() => {
    let frame = 0;
    const update = () => {
      frame = 0;
      let current = toc[0]!.id;
      for (const item of toc) {
        const el = document.getElementById(item.id);
        if (el && el.getBoundingClientRect().top <= 140) current = item.id;
      }
      // 맨 아래까지 내렸으면 짧은 마지막 절이 기준선에 닿지 못해도 마지막 절로 본다.
      if (window.innerHeight + window.scrollY >= document.documentElement.scrollHeight - 2) current = toc[toc.length - 1]!.id;
      setActive(current);
    };
    const onScroll = () => {
      if (!frame) frame = requestAnimationFrame(update);
    };
    update();
    window.addEventListener("scroll", onScroll, { passive: true });
    return () => {
      window.removeEventListener("scroll", onScroll);
      cancelAnimationFrame(frame);
    };
  }, []);

  const jumpTo = (id: string) => {
    setActive(id);
    document.getElementById(id)?.scrollIntoView({ block: "start" });
  };

  return (
    <div className="mx-auto flex w-full max-w-[1280px] gap-12 px-4 pt-6 pb-16 md:px-6 md:pt-10">
      <nav aria-label="디자인시스템 목차" className="sticky top-20 hidden h-fit w-48 shrink-0 lg:block">
        <ul className="flex flex-col">
          {toc.map((item) => (
            <li key={item.id}>
              <a
                href={`#${item.id}`}
                aria-current={active === item.id ? "location" : undefined}
                className={cn(
                  "flex min-h-11 items-center rounded-sm px-3 text-base text-text-secondary transition-token hover:bg-surface-sunken hover:text-text-primary",
                  active === item.id && "bg-surface-selected font-semibold text-brand-primary hover:bg-surface-selected hover:text-brand-primary",
                )}
              >
                {item.label}
              </a>
            </li>
          ))}
        </ul>
      </nav>

      <div className="flex min-w-0 flex-1 flex-col gap-10">
        <header className="flex max-w-prose flex-col gap-3">
          <h1 className="text-2xl font-bold text-text-primary">줍 디자인시스템</h1>
          <p className="text-md text-text-secondary">
            화면을 만들 때 쓰는 색, 글꼴, 간격과 컴포넌트를 모았어요. 아래 컴포넌트는 앱 코드 그대로이고, 기업·기사 내용은 모두 예시예요. 라이트와 다크는
            오른쪽 위 테마 버튼으로 바꿔 보세요.
          </p>
        </header>

        <div className="sticky top-12 z-10 -mx-4 border-b border-border-subtle bg-surface-base px-4 py-2 md:top-14 md:-mx-6 md:px-6 lg:hidden">
          <Select label="목차로 이동" hideLabel value={active} onValueChange={jumpTo} options={toc.map((t) => ({ value: t.id, label: t.label }))} className="w-full" />
        </div>

        <Section id="principles" title="원칙">
          <ol className="flex max-w-prose list-decimal flex-col gap-3 pl-5 text-base text-text-primary marker:text-text-secondary">
            <li>근거가 먼저예요. 기사 인용과 출처 없이 주장하지 않아요.</li>
            <li>없는 값은 지어내지 않아요. 시세·감성·AI 요약이 없으면 그 자리를 아예 그리지 않아요(‘준비 중’ 글자도 쓰지 않아요).</li>
            <li>색만으로 뜻을 전하지 않아요. 부호, 선 모양, 글자를 함께 써요.</li>
            <li>화면 대부분은 회색이에요. 브랜드 색은 주 행동 버튼 1개와 선택 상태에, 기업 상징색은 지도 노드와 기업 표지에만 써요.</li>
            <li>상자를 겹치지 않아요. 행, 구분선, 여백으로 묶어요.</li>
            <li>메타 문구는 글자 대신 아이콘으로. 설명이 필요하면 아이콘을 누르면 열려요(툴팁 + 팝오버).</li>
          </ol>
        </Section>

        <Section
          id="colors"
          title="색"
          description="Tailwind 클래스는 용도 뒤에 토큰 이름을 붙여요(bg-surface-raised, text-text-secondary). 대비는 글자 4.5:1, 선·테두리 3:1 이상이면 통과예요."
        >
          <ColorTable />
          <p className="max-w-prose text-sm text-text-secondary">
            그래프 노드를 흐리게 할 때는 색 대신 불투명도 0.22(graph-dimmed-opacity)를 써요. 값의 원본은 docs/design/tokens.json이에요.
          </p>
        </Section>

        <Section id="typography" title="글꼴" description="SUIT Variable 한 가지만 써요. 크기는 6단계뿐이고, 제목과 본문은 크기와 굵기 차이로 구분해요.">
          <ul className="flex flex-col">
            {typeScale.map((t) => (
              <li key={t.token} className="flex flex-col gap-1 border-b border-border-subtle py-4 md:flex-row md:items-baseline md:gap-6">
                <span className="flex shrink-0 flex-col text-sm text-text-secondary md:w-52">
                  <code className="font-mono text-text-primary">
                    {t.token} · {t.size}
                  </code>
                  <span>{t.weight}</span>
                </span>
                <span className="flex min-w-0 flex-col gap-1">
                  <span className={cn(t.className, "break-keep text-text-primary")}>{t.sample}</span>
                  <span className="text-sm text-text-secondary">{t.use}</span>
                </span>
              </li>
            ))}
          </ul>
          <ul className="flex max-w-prose list-disc flex-col gap-2 pl-5 text-base text-text-primary marker:text-text-secondary">
            <li>본문 한 줄은 한글 40자 안팎에서 끊어요(max-w-prose). 너무 길면 다음 줄을 찾기 어려워요.</li>
            <li>굵기는 4가지만 써요. 본문 400, 강조 500, 제목 600, 화면 제목 700.</li>
            <li>13px보다 작은 글자는 쓰지 않아요. 출처와 고지도 13px이에요.</li>
          </ul>
          <div className="flex flex-col gap-3">
            <h3 className="text-lg font-semibold text-text-primary">숫자는 자릿수를 맞춰요 (tnum)</h3>
            <p className="max-w-prose text-base text-text-secondary">
              가격·등락률·날짜에는 고정폭 숫자(tabular-nums)를 켜요. 앱 전체에 기본으로 켜져 있어서, 숫자가 바뀌어도 폭이 흔들리지 않아요.
            </p>
            <div className="grid max-w-md grid-cols-2 gap-6 text-lg text-text-primary">
              <div className="flex flex-col items-end gap-1 [font-variant-numeric:proportional-nums]">
                <span className="self-start text-sm text-text-secondary">끔</span>
                {numberSamples.map((n) => (
                  <span key={n}>{n}</span>
                ))}
              </div>
              <div className="flex flex-col items-end gap-1 tabular-nums">
                <span className="self-start text-sm text-text-secondary">켬 (기본)</span>
                {numberSamples.map((n) => (
                  <span key={n}>{n}</span>
                ))}
              </div>
            </div>
            <p className="max-w-prose text-sm text-text-secondary">
              글꼴 순서: <code className="font-mono break-all">{fontFamilyTokens.find((f) => f.name === "sans")?.value}</code>. SUIT에 없는 드문
              한글은 뒤의 시스템 글꼴로 보여요.
            </p>
          </div>
        </Section>

        <Section id="shape" title="형태" description="둥근 모서리는 누를 수 있는 컨트롤과 떠 있는 면에만 줘요. 목록과 섹션은 각지게 두고 구분선으로 나눠요.">
          <ul className="flex flex-col">
            {radiusRules.map((r) => (
              <li key={r.token} className="flex items-start gap-4 border-b border-border-subtle py-4">
                <span className="size-12 shrink-0 border-2 border-border-strong bg-surface-sunken" style={{ borderRadius: r.radius }} aria-hidden="true" />
                <span className="flex min-w-0 flex-col gap-1 text-base">
                  <code className="font-mono text-sm text-text-primary">
                    {r.token} · {r.value}
                  </code>
                  <span className="text-text-primary">{r.on}</span>
                  <span className="text-sm text-text-secondary">쓰지 않는 곳: {r.off}</span>
                </span>
              </li>
            ))}
          </ul>
          <ul className="flex max-w-prose list-disc flex-col gap-2 pl-5 text-base text-text-primary marker:text-text-secondary">
            <li>그림자는 시트, 다이얼로그, 팝오버, 토스트처럼 떠 있는 면에만 줘요. 그림자를 준 면에는 테두리를 같이 주지 않아요.</li>
            <li>16px 시트 안의 버튼은 8px을 유지해요. 안쪽 모서리가 바깥보다 둥글면 어색해 보여요.</li>
          </ul>
        </Section>

        <Section id="spacing" title="간격" description="간격은 4px 단위예요. Tailwind에서 p-4는 16px(4 × 4px)이에요. 누르는 영역은 항상 44×44px 이상이에요.">
          <ul className="flex flex-col">
            {spacingTokens
              .filter((t) => t.name !== "0")
              .map((t) => (
                <li key={t.name} className="grid grid-cols-[4.5rem_1fr] items-center gap-x-4 gap-y-1 border-b border-border-subtle py-2 sm:grid-cols-[4.5rem_4rem_1fr]">
                  <code className="font-mono text-sm text-text-primary">
                    {t.name} · {t.value}
                  </code>
                  <span className="h-3 bg-border-strong" style={{ width: t.value }} aria-hidden="true" />
                  <span className="col-span-2 text-sm text-text-secondary sm:col-span-1">{spacingUse[t.name] ?? ""}</span>
                </li>
              ))}
          </ul>
        </Section>

        <Section id="components" title="기본 컴포넌트" description="어느 화면에서나 쓰는 부품이에요. 새 화면을 만들 때 직접 스타일을 쓰기 전에 여기서 먼저 찾아요.">
          <Demo
            id="c-button"
            name="Button"
            when="한 번의 행동을 실행해요. 글자에는 누른 뒤 결과를 적어요. primary는 화면에 하나만 두니, 이 페이지의 primary도 아래 하나뿐이에요."
            code={'<Button variant="secondary" onClick={openEvidence}>근거 보기</Button>'}
          >
            <StateRow label="종류">
              <Button onClick={() => toast({ title: "예시: 관심 종목을 저장했어요", tone: "success" })}>관심 종목 저장하기</Button>
              <Button variant="secondary" onClick={() => setSheetOpen(true)}>
                근거 보기
              </Button>
              <Button variant="ghost" onClick={() => toast({ title: "예시: 지도 설정을 열었어요" })}>
                지도 설정
              </Button>
              <Button variant="link" onClick={() => toast({ title: "예시: 원문 링크예요" })}>
                원문 열기
              </Button>
            </StateRow>
            <StateRow label="상태">
              <Button variant="secondary" disabled>
                비활성
              </Button>
              <Button variant="secondary" loading>
                저장하는 중
              </Button>
              <Tooltip content="지도 보기 설정">
                <Button variant="secondary" size="icon" aria-label="지도 보기 설정" onClick={() => toast({ title: "예시: 지도 설정을 열었어요" })}>
                  <SlidersHorizontal aria-hidden="true" />
                </Button>
              </Tooltip>
            </StateRow>
            <StateRow label="크기">
              <Button variant="secondary" size="sm">
                작게
              </Button>
              <Button variant="secondary" size="md">
                보통
              </Button>
              <Button variant="secondary" size="lg">
                크게
              </Button>
            </StateRow>
          </Demo>

          <Demo id="c-input" name="Input" when="검색어와 질문을 받아요. 라벨은 항상 연결하고(숨겨도 돼요), 오류는 빨간 테두리와 함께 문장으로 알려요." code={'<Input label="종목 검색" variant="search" value={q} onChange={…} onClear={…} />'}>
            <div className="grid max-w-3xl gap-4 sm:grid-cols-2">
              <Input label="기본" placeholder="예시전자" hint="기업 이름이나 종목 코드를 입력해요" />
              <Input label="검색" variant="search" value={search} onChange={(e) => setSearch(e.target.value)} onClear={() => setSearch("")} />
              <Input label="오류" defaultValue="" error="관심 종목을 1개 이상 골라 주세요." />
              <Input label="비활성" disabled placeholder="입력할 수 없어요" />
            </div>
          </Demo>

          <Demo id="c-select" name="Select" when="선택지가 5개 이상일 때 써요. 2~4개면 Segmented가 더 빨라요." code={'<Select label="기간" value={period} onValueChange={setPeriod} options={periods} />'}>
            <div className="flex flex-wrap gap-4">
              <Select
                label="기간"
                value={period}
                onValueChange={setPeriod}
                options={[
                  { value: "1d", label: "1일" },
                  { value: "1w", label: "1주일" },
                  { value: "1m", label: "1개월" },
                  { value: "3m", label: "3개월" },
                  { value: "1y", label: "1년" },
                ]}
              />
              <Select label="비활성" value="all" onValueChange={() => undefined} options={[{ value: "all", label: "전체" }]} disabled />
            </div>
          </Demo>

          <Demo
            id="c-segmented"
            name="Segmented"
            when="같은 내용을 보는 방식을 바꿔요(지도 ↔ 목록). 아래 내용 영역이 따로 없어요. 선택 표시는 고른 칸으로 미끄러져요(200ms). 못 쓰는 선택지는 이유를 알려줘요."
            code={'<Segmented aria-label="보기 방식" value={view} onValueChange={setView} options={[…]} />'}
          >
            <StateRow label="기본">
              <Segmented
                aria-label="보기 방식"
                value={view}
                onValueChange={setView}
                options={[
                  { value: "map", label: <><Network aria-hidden="true" />지도</>, ariaLabel: "지도" },
                  { value: "list", label: <><FileText aria-hidden="true" />목록</>, ariaLabel: "목록" },
                ]}
              />
            </StateRow>
            <StateRow label="비활성">
              <GraphModeSwitch value="all" onValueChange={() => undefined} disabledModes={{ personal: "로그인하면 쓸 수 있어요" }} />
            </StateRow>
          </Demo>

          <Demo id="c-tabs" name="Tabs" when="같은 대상의 다른 내용을 나눠 보여줘요. 최대 4개, 폭을 똑같이 나눠요. 밑줄은 고른 탭으로 미끄러지고, 좌우 방향키로 옮겨요." code={'<Tabs defaultValue="events"><TabsList>…</TabsList><TabsContent value="events">…</TabsContent></Tabs>'}>
            <Tabs defaultValue="events" className="max-w-md">
              <TabsList>
                <TabsTrigger value="events">관련 사건</TabsTrigger>
                <TabsTrigger value="relations">연결</TabsTrigger>
                <TabsTrigger value="ask" disabled>
                  AI에게 묻기
                </TabsTrigger>
              </TabsList>
              <TabsContent value="events" className="pt-3 text-base">
                예시전자와 연결된 사건 3건이 여기에 보여요.
              </TabsContent>
              <TabsContent value="relations" className="pt-3 text-base">
                예시전자와 이어진 기업 2곳이 여기에 보여요.
              </TabsContent>
            </Tabs>
          </Demo>

          <Demo
            id="c-dialog"
            name="Dialog · Sheet · BottomSheet"
            when="Dialog는 짧은 확인, Sheet는 근거처럼 긴 내용이에요. Sheet는 데스크톱에서 오른쪽 패널, 모바일에서 자동으로 BottomSheet가 돼요. Esc나 [닫기]로 닫고, 닫으면 연 버튼으로 포커스가 돌아와요."
            code={'<Sheet open={open} onOpenChange={setOpen} title="근거" closeLabel="근거 창 닫기">…</Sheet>'}
          >
            <div className="flex flex-wrap gap-3">
              <Button variant="secondary" onClick={() => setDialogOpen(true)}>
                Dialog 열기
              </Button>
              <Button variant="secondary" onClick={() => setSheetOpen(true)}>
                Sheet 열기
              </Button>
              <Button variant="secondary" onClick={() => setBottomSheetOpen(true)}>
                BottomSheet 열기
              </Button>
            </div>
            <Dialog
              open={dialogOpen}
              onOpenChange={setDialogOpen}
              title="관심 종목에서 뺄까요?"
              description="예시전자를 관심 종목에서 빼요. 지도에서 다시 추가할 수 있어요."
              closeLabel="닫기"
              footer={
                <div className="flex justify-end gap-2">
                  <Button variant="secondary" onClick={() => setDialogOpen(false)}>
                    닫기
                  </Button>
                  <Button
                    onClick={() => {
                      setDialogOpen(false);
                      toast({ title: "예시: 예시전자를 관심 종목에서 뺐어요" });
                    }}
                  >
                    예시전자 빼기
                  </Button>
                </div>
              }
            >
              <p className="text-base text-text-secondary">예시 창이에요. 창이 열린 동안 포커스는 창 안에만 머물러요.</p>
            </Dialog>
            <Sheet open={sheetOpen} onOpenChange={setSheetOpen} title="예시 근거 2건" description="예시전자 2분기 실적 발표" closeLabel="근거 창 닫기">
              <EvidenceList items={exampleEvidence} />
            </Sheet>
            <BottomSheet
              open={bottomSheetOpen}
              onOpenChange={setBottomSheetOpen}
              title="예시전자"
              description="손잡이를 끌거나 ↑/↓로 높이를 바꿔 보세요."
              closeLabel="기업 상세 닫기"
              defaultSnap="half"
            >
              <ul>
                {["예시: 2분기 실적 발표", "예시: 가동 재개 보도", "예시: 공장 가동 중단"].map((title, i) => (
                  <li key={title}>
                    <ListRow title={title} description={`2026.07.${String(10 - i * 3).padStart(2, "0")}`} divider="full" />
                  </li>
                ))}
              </ul>
            </BottomSheet>
          </Demo>

          <Demo
            id="c-popover"
            name="Popover · Tooltip"
            when="Popover는 눌러서 여는 짧은 설명이라 터치에서도 돼요. Tooltip은 마우스를 올리거나 포커스할 때만 보여서, 꼭 필요한 정보는 넣지 않아요."
            code={'<Popover label="사건 공유 설명" trigger={<Button variant="link">사건 공유가 뭔가요?</Button>}>…</Popover>'}
          >
            <div className="flex flex-wrap items-center gap-3">
              <Popover label="사건 공유 설명" align="start" trigger={<Button variant="secondary">사건 공유가 뭔가요?</Button>}>
                <p className="max-w-xs text-base">{relationDescription.SHARES_ISSUE}</p>
              </Popover>
              <Tooltip content="같은 사건 보도에 함께 나온 기업이에요">
                <Button variant="ghost" onClick={() => toast({ title: "예시: 도움말을 열었어요" })}>
                  마우스를 올려 보세요
                </Button>
              </Tooltip>
            </div>
          </Demo>

          <Demo id="c-toast" name="Toast" when="결과를 한 문장으로 알려요. 3초 뒤 사라지고, 경고는 5초 보여요. 오류는 Toast 말고 ErrorState로 보여줘요." code={'const toast = useToast(); toast({ title: "관심 종목을 저장했어요", tone: "success" })'}>
            <div className="flex flex-wrap gap-3">
              <Button variant="secondary" onClick={() => toast({ title: "예시: 알림 설정을 바꿨어요" })}>
                기본 알림
              </Button>
              <Button variant="secondary" onClick={() => toast({ title: "예시: 관심 종목을 저장했어요", tone: "success" })}>
                성공 알림
              </Button>
              <Button variant="secondary" onClick={() => toast({ title: "다른 곳에서 설정이 바뀌었어요", tone: "warning" })}>
                경고 알림
              </Button>
            </div>
          </Demo>

          <Demo id="c-skeleton" name="Skeleton" when="불러오는 동안 실제 내용과 같은 모양의 자리를 먼저 보여줘서 화면이 흔들리지 않게 해요." code={'<SkeletonRows count={3} label="사건을 불러오는 중이에요" />'}>
            <div className="grid gap-6 md:grid-cols-2">
              <SkeletonRows count={2} label="예시 사건을 불러오는 중이에요" />
              <SkeletonLines lines={3} label="예시 글을 불러오는 중이에요" />
            </div>
          </Demo>

          <Demo id="c-empty" name="EmptyState" when="오류가 아니라 정말 없을 때 써요. 지금 상태 한 문장과 다음 행동을 함께 줘요." code={'<EmptyState title="아직 고른 관심 종목이 없어요" action={<Button …>종목 고르기</Button>} />'}>
            <EmptyState
              title="아직 고른 관심 종목이 없어요"
              description="관심 종목을 고르면 그 기업 주변 사건을 지도로 보여줘요."
              action={
                <Button variant="secondary" onClick={() => toast({ title: "예시: 종목 고르기 화면으로 가요" })}>
                  관심 종목 고르기
                </Button>
              }
            />
          </Demo>

          <Demo
            id="c-error"
            name="ErrorState"
            when="불러오기에 실패했을 때 써요. 빈 목록처럼 보여주면 안 돼요. [다시 시도]를 꼭 넣고, 오류 코드는 [자세히] 안에 둬요."
            code={'<ErrorState error={error} onRetry={refetch} />'}
          >
            <div className="grid gap-6 md:grid-cols-2">
              <ErrorState error={new ApiError(0, "network_error", "")} onRetry={() => toast({ title: "예시: 다시 불러와요" })} />
              <ErrorState error={new ApiError(503, "source_unavailable", "")} title="좁은 자리(compact)" onRetry={() => toast({ title: "예시: 다시 불러와요" })} compact />
            </div>
          </Demo>

          <Demo id="c-badge" name="Badge" when="누를 수 없는 상태 표시예요. 한 행에 1~2개까지만 달고, 누르는 필터는 Button이나 Segmented로 만들어요." code={'<Badge variant="warning">원문 대조 필요</Badge>'}>
            <StateRow label="종류">
              <Badge>보유</Badge>
              <Badge variant="warning">원문 대조 필요</Badge>
              <Badge variant="error">불러오지 못함</Badge>
            </StateRow>
          </Demo>

          <Demo
            id="c-listrow"
            name="ListRow"
            when="카드 대신 쓰는 목록 행이에요. 링크면 to, 같은 화면에서 고르면 onClick, 둘 다 없으면 누를 수 없는 행이에요. <li> 안에 넣어요."
            code={'<li><ListRow leading={<CompanyMark … />} title="예시전자" description="관심 종목" selected onClick={select} /></li>'}
          >
            <ul className="max-w-md">
              {[
                { id: "a", title: "예시전자", description: "관심 종목" },
                { id: "b", title: "예시반도체", description: "보유 종목" },
              ].map((row) => (
                <li key={row.id}>
                  <ListRow
                    leading={<CompanyMark id={row.id} name={row.title} />}
                    title={row.title}
                    description={row.description}
                    selected={rowSelected === row.id}
                    onClick={() => setRowSelected(row.id)}
                  />
                </li>
              ))}
              <li>
                <ListRow title="예시소재" description="누를 수 없는 행" divider="none" />
              </li>
            </ul>
          </Demo>

          <Demo
            id="c-sectionheader"
            name="SectionHeader"
            when="목록의 머리글이에요. 앞에 종류 아이콘을 두고, 설명은 오른쪽 정보 아이콘 안에 넣어요(제목 밑에 설명문을 늘어놓지 않아요)."
            code={'<SectionHeader icon={Zap} title="관련 사건" action={<IconHint icon={Info} label="직접 관련">…</IconHint>} />'}
          >
            <SectionHeader
              as="h3"
              icon={Zap}
              title="관련 사건"
              action={
                <IconHint icon={Info} label={relationLabel.INVOLVES}>
                  <p>{relationDescription.INVOLVES}</p>
                </IconHint>
              }
            />
          </Demo>

          <Demo id="c-appbar" name="AppBar · BottomTabBar" when="모바일(768px 이하) 위아래 고정 바예요. 앱 셸이 이미 쓰고 있어서 화면에서는 따로 넣지 않아요. 아래는 390px 폭 예시예요." code={'<BottomTabBar tabs={[{ to: "/", label: "지도", icon: MapIcon, end: true }, …]} />'}>
            <div className="w-full max-w-[390px] bg-surface-raised">
              <AppBar leading={<span className="text-lg font-bold text-text-primary">줍</span>} title="예시 화면" trailing={<SourceIndicator kind="synthetic-preview" />} />
              <div className="h-24 bg-surface-base" aria-hidden="true" />
              <BottomTabBar
                label="예시 하단 탭"
                className="static z-auto"
                tabs={[
                  { to: ".", label: "지도", icon: MapIcon },
                  { to: "/briefing", label: "브리핑", icon: Newspaper },
                  { to: "/me/stocks", label: "내 종목", icon: Bookmark },
                ]}
              />
            </div>
          </Demo>
        </Section>

        <Section id="domain" title="줍 컴포넌트" description="줍에만 있는 부품이에요. 근거와 출처를 정직하게 보여주고, 없는 값은 지어내지 않아요.">
          <Demo
            id="c-source"
            name="SourceIndicator"
            when="지금 데이터가 실제 기사인지 합성 데이터인지 글자 없이 아이콘 하나로 알려요. 앱 헤더와 근거 창 두 곳에만 둬요. 올리면 툴팁, 누르면 한 문장 설명이 열리고, 스크린리더는 ‘데이터 출처: 합성 데이터’처럼 읽어요."
            code={'<SourceIndicator kind={health.datasetKind} />'}
          >
            <StateRow label="종류">
              {datasetKinds.map((kind) => (
                <SourceIndicator key={kind} kind={kind} />
              ))}
            </StateRow>
            <StateRow label="연결 끊김">
              <SourceIndicator kind={null} offline />
            </StateRow>
            <TableScroll label="데이터 출처 문구">
              <table className="w-full min-w-[480px] border-collapse text-sm">
                <caption className="sr-only">데이터 출처 라벨과 설명</caption>
                <thead>
                  <tr>
                    <th scope="col" className={th}>
                      라벨
                    </th>
                    <th scope="col" className={th}>
                      툴팁·스크린리더 이름
                    </th>
                  </tr>
                </thead>
                <tbody>
                  {datasetKinds.map((kind) => (
                    <tr key={kind}>
                      <th scope="row" className={cn(td, "text-left font-medium whitespace-nowrap text-text-primary")}>
                        데이터 출처: {datasetLabel[kind]}
                      </th>
                      <td className={cn(td, "text-text-secondary")}>{datasetDescription[kind]}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </TableScroll>
          </Demo>

          <Demo
            id="c-iconhint"
            name="IconHint · IconCount"
            when="설명문·부제·메타 라벨 대신 아이콘 하나로 보여줘요. 올리면 툴팁(한 줄), 누르면 팝오버(짧은 설명). 개수 메타는 아이콘 + 숫자예요. 아이콘만 있는 컨트롤은 반드시 aria-label과 툴팁을 가져요."
            code={'<IconHint icon={CalendarClock} label="발행 시각 미확정"><p>예정 시각은 바뀔 수 있어요.</p></IconHint> <IconCount icon={Newspaper} label="보도 기사" count={3} />'}
          >
            <StateRow label="힌트">
              <IconHint icon={CalendarClock} label="발행 시각 미확정">
                <p>예정 시각은 바뀔 수 있어요.</p>
              </IconHint>
              <IconHint icon={Info} label={relationLabel.STRUCTURALLY_RELATED_TO}>
                <p>{relationDescription.STRUCTURALLY_RELATED_TO}</p>
              </IconHint>
            </StateRow>
            <StateRow label="개수">
              <IconCount icon={Newspaper} label="보도 기사" count={3} />
              <IconCount icon={FileText} label="근거 문서" count={2} />
            </StateRow>
          </Demo>

          <Demo
            id="c-price"
            name="PriceChange · SentimentLabel"
            when="등락은 색, 부호, ▲▼를 함께 써요. 기업 상세 시세·차트·평가 손익은 금액과 등락률을 같이(받은 통화 그대로), 값이 없으면 아무것도 그리지 않아요. 감성 4분류는 나중을 위한 규격이고, 확률 수치는 쓰지 않아요. 아래 숫자는 예시예요."
            code={"<PriceChange change={quote.change} changePercent={quote.changeRate * 100} currency={quote.currency} />"}
          >
            <StateRow label="등락률">
              <PriceChange changePercent={2.34} />
              <PriceChange changePercent={-1.5} />
              <PriceChange changePercent={0} />
              <span className="text-sm text-text-secondary">null → (그리지 않음)</span>
              <PriceChange changePercent={null} />
            </StateRow>
            <StateRow label="금액 + 등락률">
              <PriceChange change={5250} changePercent={1.96} currency="KRW" />
              <PriceChange change={-13.61} changePercent={-1.84} currency="USD" />
            </StateRow>
            <StateRow label="감성">
              <SentimentLabel value="positive" />
              <SentimentLabel value="negative" />
              <SentimentLabel value="mixed" />
              <SentimentLabel value="undetermined" />
            </StateRow>
          </Demo>

          <Demo id="c-disclaimer" name="DisclaimerNote" when="투자 권유가 아니라는 고지예요. 브리핑과 기업 상세 맨 아래에 13px 한 줄로 둬요. 이 페이지의 고지도 여기 하나예요." code={"<DisclaimerNote />"}>
            <DisclaimerNote />
          </Demo>

          <Demo
            id="c-eventrow"
            name="EventRow"
            when="사건 1건을 카드 없이 한 행으로 보여줘요. 날짜 줄에 아이콘 메타(관계 선 견본·보도 기사 수)를 붙이고, 제목과 근거 버튼이 이어져요."
            code={'<EventRow title={event.title} eventTime={event.eventTime} timePrecision="day" evidenceCount={3} onShowEvidence={open} meta={<IconCount icon={Newspaper} label="보도 기사" count={3} />} />'}
          >
            <div className="max-w-2xl">
              <EventRow
                title="예시: 예시전자 2분기 실적 발표"
                eventTime="2026-07-10"
                timePrecision="day"
                evidenceCount={2}
                relationType="INVOLVES"
                onShowEvidence={() => setSheetOpen(true)}
                onAsk={() => toast({ title: "예시: AI 질문 창을 열어요" })}
                headingLevel="h4"
                meta={<IconCount icon={Newspaper} label="보도 기사" count={3} />}
              />
              <EventRow title="예시: 시각이 확인되지 않은 사건" eventTime={null} timePrecision="unknown" evidenceCount={0} headingLevel="h4" divider={false} />
            </div>
          </Demo>

          <Demo
            id="c-briefing"
            name="BriefingCard"
            when="브리핑 1회분이에요. 바깥 경계는 이것 하나이고, 안은 EventRow로 채워요. 그래서 이 예시는 프레임 없이 보여줘요."
            code={'<BriefingCard edition="morning" date={date} scheduledAt="07:40" publishedAt={…} dataAsOf={…} notice={…} corrections={…} totalEvidence={3} summary={…} relations={…} />'}
            frame={false}
          >
            <BriefingCard
              className="max-w-2xl"
              edition="morning"
              date="2026-09-29"
              scheduledAt="07:40"
              publishedAt="2026-09-29 07:41 KST"
              dataAsOf="2026-09-29 07:40 KST"
              totalEvidence={2}
              summary={<EventRow title="예시: 예시전자 2분기 실적 발표" eventTime="2026-07-10" timePrecision="day" evidenceCount={2} headingLevel="h3" divider={false} />}
              relations={<p className="text-base text-text-secondary">브리핑 사건과 기업을 잇는 작은 지도가 들어가요.</p>}
            />
          </Demo>

          <Demo id="c-company" name="CompanyHeader · CompanyMark" when="기업 상세와 패널 맨 위예요. 지도 노드와 같은 표지(상징색 원 + 로고, 없으면 이니셜)를 앞에 둬요. 시세가 없으면 시세 자리를 두지 않아요." code={'<CompanyHeader id={c.id} name={c.name} brandColor={c.brandColor} logoUrl={c.logoUrl} ticker={c.ticker} holding={c.holding} watch={c.watch} />'}>
            <CompanyHeader id="a" name="예시전자" ticker="000000" sector="예시 업종" brandColor="#1F4E9E" holding holdingWeight={0.4} watch as="h4" />
            <StateRow label="표지">
              {markExamples.map((m) => (
                <span key={m.id} className="flex items-center gap-2 text-sm text-text-secondary">
                  <CompanyMark id={m.id} name={m.name} brandColor={m.brandColor} logoUrl={m.logoUrl} size={32} />
                  <span>
                    <span className="font-medium text-text-primary">{m.name}</span> · {m.note}
                  </span>
                </span>
              ))}
            </StateRow>
          </Demo>

          <Demo
            id="c-evidence"
            name="EvidenceList · VerificationBadge"
            when="근거가 된 기사 문장을 원문 그대로 인용해요. 출처와 시각을 함께 적고, 원문과 대조하지 못한 인용은 경고로 알려요."
            code={"<EvidenceList items={evidence} />"}
          >
            <StateRow label="확인 상태">
              <VerificationBadge verified />
              <VerificationBadge verified={null} />
            </StateRow>
            <EvidenceList items={exampleEvidence} className="max-w-2xl" />
          </Demo>

          <Demo
            id="c-document"
            name="DocumentItem"
            when="기업 상세의 근거 문서 한 건이에요. 출처·발행 시각, 제목, 사건과의 관계, 저장한 인용, 원문 링크 순서예요. 원문 링크가 없으면 정해진 문구를 써요. 인용과 출처는 저장한 값이라 원문 사이트가 열리지 않아도 남아요."
            code={'<DocumentItem title={doc.title} publisher={doc.publisher} url={doc.url} publishedAt={doc.publishedAt} relation="사건을 보도한 기사" quotes={quotes} />'}
          >
            <div className="flex max-w-2xl flex-col divide-y divide-border-subtle">
              <DocumentItem
                className="pb-4"
                headingLevel="h4"
                title="예시: 예시전자 2분기 실적 발표"
                publisher="예시 뉴스"
                url="https://example.invalid/article"
                publishedAt="2026-07-10T09:00:00+09:00"
                relation={documentRelationLabel.REPORTS}
                quotes={[{ id: "ex-1", quote: "예시전자는 2분기 매출이 늘었다고 밝혔다.", quoteVerified: true }]}
              />
              <DocumentItem
                className="pt-4"
                headingLevel="h4"
                title="예시: 원문 링크가 없는 공시 요약"
                publisher="예시 공시"
                url={null}
                publishedAt="2026-07-11T18:00:00+09:00"
                relation={documentRelationLabel.PROVIDES_BACKGROUND}
              />
            </div>
          </Demo>

          <Demo
            id="c-ai"
            name="AiBadge · AiNotice · AiDisclosure"
            when="AI가 만든 글이라는 표시를 한 번, 아래에 한 줄 고지를 둬요. 만든 방법은 링크를 눌러 팝오버로 봐요."
            code={'<AiBadge /> … <AiNotice /> <AiDisclosure sourceScope="근거 3건" asOf={asOf} />'}
          >
            <StateRow label="표시">
              <AiBadge />
            </StateRow>
            <AiNotice />
            <AiDisclosure sourceScope="예시 근거 2건" asOf="2026-09-29 07:30" />
          </Demo>
        </Section>

        <Section
          id="graph"
          title="그래프"
          description="GraphDB 시각화(Neo4j Browser·Bloom) 관례를 따라요. 모든 노드는 원이고 종류는 색으로 구분해요. 선 가운데에는 관계 요약을 적고, 관계 유형은 선 모양으로 구분해요. 지도에는 항상 같은 내용의 목록이 함께 있어요."
        >
          <Demo
            id="c-legend"
            name="GraphLegend"
            when="Neo4j식 라벨 칩이에요. 지도에 있는 종류만 표지 + 이름 + 개수로 보여줘요. onToggle을 주면 노드 종류·관계 유형 칩이 표시 켜기/끄기 버튼(aria-pressed)이 돼요. 꺼도 개수는 그대로고 칩만 흐려져요. 노드 종류는 하나 이상 켜 둬야 해서 마지막 하나는 끌 수 없어요. 연결 없는 사건 묶음은 '사건'을 따라요. 지도는 다시 배치하지 않아요."
            code={"<GraphLegend nodes={graph.nodes} edges={graph.edges} hidden={hidden} onToggle={toggle} />"}
          >
            <StateRow label="보기 전용">
              <GraphLegend nodes={demoNodes} edges={demoEdges} />
            </StateRow>
            <StateRow label="거르기">
              <GraphLegend nodes={demoNodes} edges={demoEdges} hidden={legendHidden} onToggle={toggleLegend} />
            </StateRow>
          </Demo>

          <div className="flex flex-col gap-3">
            <h3 className="text-lg font-semibold text-text-primary">노드</h3>
            <ul className="flex max-w-prose list-disc flex-col gap-2 pl-5 text-base text-text-primary marker:text-text-secondary">
              <li>기업: 상징색 원(기본 모델 크기 데스크톱 64px, 모바일 72px, 중심 기업 +12px) 안에 흰색 또는 거의 검정(대비가 큰 쪽) 로고. 화면 최소 지름은 넓게 볼수록 줄어요(배율 0.6배 이상 44px → 0.25배 이하 28px, WCAG 2.2 최소 대상 24px 이상). 로고가 없으면 이니셜, 상징색이 없으면 폴백 팔레트 8색 중 company_id 해시로 고른 색(항상 같은 색).</li>
              <li>사건: 범주색 원 하나(graph-node-issue) + 번개 아이콘. 캡션은 원문 대상이나 제목을 최대 두 줄로 줄여요(한글 포함 시 줄당 12자, 그 외 24자). 전체 제목은 상세에서 읽을 수 있어요.</li>
              <li>근거 수 배지: 사건 노드 오른쪽 위에 그 사건의 근거 수(그래프 응답 evidenceCount, 사건 상세 근거 수와 같음)를 채운 원으로 붙여요. 숫자는 text-primary 바탕에 surface-base 글자라 두 테마 모두 대비 4.5:1을 넘고, 바깥 바탕색 테두리로 노드와 떨어져 보여요. 숫자가 13px 아래로 작아지지 않게 배율에 반비례해 키우고, 사건 캡션과 같은 0.55배부터 보여요. 캡션 정리로는 숨기지 않아요.</li>
              <li>연결 없는 사건 묶음: 그래프에서 선이 하나도 없는 사건(후속 사건 선만 있어도 연결된 것)은 묶음 노드 하나로 모아 지도 가장자리(가로로 긴 화면은 오른쪽, 세로로 긴 화면은 아래)에 둬요. 범주색 원 + 개수 + 이중 테두리, 캡션은 “연결 없는 사건 N”. 기업처럼 축소해도 화면에서 48px을 지켜 개수가 읽혀요. 누르면 상세에 묶인 사건이 최신순으로 나와요. 캔버스 위 투명 버튼으로 키보드·스크린리더(“연결 없는 사건 N건 보기”)도 고를 수 있어요. 목록 보기는 모든 사건을 그대로 보여줘요.</li>
              <li>보유·관심: 3px 바깥 테두리(모양 신호). 선택: 3px 브랜드 외곽선(글로우 없음). 배경 대비 3:1이 안 되는 상징색은 얇은 윤곽선.</li>
              <li>캡션은 노드 아래, 선 요약은 선을 따라 회전하고 바탕색 배경을 깔아요. 화면 글자는 최소 13px이에요. 사건 캡션은 0.55배, 선 요약은 0.95배 미만에서 숨겨요. 선 160개 초과 시 강조된 선의 요약만 보여요.</li>
              <li>캡션 정리: 화면이 멈춘 뒤(140ms) 캡션끼리 또는 캡션과 다른 기업 원이 겹치면 우선순위가 낮은 쪽 캡션만 숨겨요. 순서는 선택·경로·포커스 중심(항상 보임) &gt; 선택의 이웃 기업 &gt; 보유·관심 기업 &gt; 연결 수가 많은 기업 &gt; 묶음 &gt; 사건이에요. 원·배지·선은 그대로이고, 확대하거나 올리거나 고르면 캡션이 다시 보여요.</li>
              <li>배치 고정: fcose 난수 씨앗을 고정하고 앱 실행 중에는 데이터별 좌표를 기억해, 새로고침이나 지도 복귀 뒤에도 같은 자리에 그려요. 배치 계산 때 기업은 이름 자리까지 포함한 크기(140)로 셈해요.</li>
              <li>선 요약은 12자를 넘으면 말줄임해요. 노드를 고르거나 올리면 연결된 사건이 최신인 선 6개에만 요약이 보이고, 나머지 선은 그 선에 올리거나 눌렀을 때 전체 요약이 보여요. 같은 두 노드 사이의 여러 선은 곡선 간격을 넓혀 요약이 겹치지 않게 해요.</li>
              <li>누를 수 있는 선(명세 D03·FS022): 사건 공유(기업 사이)와 후속 사건(사건 사이) 선만 연결선 상세를 열어요. 사건–기업 선(직접 관련·구조적 관련)은 올리면 요약만 보이고 눌러도 아무것도 고르지 않아요. 기업과 사건의 관계는 기업 상세의 [직접 이슈]에서 사건을 눌러 영향 경로로 봐요.</li>
            </ul>
          </div>

          <div className="flex flex-col gap-3">
            <h3 className="text-lg font-semibold text-text-primary">선 4종</h3>
            <p className="max-w-prose text-base text-text-secondary">
              위 세 가지는 검증된 관계예요(화살표 = 방향). 사건 공유는 같은 사건 보도에 두 기업이 함께 나왔다는 뜻일 뿐이라, 방향 없이 가장 흐린 점선으로
              그려요. 직접 관계가 아니라는 설명은 연결선 상세에서만 해요.
            </p>
            <TableScroll label="선 4종 표">
              <table className="w-full min-w-[640px] border-collapse text-sm">
                <caption className="sr-only">그래프 선 종류별 모양과 뜻</caption>
                <thead>
                  <tr>
                    <th scope="col" className={th}>
                      선
                    </th>
                    <th scope="col" className={th}>
                      모양
                    </th>
                    <th scope="col" className={th}>
                      뜻
                    </th>
                    <th scope="col" className={th}>
                      구분
                    </th>
                  </tr>
                </thead>
                <tbody>
                  {edgeRules.map((edge) => (
                    <tr key={edge.type}>
                      <th scope="row" className={cn(td, "text-left font-medium whitespace-nowrap text-text-primary")}>
                        <span className="flex items-center gap-2">
                          <EdgeGlyph type={edge.type} />
                          {relationLabel[edge.type]}
                        </span>
                      </th>
                      <td className={cn(td, "whitespace-nowrap text-text-secondary")}>{edge.shape}</td>
                      <td className={cn(td, "text-text-primary")}>{relationDescription[edge.type]}</td>
                      <td className={cn(td, "whitespace-nowrap")}>{edge.approved ? "승인 관계" : <Badge variant="warning">파생 경로</Badge>}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </TableScroll>
          </div>

          <Demo
            id="c-focus"
            name="FocusBar"
            when="포커스 모드예요. 기업·사건 상세의 [이 노드 중심으로 보기]로 들어가면 그 노드의 1단계(바로 이어진 노드) 또는 2단계(이웃의 이웃) 이웃만 남기고, 포커스 노드를 제자리에 둔 방사형(1단계는 첫 링, 2단계는 둘째 링)으로 옮겨 사건 캡션과 근거 배지가 읽히는 배율로 맞춰요. 링 안 순서는 원래 지도의 방향을 따르고, 나오면 원래 위치로 돌아가요. 기본은 1단계예요. 들어가기·범위 바꾸기·전체 보기는 주소(?focus=&hops=)에 쌓여 뒤로 가기로 돌아올 수 있어요. 좁은 화면에서는 [전체 보기]가 아이콘이 돼 한 줄을 지켜요."
            code={"<FocusBar node={node} hops={1} onHopsChange={setHops} onExit={exit} />"}
          >
            <StateRow label="넓은 화면">
              <FocusBar node={demoNodes[0]!} hops={demoFocus?.hops ?? 1} onHopsChange={(hops) => setDemoFocus({ id: "a", hops })} onExit={() => setDemoFocus(null)} />
            </StateRow>
            <StateRow label="좁은 화면">
              <FocusBar
                node={demoNodes[0]!}
                hops={demoFocus?.hops ?? 1}
                onHopsChange={(hops) => setDemoFocus({ id: "a", hops })}
                onExit={() => setDemoFocus(null)}
                compact
                className="w-full max-w-[366px]"
              />
            </StateRow>
          </Demo>

          <Demo
            id="c-path"
            name="PathBar"
            when="두 기업 사이 경로예요. 기업 상세의 [다른 기업과의 연결 보기]에서 지도의 다른 기업을 고르면, 승인된 관계 선만 따라(방향 무시, 사건 공유 파생 선 제외) 가장 적은 단계로 잇는 경로를 강조해요. 나머지는 흐리게 두고 경로 선 요약은 항상 보이며, 상세에는 기업 → 선 요약 → 사건 → … 단계 목록이 나와요. 이어지지 않으면 막대 없이 상세에 '아직 두 기업을 잇는 사건이 없어요.'만 보여요. 주소(?path=A,B)에 쌓여 뒤로 가기로 돌아오고, 포커스와 함께 두지 않아요. 좁은 화면에서는 [경로 단계 보기]로 단계 시트를 열어요. 카메라는 경로(영향 경로 포함)에 맞추되, 넓은 화면에서 미니맵이 있으면 그 위까지만, 좁은 화면에서 상세 시트가 열려 있으면 시트 위 영역에 맞춰요. 아래 지도(작은 예시)에 적용돼요."
            code={"<PathBar from={a} to={b} steps={path.edgeIds.length} onExit={exit} />"}
          >
            {demoPath && demoPathOn ? (
              <>
                <StateRow label="넓은 화면">
                  <PathBar from={demoNodes[0]!} to={demoNodes[2]!} steps={demoPath.edgeIds.length} onExit={() => setDemoPathOn(false)} />
                </StateRow>
                <StateRow label="좁은 화면">
                  <PathBar
                    from={demoNodes[0]!}
                    to={demoNodes[2]!}
                    steps={demoPath.edgeIds.length}
                    onExit={() => setDemoPathOn(false)}
                    compact
                    className="w-full max-w-[366px]"
                  />
                </StateRow>
              </>
            ) : (
              <Button
                variant="secondary"
                onClick={() => {
                  setDemoFocus(null);
                  setDemoPathOn(true);
                }}
              >
                예시전자 ↔ 예시소재 경로 보기
              </Button>
            )}
          </Demo>

          <Demo
            id="c-mode"
            name="GraphModeSwitch · 보유/관심 표시"
            when="전체(시장 전체)와 개인화(내 종목: 보유 + 관심) 지도를 바꿔요. 고른 칸이 지금 모드예요. 주소가 없으면 보유·관심이 있는 회원은 개인화로, 아니면 전체로 열려요. 비회원이 개인화를 누르면 자물쇠와 로그인 안내가 나와요. 지도에서 보유는 실선 테두리, 관심은 점선 테두리, 둘 다면 이중 테두리이고 이름 아래에 글자로도 적어요(색만으로 구별하지 않아요). 보유·관심이 모두 없으면 관심 종목 고르기를 안내해요."
            code={'<GraphModeSwitch value={mode} onValueChange={setMode} lockedModes={isGuest ? ["personal"] : []} />'}
          >
            <StateRow label="회원">
              <GraphModeSwitch value={mode} onValueChange={setMode} />
            </StateRow>
            <StateRow label="비회원">
              <GraphModeSwitch value="all" onValueChange={() => undefined} lockedModes={["personal"]} />
            </StateRow>
            <StateRow label="표시">
              <span className="flex items-center gap-1.5 text-sm text-text-primary">
                <MarkRing kind="holding" />
                보유
              </span>
              <span className="flex items-center gap-1.5 text-sm text-text-primary">
                <MarkRing kind="watch" />
                관심
              </span>
            </StateRow>
            <StateRow label="빈 개인화">
              <EmptyState
                className="py-0"
                title="아직 보유·관심 종목이 없어요"
                description="관심 종목을 고르거나 가상 계좌를 연결하면 내 종목 지도를 보여드려요."
                action={
                  <>
                    <Button size="sm">관심 종목 고르기</Button>
                    <Button size="sm" variant="ghost">
                      시장 전체 지도 보기
                    </Button>
                  </>
                }
              />
            </StateRow>
          </Demo>

          <Demo
            id="c-tutorial"
            name="GraphTutorialPanel · GraphTutorialSheetBar · 튜토리얼 대상 표시"
            when="메인 지도 튜토리얼 5단계(지도 움직이기 → 기업·사건 고르기 → 영향 경로 보기(기업 상세의 [직접 이슈]에서 사건, 또는 기업 사이 선) → 근거 확인 → AI에게 묻기)예요. 사건–기업 선은 누를 수 없으므로 누르라고 하지 않아요(FS022). 비회원의 5단계는 AI 질문이 회원 기능이라는 것과 [로그인]만 안내해요. 패널은 데스크톱에서 왼쪽 목록 자리, 모바일에서 지도 위 흐름 안에 놓여요. 모바일 상세 시트가 열리면 같은 단계의 짧은 안내(번호·한 줄 지시·[다음]/[건너뛰기])가 시트 머리글 아래로 옮겨 가고, 지도에서 해야 하는 단계는 [창 닫기]를 함께 줘요. 단계 알림은 보이는 쪽 하나만 읽어요. 가리킬 대상에는 .tutorial-target(브랜드 점선 테두리)을 붙이고, 키보드 포커스는 실선으로 따로 보여요."
            code={'const t = useGraphTutorial(active, onClose); <GraphTutorialPanel tutorial={t} live={!sheetOpen} /> <GraphExplorer sheetTop={<GraphTutorialSheetBar tutorial={t} onCloseSheet={…} />} />'}
          >
            <StateRow label="대상 표시">
              <Button variant="secondary" className="tutorial-target">
                근거 2건 보기
              </Button>
              <Button variant="ghost">AI에게 묻기</Button>
            </StateRow>
          </Demo>

          <Demo
            id="c-canvas"
            name="GraphCanvas · RelationList"
            when="force-directed(fcose) 배치예요. 노드를 끌어 옮기고, 올리면 이웃만 선명해지고, 누르면 선택(카메라가 부드럽게 따라감), 두 번 누르면 이웃으로 확대해요. 큰 지도(150개)로 바꿔 라벨이 배율에 따라 줄어드는 모습을 볼 수 있어요. 넓은 화면에서 보이는 노드가 60개를 넘으면 오른쪽 아래에 미니맵(전체 조망 + 보이는 영역 사각형, 끌면 화면이 따라감)이 생겨요. 포인터 전용이라 스크린리더에는 숨기고, 키보드는 확대·축소·화면에 맞추기를 써요. 함께 둔 목록(RelationList)으로 같은 내용을 키보드와 스크린리더로 볼 수 있어요. 아래 인용의 [지도에서 보기]를 누르면 그 근거 id(evidenceIds)를 가진 선과 양 끝 노드만 강조돼요(해당 선이 없으면 그 사건 노드). 근거 창을 닫으면 강조가 풀려요. 위 범례·포커스·경로 예시의 상태가 이 지도에도 적용돼요."
            code={'<GraphCanvas nodes={nodes} edges={edges} selection={sel} onSelect={setSel} ariaLabel="…" groupIsolated focus={focus} hidden={hidden} evidence={highlight} path={path} />'}
          >
            <Segmented
              aria-label="예시 지도 크기"
              value={graphSize}
              onValueChange={(size) => {
                setGraphSize(size);
                setSelection(null);
              }}
              options={[
                { value: "small", label: "작은 예시(6개)" },
                { value: "big", label: "큰 예시(150개)" },
              ]}
            />
            <GraphLegend nodes={demoGraph.nodes} edges={demoGraph.edges} />
            <div className="grid gap-6 lg:grid-cols-[minmax(0,1fr)_280px]">
              <GraphCanvas
                nodes={demoGraph.nodes}
                edges={demoGraph.edges}
                selection={selection}
                onSelect={setSelection}
                ariaLabel={`예시 지도. 노드 ${demoGraph.nodes.length}개, 연결선 ${demoGraph.edges.length}개가 있어요.`}
                className="h-[420px]"
                minimalToolbar
                groupIsolated
                focus={graphSize === "small" ? demoFocus : null}
                path={graphSize === "small" && demoPathOn && !demoFocus ? demoPath : null}
                hidden={legendHidden}
                evidence={demoEvidence ? { evidenceId: demoEvidence } : null}
              />
              <RelationList
                nodes={demoGraph.nodes}
                edges={demoGraph.edges}
                selection={selection}
                onSelect={setSelection}
                label="예시 지도의 연결 목록"
                className="max-h-[420px]"
              />
            </div>
            <EvidenceList
              items={exampleEvidence}
              mapLink={{ activeId: demoEvidence, onToggle: (id) => setDemoEvidence((current) => (current === id ? null : id)) }}
              className="max-w-2xl"
            />
          </Demo>

        </Section>

        <Section
          id="motion"
          title="모션"
          description="당근 SEED의 모션 값(seed-design.io/foundations/motion)을 그대로 옮겼어요. 200ms 이하는 마이크로, 넘으면 매크로예요. transform과 opacity만 움직이고 튀는 오버슈트는 쓰지 않아요. 동작 줄이기를 켜면 모두 즉시 바뀌어요."
        >
          <TableScroll label="모션 토큰 표">
            <table className="w-full min-w-[560px] border-collapse text-sm">
              <caption className="sr-only">모션 토큰 값과 쓰는 곳</caption>
              <thead>
                <tr>
                  <th scope="col" className={th}>
                    토큰
                  </th>
                  <th scope="col" className={th}>
                    값
                  </th>
                  <th scope="col" className={th}>
                    쓰는 곳
                  </th>
                </tr>
              </thead>
              <tbody>
                {motionTokens
                  .filter((t) => motionUses[t.name])
                  .map((t) => (
                    <tr key={t.name}>
                      <th scope="row" className={cn(td, "text-left font-normal")}>
                        <code className="font-mono text-sm text-text-primary">{t.name}</code>
                      </th>
                      <td className={cn(td, "font-mono text-text-primary")}>{t.value}</td>
                      <td className={cn(td, "text-text-secondary")}>{motionUses[t.name]}</td>
                    </tr>
                  ))}
              </tbody>
            </table>
          </TableScroll>
          <Demo
            id="c-motion"
            name="눌림 축소 · 목록 첫 표시"
            when="누를 수 있는 것은 눌리는 동안 세로로 2px 줄어요(SEED Feedback/Scale, pressable). 목록은 처음 보일 때 행이 30ms 간격으로 떠올라요(stagger). 시트·다이얼로그의 진입·퇴장은 위 ‘Dialog · Sheet · BottomSheet’에서 열고 닫아 보세요."
            code={'<button className="pressable">…</button> <ul className="stagger">…</ul>'}
          >
            <StateRow label="눌림">
              <Button>주 행동</Button>
              <Button variant="secondary">보조 행동</Button>
              <Button variant="ghost" size="icon" aria-label="예시 아이콘 버튼">
                <Star aria-hidden="true" />
              </Button>
            </StateRow>
            <div className="flex flex-col gap-2">
              <Button variant="secondary" size="sm" className="w-fit" onClick={() => setStaggerKey((k) => k + 1)}>
                목록 다시 보이기
              </Button>
              <ul key={staggerKey} className="stagger max-w-md">
                {["예시전자", "예시반도체", "예시소재", "예시화학"].map((name) => (
                  <li key={name}>
                    <ListRow leading={<CompanyMark id={name} name={name} />} title={name} />
                  </li>
                ))}
              </ul>
            </div>
          </Demo>
        </Section>

        <Section id="icons" title="아이콘" description="lucide 아이콘을 글자 옆에 그대로 둬요(상자에 가두지 않아요). 같은 뜻에는 앱 전체에서 같은 아이콘을 써요. 아이콘만 있는 컨트롤은 aria-label과 툴팁이 필수예요.">
          <TableScroll label="아이콘 표">
            <table className="w-full min-w-[480px] border-collapse text-sm">
              <caption className="sr-only">아이콘과 뜻</caption>
              <thead>
                <tr>
                  <th scope="col" className={th}>
                    아이콘
                  </th>
                  <th scope="col" className={th}>
                    뜻
                  </th>
                </tr>
              </thead>
              <tbody>
                {iconRules.map(({ icon: Icon, name, meaning }) => (
                  <tr key={name}>
                    <th scope="row" className={cn(td, "text-left font-normal")}>
                      <span className="flex items-center gap-2">
                        <Icon className="size-5 text-text-primary" aria-hidden="true" />
                        <code className="font-mono text-sm text-text-secondary">{name}</code>
                      </span>
                    </th>
                    <td className={cn(td, "text-text-primary")}>{meaning}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </TableScroll>
        </Section>

        <Section id="writing" title="UX 라이팅" description="금융을 잘 몰라도 부담 없이 읽히게 써요. 투자를 권하거나 원인을 단정하지 않아요.">
          <TableScroll label="라이팅 규칙 표">
            <table className="w-full min-w-[640px] border-collapse text-sm">
              <caption className="sr-only">라이팅 규칙과 고친 예</caption>
              <thead>
                <tr>
                  <th scope="col" className={th}>
                    규칙
                  </th>
                  <th scope="col" className={th}>
                    이렇게 쓰지 않아요
                  </th>
                  <th scope="col" className={th}>
                    이렇게 써요
                  </th>
                </tr>
              </thead>
              <tbody>
                {writingRules.map((r) => (
                  <tr key={r.rule}>
                    <th scope="row" className={cn(td, "text-left font-medium text-text-primary")}>
                      {r.rule}
                    </th>
                    <td className={cn(td, "text-text-secondary line-through decoration-1")}>{r.bad}</td>
                    <td className={cn(td, "text-text-primary")}>{r.good}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </TableScroll>

          <div className="flex flex-col gap-3">
            <h3 className="text-lg font-semibold text-text-primary">금지어</h3>
            <TableScroll label="금지어 표">
              <table className="w-full min-w-[640px] border-collapse text-sm">
                <caption className="sr-only">쓰지 않는 표현과 대신 쓰는 표현</caption>
                <thead>
                  <tr>
                    <th scope="col" className={th}>
                      쓰지 않는 말
                    </th>
                    <th scope="col" className={th}>
                      이유
                    </th>
                    <th scope="col" className={th}>
                      대신
                    </th>
                  </tr>
                </thead>
                <tbody>
                  {bannedWords.map((w) => (
                    <tr key={w.bad}>
                      <th scope="row" className={cn(td, "text-left font-medium text-text-secondary line-through decoration-1")}>
                        {w.bad}
                      </th>
                      <td className={cn(td, "text-text-secondary")}>{w.why}</td>
                      <td className={cn(td, "text-text-primary")}>{w.good}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </TableScroll>
          </div>
        </Section>

        <Section id="slop" title="슬롭 금지 체크리스트" description="화면을 만들거나 리뷰할 때 14가지를 확인해요. 하나라도 걸리면 고쳐요.">
          <ol className="flex max-w-prose list-decimal flex-col gap-3 pl-6 text-base text-text-primary marker:text-text-secondary">
            {slopChecklist.map((item) => (
              <li key={item} className="pl-1">
                {item}
              </li>
            ))}
          </ol>
        </Section>
      </div>
    </div>
  );
}
