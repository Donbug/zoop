// 어느 화면에서든 열 수 있는 두 개의 창:
//  - 근거 창(UI-09, 요구 24): 인용문 원문과 검증 상태. 문서마다 발행 시각을, 창 위에 관계 확인 시점을 따로 보인다
//    (기준 관계의 검증 시각이 있으면 그것, 없으면 검증을 통과한 자료의 기준 시각). 관계(연결선) id만 받으면 그 관계 상세에서
//    검증 시각을 읽는다. 사건·근거·관계 조회는 따로 실패할 수 있고, 실패한 조회만 다시 시도한다(근거 없음과 구분).
//    데이터 출처(datasetKind)는 여기(아이콘)와 앱 헤더에서만 밝힌다.
//  - AI 질문 창(UI-10): 예시 답변. 근거가 부족하면 답변을 보류한다. 화면 버튼([AI에게 묻기])은 그 자리의 대상을 넘기고,
//    모바일 하단 [AI] 탭(openScreenChat)은 지금 화면이 useScreenChatTargets로 알린 대상(기업 상세의 기업 등, 없으면 빈 대상)으로 연다.
// 모바일에서 노드 시트 위에 열면 그 위에 쌓이고, 닫으면 아래 시트로 돌아간다(Radix 대화상자 스택).
// 지도에서 연 근거 창(request.map)은 인용마다 [지도에서 보기] 토글을 두고, 누른 인용을 mapHighlight로 내보낸다.
// 지도(GraphExplorer)가 이 값을 읽어 강조하고, 근거 창을 닫으면 강조가 풀린다.
import { Info, RotateCw } from "lucide-react";
import { createContext, useContext, useEffect, useMemo, useRef, useState, type ReactNode } from "react";
import { useEdge, useEvent, useEvidenceItems } from "@/api/queries";
import { EvidenceList, UnavailableEvidenceNote, isEvidenceGone, type EvidenceMapLink } from "@/components/domain/evidence";
import { SourceIndicator } from "@/components/domain/source-indicator";
import { Button } from "@/components/ui/button";
import { EmptyState, ErrorState, SkeletonRows } from "@/components/ui/feedback";
import { Sheet } from "@/components/ui/dialog";
import { IconHint } from "@/components/ui/icon-hint";
import { formatKst } from "@/lib/labels";
import type { EvidenceHighlight } from "@/lib/graph-view";
import { ChatDrawer, type ChatContext, type ChatTarget } from "./chat-drawer";

export interface EvidenceRequest {
  /** 창 상단에 보여줄 사건·관계 이름 */
  title: string;
  evidenceIds?: string[];
  /** 근거 id를 모를 때 사건 id를 주면 사건 상세에서 근거 목록을 가져온다. */
  eventId?: string;
  /** 문서 판정은 이 기업 맥락으로만 읽는다. 기업이 정해지지 않은 사건·연결선에서는 null. */
  companyId?: string;
  /** 지도에서 열었을 때: 인용을 지도에서 강조할 수 있다. issueId는 해당 간선이 없을 때 대신 강조할 사건. */
  map?: { issueId?: string };
  /** 기준 관계를 검증한 시각(있을 때만). 없으면 근거 응답의 자료 기준 시각을 관계 확인 시점으로 보인다. */
  checkedAt?: string | null;
  /** checkedAt을 모르는 관계(연결선) id: 그 관계 상세의 검증 시각을 관계 확인 시점으로 쓴다. */
  edgeId?: string;
}

interface OverlayApi {
  openEvidence: (request: EvidenceRequest) => void;
  openChat: (context: ChatContext) => void;
  /** 화면 버튼 없이(하단 [AI] 탭) 질문 창을 연다: 지금 화면이 알린 대상을 넘긴다. */
  openScreenChat: () => void;
  /** 지금 화면의 질문 대상을 알리는 자리(useScreenChatTargets가 쓴다) */
  screenTargets: { current: ChatTarget[] | null };
  /** 근거 창에서 [지도에서 보기]를 누른 인용(창이 닫히면 null) */
  mapHighlight: EvidenceHighlight | null;
  /** 근거 창·AI 질문 창이 열려 있는지(튜토리얼이 '실제로 해 봤는지' 확인할 때 읽는다) */
  evidenceOpen: boolean;
  chatOpen: boolean;
}

const OverlayContext = createContext<OverlayApi | null>(null);

export function OverlayProvider({ children }: { children: ReactNode }) {
  const [evidence, setEvidence] = useState<EvidenceRequest | null>(null);
  const [evidenceOpen, setEvidenceOpen] = useState(false);
  const [chat, setChat] = useState<ChatContext | null>(null);
  const [chatOpen, setChatOpen] = useState(false);
  const [mapHighlight, setMapHighlight] = useState<EvidenceHighlight | null>(null);
  const screenTargets = useRef<ChatTarget[] | null>(null);

  const api = useMemo<OverlayApi>(() => {
    const openChat = (context: ChatContext) => {
      setChat(context);
      setChatOpen(true);
    };
    return {
      openEvidence: (request) => {
        setEvidence(request);
        setEvidenceOpen(true);
        setMapHighlight(null);
      },
      openChat,
      openScreenChat: () => openChat({ targets: screenTargets.current ?? [] }),
      screenTargets,
      mapHighlight,
      evidenceOpen,
      chatOpen,
    };
  }, [mapHighlight, evidenceOpen, chatOpen]);

  const setEvidenceOpenAndClear = (open: boolean) => {
    setEvidenceOpen(open);
    if (!open) setMapHighlight(null);
  };

  return (
    <OverlayContext.Provider value={api}>
      {children}
      {evidence && (
        <EvidenceSheet
          request={evidence}
          open={evidenceOpen}
          onOpenChange={setEvidenceOpenAndClear}
          mapLink={
            evidence.map && {
              activeId: mapHighlight?.evidenceId ?? null,
              onToggle: (evidenceId) =>
                setMapHighlight((current) => (current?.evidenceId === evidenceId ? null : { evidenceId, issueId: evidence.map?.issueId })),
            }
          }
        />
      )}
      {chat && (
        <ChatDrawer
          context={chat}
          open={chatOpen}
          onOpenChange={setChatOpen}
          onShowEvidence={(title, evidenceIds) => api.openEvidence({ title, evidenceIds })}
        />
      )}
    </OverlayContext.Provider>
  );
}

export function useOverlays() {
  const api = useContext(OverlayContext);
  if (!api) throw new Error("useOverlays는 OverlayProvider 안에서만 쓸 수 있어요.");
  return api;
}

/** 이 화면이 보여 주는 질문 대상(예: 기업 상세의 기업)을 하단 [AI] 탭에 알린다. 화면을 떠나면 지운다. */
export function useScreenChatTargets(targets: ChatTarget[]) {
  const { screenTargets } = useOverlays();
  useEffect(() => {
    screenTargets.current = targets;
    return () => {
      if (screenTargets.current === targets) screenTargets.current = null;
    };
  });
}

function EvidenceSheet({
  request,
  open,
  onOpenChange,
  mapLink,
}: {
  request: EvidenceRequest;
  open: boolean;
  onOpenChange: (open: boolean) => void;
  mapLink?: EvidenceMapLink;
}) {
  const needsEvent = !request.evidenceIds && Boolean(request.eventId);
  const event = useEvent(needsEvent ? request.eventId : undefined);
  const ids = request.evidenceIds ?? event.data?.evidenceIds ?? [];
  const items = useEvidenceItems(ids, request.companyId);
  const loaded = items.flatMap((q) => (q.data ? [q.data] : []));
  // 받을 수 없는 근거(404 삭제·비공개, 403 권한 없음)는 다시 시도할 대상이 아니다. 일시 장애만 오류로 보이고 그것만 다시 시도한다.
  const failed = items.filter((q) => q.isError && !isEvidenceGone(q.error));
  const gone = items.filter((q) => q.isError && isEvidenceGone(q.error)).length;
  const loading = (needsEvent && event.isPending) || items.some((q) => q.isPending);

  let body: ReactNode;
  if (needsEvent && event.isError) {
    body = isEvidenceGone(event.error) ? (
      <EmptyState title="이 사건은 지금 볼 수 없어요" description="삭제됐거나 지금은 제공하지 않는 사건이에요." />
    ) : (
      <ErrorState error={event.error} title="사건 정보를 불러오지 못했어요" onRetry={() => void event.refetch()} />
    );
  } else if (loading) {
    body = <SkeletonRows count={2} label="근거 문서를 불러오고 있어요" />;
  } else if (ids.length === 0) {
    body = <EmptyState title="연결된 근거 문서가 없어요" />;
  } else {
    body = (
      <div className="flex flex-col gap-4">
        {failed.length > 0 && (
          <ErrorState
            error={failed[0]!.error}
            title={`근거 ${ids.length}건 중 ${failed.length}건을 불러오지 못했어요`}
            onRetry={() => failed.forEach((q) => void q.refetch())}
            compact
          />
        )}
        {gone > 0 && <UnavailableEvidenceNote count={gone} />}
        {loaded.length > 0 && <EvidenceList items={loaded} mapLink={mapLink} />}
      </div>
    );
  }
  // 관계 확인 시점: 넘겨받은 값 > 관계 상세의 마지막 검증 시각 > 근거 자료의 기준 시각. 관계 상세를 읽는 중이거나 실패하면 정하지 않는다.
  const edge = useEdge(request.checkedAt === undefined ? request.edgeId : undefined);
  const edgeVerifiedAt = edge.data?.basis.map((b) => b.verifiedAt).filter((v): v is string => Boolean(v)).sort().at(-1) ?? null;
  const verifiedAt = request.checkedAt ?? edgeVerifiedAt;
  const edgeUnsettled = request.checkedAt === undefined && Boolean(request.edgeId) && !edge.isSuccess;
  const checkedAt = edgeUnsettled ? null : (verifiedAt ?? loaded[0]?.metadata.asOf);

  return (
    <Sheet
      open={open}
      onOpenChange={onOpenChange}
      // 지도에서 연 근거는 모바일에서 절반만 올려 강조된 지도를 함께 보인다.
      mobileSnap={mapLink ? "half" : "full"}
      title="근거 문서"
      description={request.title}
      closeLabel="근거 창 닫기"
      headerExtra={loaded[0] && <SourceIndicator kind={loaded[0].metadata.datasetKind} size="sm" className="-ml-1" />}
    >
      {edgeUnsettled && edge.isError && (
        <p role="alert" className="mb-4 flex flex-wrap items-center gap-x-2 gap-y-1 text-sm text-text-secondary">
          관계 확인 시점을 불러오지 못했어요.
          <Button variant="link" size="sm" onClick={() => void edge.refetch()}>
            <RotateCw aria-hidden="true" />
            다시 시도
          </Button>
        </p>
      )}
      {checkedAt && (
        <p className="mb-4 flex items-center gap-1 text-sm text-text-secondary">
          관계 확인 시점 <span className="text-text-primary tabular-nums">{formatKst(checkedAt)}</span>
          <IconHint icon={Info} label="관계 확인 시점">
            <p>
              {verifiedAt
                ? "기준 관계를 검증한 시각이에요."
                : "검증을 통과한 자료를 이 시각 기준으로 확인했어요."}{" "}
              아래 문서마다 적힌 발행 시각과는 달라요.
            </p>
          </IconHint>
        </p>
      )}
      {body}
    </Sheet>
  );
}
