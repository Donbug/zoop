// 노드·연결선 상세(UI-04·UI-05). 데스크톱은 지도 오른쪽 패널, 모바일은 바텀시트 안에 그린다(감싸는 틀은 graph-explorer).
// 내부는 평탄하게: SectionHeader(아이콘) + ListRow/EventRow + 구분선. 관계 유형의 뜻은 섹션 머리의 정보 아이콘 안에 둔다.
//  - 기업(요구 20): 상징색 표지·티커·업종·보유/관심, 직접 이슈(INVOLVES)와 간접 이슈(구조적 관련 + 직접 이슈의 앞뒤 사건)를
//    나눠 보이고, 같은 사건을 공유하는 관련 기업, 기업 상세 이동. 생산자가 없는 시세·재무·AI 요약은 자리를 두지 않는다.
//  - 사건: 시각(정밀도), 근거, 관련 기업, 보도 기사, 앞뒤 사건. 긍정·부정 해석은 데이터가 없어 두지 않는다.
//  - 연결선(요구 23): 두 대상·방향·공유 사건·확인 시점. 관계 유형(공급·고객 등)은 데이터에 없으므로 만들지 않는다.
//  - 연결 없는 사건 묶음(G1): 묶인 사건을 최신순 EventRow로, 각 행에서 근거를 연다.
//  - 기업·사건에는 [이 노드 중심으로 보기](G2 포커스 모드 진입)를 둔다.
//  - 기업에는 [다른 기업과의 연결 보기](G6 경로)를 둔다(path-panel).
//  - [AI에게 묻기](요구 25): 선택 대상과 기간·근거 수를 질문 대상으로 넘기고, 질문 창에서 확인·해제한다.
import { ArrowUpRight, Building2, ExternalLink, FileText, Focus, GitFork, History, Info, Link2, MessageCircleQuestion, Newspaper, Star, Unlink, Wallet, Zap } from "lucide-react";
import type { ReactNode } from "react";
import { Link } from "react-router";
import type { Schemas } from "@/api/client";
import { useCompany, useEdge, useEvent, useEventsByIds } from "@/api/queries";
import { Badge } from "@/components/ui/badge";
import { ApprovalNote, RoleUnconfirmed } from "@/components/domain/approval-note";
import { CompanyMark } from "@/components/domain/company-mark";
import { EventRow } from "@/components/domain/event-row";
import type { GraphSelection } from "@/components/domain/graph-canvas";
import { EdgeGlyph } from "@/components/domain/relation-type-tag";
import { Button } from "@/components/ui/button";
import { WatchToggle } from "@/components/domain/watch-toggle";
import { ErrorState, SkeletonLines, SkeletonRows } from "@/components/ui/feedback";
import { ISOLATED_BUNDLE_ID, isolatedBundleLabel, isolatedIssues } from "@/lib/graph-view";
import { IconHint } from "@/components/ui/icon-hint";
import { ListRow } from "@/components/ui/list-row";
import { SectionHeader } from "@/components/ui/section-header";
import { assertionStatusLabel, eventPeriod, formatEventTime, formatKst, relationDescription, relationLabel, type RelationType } from "@/lib/labels";
import { truncate } from "@/lib/utils";
import { useOverlays, type EvidenceRequest } from "./overlays";
import type { ChatTarget } from "./chat-drawer";
import { PathPicker } from "./path-panel";

export interface NodeDetailProps {
  selection: GraphSelection;
  nodes: Schemas["GraphNode"][];
  edges: Schemas["GraphEdge"][];
  onSelect: (selection: GraphSelection) => void;
  /** 근거 창 열기 */
  onShowEvidence: (request: EvidenceRequest) => void;
  /** 기업 상세로 이동할 때 실을 이력 state({ from }) */
  linkState: { from: string };
  /** 연결 없는 사건 묶음에 들어간 사건(그래프 보기에서만). 선택이 묶음이면 이 목록을 보여준다. */
  isolated?: Schemas["GraphNode"][];
  /** 포커스 모드 진입. 없으면 [이 노드 중심으로 보기]를 두지 않는다. */
  onFocusNode?: (id: string) => void;
  /** 지금 포커스 중인 노드(같은 노드면 진입 버튼을 숨긴다) */
  focusId?: string | null;
  /** 경로 모드 진입(기업 → 두 번째 기업). 없으면 [다른 기업과의 연결 보기]를 두지 않는다. */
  onPathTo?: (fromId: string, toId: string) => void;
  /** 기업 패널의 관련 이슈 → 영향 경로(FS022). 없으면 이슈 행은 그 사건을 선택한다. */
  onImpact?: (companyId: string, issueId: string) => void;
}

/** 패널·시트 제목. 지도 데이터만으로 바로 정할 수 있어 상세 조회를 기다리지 않는다.
 *  연결선 제목에서 사건은 짧은 행동어(예: 실적 발표)로 줄인다. 전체 제목은 '연결된 두 대상'에 있다. */
export function selectionTitle(selection: GraphSelection, nodes: Schemas["GraphNode"][], edges: Schemas["GraphEdge"][]) {
  const node = (id: string) => nodes.find((n) => n.id === id);
  if (selection.id === ISOLATED_BUNDLE_ID) return isolatedBundleLabel(isolatedIssues(nodes, edges).length);
  if (selection.kind === "node") return node(selection.id)?.label ?? selection.id;
  const edge = edges.find((e) => e.id === selection.id);
  if (!edge) return "연결 관계";
  const short = (id: string) => {
    const n = node(id);
    return n?.kind === "issue" ? (n.action ?? truncate(n.label, 16)) : (n?.label ?? id);
  };
  return `${short(edge.source)} – ${short(edge.target)}`;
}

export function NodeDetail(props: NodeDetailProps) {
  const { selection, nodes } = props;
  const node = selection.kind === "node" ? nodes.find((n) => n.id === selection.id) : undefined;
  return (
    <div className="flex flex-col pb-4">
      {selection.id === ISOLATED_BUNDLE_ID ? (
        <IsolatedIssuesView {...props} />
      ) : selection.kind === "edge" ? (
        <EdgeDetailView key={selection.id} edgeId={selection.id} {...props} />
      ) : node?.kind === "issue" ? (
        <IssueDetailView key={selection.id} issueId={selection.id} {...props} />
      ) : (
        <CompanyDetailView key={selection.id} companyId={selection.id} {...props} />
      )}
    </div>
  );
}

function Actions({ children }: { children: ReactNode }) {
  return <div className="flex flex-wrap items-center gap-2 px-4 pt-3">{children}</div>;
}

function AskButton({ targets }: { targets: ChatTarget[] }) {
  const { openChat } = useOverlays();
  return (
    <Button variant="ghost" onClick={() => openChat({ targets })}>
      <MessageCircleQuestion aria-hidden="true" />
      AI에게 묻기
    </Button>
  );
}

/** 질문 대상 요약: 기간(아는 사건만) · 근거 수 */
function targetDetail(parts: (string | null | false)[]) {
  return parts.filter(Boolean).join(" · ") || undefined;
}

/** [이 노드 중심으로 보기]: 연결이 있는 노드에서만, 이미 그 노드 중심이면 숨긴다. */
function FocusButton({ id, onFocusNode, focusId, edges }: Pick<NodeDetailProps, "onFocusNode" | "focusId" | "edges"> & { id: string }) {
  if (!onFocusNode || focusId === id || !edges.some((e) => e.source === id || e.target === id)) return null;
  return (
    <Button variant="ghost" onClick={() => onFocusNode(id)}>
      <Focus aria-hidden="true" />
      이 노드 중심으로 보기
    </Button>
  );
}

/** 섹션 머리 오른쪽 정보 아이콘: 관계 유형의 뜻 */
function RelationHint({ type }: { type: RelationType }) {
  return (
    <IconHint icon={Info} label={relationLabel[type]}>
      <p>{relationDescription[type]}</p>
    </IconHint>
  );
}

/** 지도 노드에서 기업 표지(상징색·로고)를 찾는다. 지도에 없는 기업은 id 해시 폴백 색. */
function markFor(nodes: Schemas["GraphNode"][], id: string, name: string) {
  const node = nodes.find((n) => n.id === id);
  return <CompanyMark id={id} name={name} brandColor={node?.brandColor} logoUrl={node?.logoUrl} />;
}

/** 간접 이슈 한 건: 구조적 관련(기준 관계) 또는 직접 이슈의 앞뒤 사건(FOLLOWS, 지도 데이터에서 찾는다). */
interface IndirectIssue {
  id: string;
  title: string;
  eventTime: string | null;
  timePrecision: Schemas["CompanyIssueRef"]["timePrecision"] | null;
  evidenceCount: number | null;
  why: string;
}

function CompanyDetailView({
  companyId,
  nodes,
  edges,
  onSelect,
  onShowEvidence,
  linkState,
  onFocusNode,
  focusId,
  onPathTo,
  onImpact,
}: NodeDetailProps & { companyId: string }) {
  const query = useCompany(companyId);

  if (query.isPending) return <div className="px-4"><SkeletonRows count={2} label="기업 정보를 불러오고 있어요" /></div>;
  if (query.isError) return <ErrorState className="px-4" error={query.error} onRetry={() => void query.refetch()} />;

  const company = query.data;
  const nodeOf = (id: string) => nodes.find((n) => n.id === id);
  const direct = company.directIssues;
  const directIds = new Set(direct.map((i) => i.issueId));
  const seen = new Set(directIds);
  const indirect: IndirectIssue[] = company.structuralIssues
    .filter((i) => !seen.has(i.issueId) && seen.add(i.issueId))
    .map((i) => ({ id: i.issueId, title: i.title, eventTime: i.eventTime, timePrecision: i.timePrecision, evidenceCount: i.evidenceCount, why: relationLabel.STRUCTURALLY_RELATED_TO }));
  // 후속 사건 선(FOLLOWS)은 나중 사건 → 앞선 사건 방향이다.
  for (const edge of edges) {
    if (edge.relationType !== "FOLLOWS") continue;
    const [anchor, other, why] = directIds.has(edge.target) ? [edge.target, edge.source, "이어진 사건"] : directIds.has(edge.source) ? [edge.source, edge.target, "앞선 사건"] : [];
    const node = other ? nodeOf(other) : undefined;
    if (!anchor || !node || seen.has(node.id)) continue;
    seen.add(node.id);
    indirect.push({ id: node.id, title: node.label, eventTime: node.eventTime, timePrecision: node.timePrecision, evidenceCount: node.evidenceCount, why: `${why} · ${truncate(nodeOf(anchor)?.label ?? "", 20)}` });
  }
  // 관련 기업: 지도의 사건 공유 선(파생). 누르면 그 선의 상세(공유 사건·확인 시점)를 연다.
  const related = edges
    .filter((e) => e.relationType === "SHARES_ISSUE" && (e.source === companyId || e.target === companyId))
    .map((edge) => ({ edge, other: nodeOf(edge.source === companyId ? edge.target : edge.source) }))
    .sort((a, b) => b.edge.via.length - a.edge.via.length);
  const directEvidence = direct.reduce((sum, i) => sum + i.evidenceCount, 0);
  const period = eventPeriod(direct);

  const issueRow = (issue: { id: string; title: string; eventTime: string | null; timePrecision: IndirectIssue["timePrecision"]; evidenceCount: number | null }, meta?: string) => (
    <li key={issue.id} className="px-4">
      <EventRow
        headingLevel="h4"
        title={issue.title}
        eventTime={issue.eventTime}
        timePrecision={issue.timePrecision}
        evidenceCount={issue.evidenceCount ?? undefined}
        onShowEvidence={() => onShowEvidence({ title: issue.title, eventId: issue.id })}
        // 관련 이슈를 고르면 이 기업과 그 사건의 영향 경로를 연다(FS022). 지도 밖 사건은 경로를 만들 수 없다.
        onSelect={nodeOf(issue.id) ? () => (onImpact ? onImpact(companyId, issue.id) : onSelect({ kind: "node", id: issue.id })) : undefined}
        meta={meta ? <span className="text-sm text-text-secondary">{meta}</span> : undefined}
      />
    </li>
  );

  return (
    <>
      <div className="flex items-center gap-3 px-4">
        <CompanyMark id={company.id} name={company.name} brandColor={company.brandColor} logoUrl={company.logoUrl} size={40} />
        <div className="flex min-w-0 flex-col gap-1">
          {(company.ticker || company.sector) && (
            <p className="text-base text-text-secondary tabular-nums">{[company.ticker, company.sector].filter(Boolean).join(" · ")}</p>
          )}
          {(company.holding || company.watch) && (
            <p className="flex flex-wrap gap-1.5">
              {company.holding && (
                <Badge>
                  <Wallet aria-hidden="true" />
                  보유 종목
                </Badge>
              )}
              {company.watch && (
                <Badge>
                  <Star aria-hidden="true" />
                  관심 종목
                </Badge>
              )}
            </p>
          )}
        </div>
      </div>
      <Actions>
        <Button variant="secondary" asChild>
          <Link to={`/companies/${encodeURIComponent(company.id)}`} state={linkState}>
            <ArrowUpRight aria-hidden="true" />
            기업 상세
          </Link>
        </Button>
        <WatchToggle companyId={company.id} companyName={company.name} />
        <FocusButton id={company.id} onFocusNode={onFocusNode} focusId={focusId} edges={edges} />
        {onPathTo && <PathPicker fromId={company.id} nodes={nodes} onPick={(toId) => onPathTo(company.id, toId)} />}
        <AskButton
          targets={[
            { id: company.id, kind: "company", label: company.name, detail: targetDetail([`직접 이슈 ${direct.length}건`, period, `근거 ${directEvidence}건`]) },
          ]}
        />
      </Actions>

      <section aria-label="직접 이슈">
        <SectionHeader as="h3" icon={Zap} title={`직접 이슈 ${direct.length}건`} action={<RelationHint type="INVOLVES" />} />
        {direct.length === 0 ? (
          <p className="px-4 text-base text-text-secondary">승인된 직접 이슈가 아직 없어요.</p>
        ) : (
          <>
            {onImpact && <p className="px-4 pb-1 text-sm text-text-secondary">사건을 누르면 이 기업과 이어진 경로와 근거가 보여요.</p>}
            <ul className="stagger">{direct.map((i) => issueRow({ id: i.issueId, title: i.title, eventTime: i.eventTime, timePrecision: i.timePrecision, evidenceCount: i.evidenceCount }, i.role ?? undefined))}</ul>
          </>
        )}
      </section>

      <section aria-label="간접 이슈">
        <SectionHeader
          as="h3"
          icon={GitFork}
          title={`간접 이슈 ${indirect.length}건`}
          action={
            <IconHint icon={Info} label="간접 이슈">
              <p>기사에 이 기업이 직접 나오지는 않지만 데이터로 이어진 사건이에요. 등록된 기준 관계로 연결된 사건(구조적 관련)과 직접 이슈의 앞뒤로 이어진 사건(후속 사건)이에요.</p>
            </IconHint>
          }
        />
        {indirect.length === 0 ? (
          <p className="px-4 text-base text-text-secondary">데이터로 이어진 간접 이슈가 없어요.</p>
        ) : (
          <ul className="stagger">{indirect.map((i) => issueRow(i, i.why))}</ul>
        )}
      </section>

      {related.length > 0 && (
        <section aria-label="관련 기업">
          <SectionHeader as="h3" icon={Building2} title={`관련 기업 ${related.length}곳`} action={<RelationHint type="SHARES_ISSUE" />} />
          <ul className="stagger">
            {related.map(({ edge, other }) => (
              <li key={edge.id}>
                <ListRow
                  leading={other ? markFor(nodes, other.id, other.label) : <Building2 />}
                  title={other?.label ?? edge.id}
                  description={`같은 사건 ${edge.via.length}건`}
                  trailing={<EdgeGlyph type="SHARES_ISSUE" />}
                  onClick={() => onSelect({ kind: "edge", id: edge.id })}
                />
              </li>
            ))}
          </ul>
        </section>
      )}
    </>
  );
}

function IssueDetailView({ issueId, nodes, edges, onSelect, onShowEvidence, linkState, onFocusNode, focusId }: NodeDetailProps & { issueId: string }) {
  const query = useEvent(issueId);

  if (query.isPending) return <div className="px-4"><SkeletonRows count={2} label="사건 정보를 불러오고 있어요" /></div>;
  if (query.isError) return <ErrorState className="px-4" error={query.error} onRetry={() => void query.refetch()} />;

  const event = query.data;
  const nodeIds = new Set(nodes.map((n) => n.id));
  const companyGroups = (["INVOLVES", "STRUCTURALLY_RELATED_TO"] as const)
    .map((type) => ({ type, companies: event.companies.filter((c) => c.relationType === type) }))
    .filter((g) => g.companies.length > 0);
  const follows = [
    ...event.follows.previous.map((f) => ({ ...f, direction: "앞선 사건" })),
    ...event.follows.next.map((f) => ({ ...f, direction: "이어진 사건" })),
  ];
  const support = event.sourceSupport;

  return (
    <>
      <p className="px-4 text-base text-text-secondary tabular-nums">
        {formatEventTime(event.eventTime, event.timePrecision)}
        {event.period ? ` · 대상 기간 ${event.period}` : ""}
      </p>
      <ApprovalNote approval={event.approval} className="px-4" />
      <Actions>
        {event.evidenceIds.length > 0 && (
          <Button variant="secondary" onClick={() => onShowEvidence({ title: event.title, evidenceIds: event.evidenceIds, eventId: event.id })}>
            <FileText aria-hidden="true" />
            근거 {event.evidenceIds.length}건 보기
          </Button>
        )}
        <FocusButton id={event.id} onFocusNode={onFocusNode} focusId={focusId} edges={edges} />
        <AskButton
          targets={[
            {
              id: event.id,
              kind: "issue",
              label: event.title,
              detail: targetDetail([event.timePrecision !== "unknown" && formatEventTime(event.eventTime, event.timePrecision), `근거 ${event.evidenceIds.length}건`]),
            },
          ]}
        />
      </Actions>

      {companyGroups.length === 0 ? (
        <>
          <SectionHeader as="h3" icon={Building2} title="관련 기업" />
          <p className="px-4 text-base text-text-secondary">연결된 기업이 없어요.</p>
        </>
      ) : (
        companyGroups.map((group) => (
          <section key={group.type} aria-label={`${relationLabel[group.type]} 기업`}>
            <SectionHeader as="h3" icon={Building2} title={`${relationLabel[group.type]} 기업 ${group.companies.length}곳`} action={<RelationHint type={group.type} />} />
            <ul className="stagger">
              {group.companies.map((c) => (
                <li key={c.id}>
                  {nodeIds.has(c.id) ? (
                    <ListRow leading={markFor(nodes, c.id, c.name)} title={c.name} description={c.role ?? (c.roleUnconfirmed ? <RoleUnconfirmed /> : undefined)} onClick={() => onSelect({ kind: "node", id: c.id })} />
                  ) : (
                    <ListRow
                      leading={markFor(nodes, c.id, c.name)}
                      title={c.name}
                      description={c.role ?? (c.roleUnconfirmed ? <RoleUnconfirmed /> : undefined)}
                      trailing={<ArrowUpRight className="size-4" role="img" aria-label="기업 상세로 이동" />}
                      to={`/companies/${encodeURIComponent(c.id)}`}
                      state={linkState}
                    />
                  )}
                </li>
              ))}
            </ul>
          </section>
        ))
      )}

      <section aria-label="보도 기사">
        <SectionHeader
          as="h3"
          icon={Newspaper}
          title={`보도 기사 ${event.articles.length}건`}
          action={
            support.independentSourceCount !== null && (
              <span className="text-sm text-text-secondary tabular-nums">독립 출처 {support.independentSourceCount}곳</span>
            )
          }
        />
        <ul className="stagger">
          {event.articles.map((a) => (
            <li key={a.id}>
              <ListRow
                title={a.title ?? "제목 없음"}
                description={[a.publisher ?? "출처 미상", formatKst(a.publishedAt), a.relationType === "PROVIDES_BACKGROUND" ? "배경 기사" : null]
                  .filter(Boolean)
                  .join(" · ")}
              />
            </li>
          ))}
        </ul>
      </section>

      {follows.length > 0 && (
        <section aria-label="앞뒤로 이어진 사건">
          <SectionHeader as="h3" icon={History} title="앞뒤로 이어진 사건" action={<RelationHint type="FOLLOWS" />} />
          <ul className="stagger">
            {follows.map((f) => (
              <li key={f.id}>
                <ListRow
                  leading={<Zap />}
                  title={f.title}
                  description={`${f.direction} · ${formatEventTime(f.eventTime, f.timePrecision)}`}
                  onClick={nodeIds.has(f.id) ? () => onSelect({ kind: "node", id: f.id }) : undefined}
                />
              </li>
            ))}
          </ul>
        </section>
      )}
    </>
  );
}

function EdgeDetailView({ edgeId, selection, nodes, edges, onSelect, onShowEvidence }: NodeDetailProps & { edgeId: string }) {
  const query = useEdge(edgeId);

  if (query.isPending) return <div className="px-4"><SkeletonLines lines={5} label="연결 정보를 불러오고 있어요" /></div>;
  if (query.isError) return <ErrorState className="px-4" error={query.error} onRetry={() => void query.refetch()} />;

  const edge = query.data;
  const roles = edge.roles.length > 0 ? edge.roles.join(", ") : edge.role;
  // 파생 선은 자기 근거가 없고, 공유 사건마다 두 기업이 등장한 근거가 있다. 기준 관계가 있으면 그 검증 시각이 관계 확인 시점이다.
  const evidenceIds = edge.derived ? [...new Set(edge.via.flatMap((v) => v.evidenceIds))] : edge.evidenceIds;
  const verifiedAt = edge.basis.map((b) => b.verifiedAt).filter((v): v is string => Boolean(v)).sort().at(-1) ?? null;
  const checkedAt = verifiedAt ?? edge.metadata.asOf;
  const period = eventPeriod(edge.via);
  const title = selectionTitle(selection, nodes, edges);

  return (
    <>
      <div className="flex flex-col gap-2 px-4">
        <p className="flex items-center gap-2 text-lg font-semibold text-text-primary">
          <EdgeGlyph type={edge.relationType} />
          {edge.summary}
          <span className="text-sm font-normal text-text-secondary">{relationLabel[edge.relationType]}</span>
          <RelationHint type={edge.relationType} />
        </p>
        {edge.explanation && <p className={edge.derived ? "text-base text-text-primary" : "text-sm text-text-secondary"}>{edge.explanation}</p>}
        <dl className="mt-1 grid grid-cols-[auto_1fr] gap-x-4 gap-y-1 text-sm">
          <dt className="text-text-secondary">방향</dt>
          <dd className="text-text-primary">{edge.directed ? `${edge.source.label} → ${edge.target.label}` : "방향 없음"}</dd>
          {edge.derived && (
            <>
              <dt className="text-text-secondary">공유 사건</dt>
              <dd className="text-text-primary tabular-nums">
                {edge.via.length}건{period ? ` · ${period}` : ""}
              </dd>
            </>
          )}
          {roles && (
            <>
              <dt className="text-text-secondary">역할</dt>
              <dd className="text-text-primary">{roles}</dd>
            </>
          )}
          {!edge.derived && (
            <>
              <dt className="text-text-secondary">보도 표현</dt>
              <dd className="text-text-primary">{assertionStatusLabel(edge.assertionStatus)}</dd>
              <dt className="text-text-secondary">인용 검증</dt>
              <dd className="text-text-primary">{edge.verification.status === "ALLOW" ? "통과" : "해당 없음"}</dd>
            </>
          )}
          <dt className="flex items-center gap-1 text-text-secondary">
            확인 시점
            <IconHint icon={Info} label="확인 시점">
              <p>
                {verifiedAt
                  ? "기준 관계를 검증한 시각이에요. 기사 발행 시각과 달라요."
                  : "검증을 통과한 자료를 이 시각 기준으로 확인했어요. 기사 발행 시각은 근거에서 따로 보여요."}
              </p>
            </IconHint>
          </dt>
          <dd className="text-text-primary tabular-nums">{formatKst(checkedAt)}</dd>
        </dl>
      </div>
      <Actions>
        {evidenceIds.length > 0 && (
          <Button variant="secondary" onClick={() => onShowEvidence({ title, evidenceIds, checkedAt: verifiedAt })}>
            <FileText aria-hidden="true" />
            근거 {evidenceIds.length}건 보기
          </Button>
        )}
        <AskButton
          targets={[
            {
              id: edge.id,
              kind: "edge",
              label: `${title} ${relationLabel[edge.relationType]}`,
              detail: targetDetail([edge.derived && `함께 언급된 사건 ${edge.via.length}건`, period, `근거 ${evidenceIds.length}건`]),
            },
            ...[edge.source, edge.target].map((end): ChatTarget => ({ id: end.id, kind: end.kind, label: end.label, checked: false })),
          ]}
        />
      </Actions>

      <section aria-label="연결된 두 대상">
        <SectionHeader as="h3" icon={Link2} title="연결된 두 대상" />
        <ul>
          {[edge.source, edge.target].map((end) => (
            <li key={end.id}>
              <ListRow
                leading={end.kind === "company" ? markFor(nodes, end.id, end.label) : <Zap />}
                title={
                  <>
                    <span className="sr-only">{end.kind === "company" ? "기업: " : "사건: "}</span>
                    {end.label}
                  </>
                }
                onClick={() => onSelect({ kind: "node", id: end.id })}
              />
            </li>
          ))}
        </ul>
      </section>

      {edge.via.length > 0 && (
        <section aria-label="함께 언급된 사건">
          <SectionHeader as="h3" icon={Zap} title={`함께 언급된 사건 ${edge.via.length}건`} />
          <ul className="stagger">
            {edge.via.map((issue) => (
              <li key={issue.id} className="px-4">
                <EventRow
                  headingLevel="h4"
                  title={issue.title}
                  eventTime={issue.eventTime}
                  timePrecision={issue.timePrecision}
                  evidenceCount={issue.evidenceIds.length}
                  onShowEvidence={() => onShowEvidence({ title: issue.title, evidenceIds: issue.evidenceIds, eventId: issue.id })}
                  onSelect={() => onSelect({ kind: "node", id: issue.id })}
                />
              </li>
            ))}
          </ul>
        </section>
      )}

      {edge.basis.length > 0 && (
        <section aria-label="관계 기준 문서">
          <SectionHeader as="h3" icon={FileText} title="관계 기준 문서" />
          <ul className="flex flex-col px-4">
            {edge.basis.map((b) => (
              <li key={b.edgeId} className="flex min-h-11 flex-wrap items-center gap-x-2 border-b border-border-subtle py-2 text-sm">
                {b.sourceUrl ? (
                  <a href={b.sourceUrl} target="_blank" rel="noreferrer" className="inline-flex min-h-11 items-center gap-1 font-medium text-brand-primary underline-offset-4 hover:underline">
                    <ExternalLink className="size-4" aria-hidden="true" />
                    기준 문서 열기
                    <span className="sr-only">(새 창에서 열림)</span>
                  </a>
                ) : (
                  <span className="text-text-primary">기준 문서 링크 없음</span>
                )}
                <span className="text-text-secondary tabular-nums">검증 {formatKst(b.verifiedAt)}</span>
              </li>
            ))}
          </ul>
        </section>
      )}
    </>
  );
}

/** 연결 없는 사건 묶음: 묶인 사건을 최신순으로 나열한다(발생 시각 미상은 뒤에, 보도 시각 순). */
function IsolatedIssuesView({ nodes, edges, isolated, onSelect, onShowEvidence }: NodeDetailProps) {
  const issues = isolated ?? isolatedIssues(nodes, edges);
  const queries = useEventsByIds(issues.map((n) => n.id));
  const failed = queries.find((q) => q.isError);
  if (queries.some((q) => q.isPending)) return <div className="px-4"><SkeletonRows count={3} label="연결 없는 사건을 불러오고 있어요" /></div>;
  if (failed) return <ErrorState className="px-4" error={failed.error} onRetry={() => queries.forEach((q) => q.isError && void q.refetch())} />;

  // 발생 시각이 있는 사건을 먼저 최신순으로, 시각 미상(정밀도 unknown 포함)인 사건은 그 뒤에 가장 늦은 보도 시각 순으로 둔다.
  const known = (event: Schemas["EventDetail"]) => (event.timePrecision && event.timePrecision !== "unknown" ? event.eventTime : null);
  const reported = (event: Schemas["EventDetail"]) =>
    event.articles.reduce<string>((max, a) => (a.publishedAt && a.publishedAt > max ? a.publishedAt : max), "");
  const events = queries
    .flatMap((q) => (q.data ? [q.data] : []))
    .sort((a, b) => {
      const [ta, tb] = [known(a), known(b)];
      return ta && tb ? tb.localeCompare(ta) : ta ? -1 : tb ? 1 : reported(b).localeCompare(reported(a));
    });

  return (
    <section aria-label="연결 없는 사건">
      <SectionHeader
        as="h3"
        icon={Unlink}
        title={`사건 ${events.length}건`}
        action={
          <IconHint icon={Info} label="연결 없는 사건">
            <p>지도에서 다른 기업·사건과 이어진 관계가 아직 없는 사건이에요. 최신순이고, 발생 시각을 모르는 사건은 보도가 늦은 순으로 뒤에 둬요.</p>
          </IconHint>
        }
      />
      <ul className="stagger">
        {events.map((event) => (
          <li key={event.id} className="px-4">
            <EventRow
              headingLevel="h4"
              title={event.title}
              eventTime={event.eventTime}
              timePrecision={event.timePrecision}
              evidenceCount={event.evidenceIds.length}
              onShowEvidence={() => onShowEvidence({ title: event.title, evidenceIds: event.evidenceIds, eventId: event.id })}
              onSelect={() => onSelect({ kind: "node", id: event.id })}
            />
          </li>
        ))}
      </ul>
    </section>
  );
}
