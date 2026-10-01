// 어느 화면에서든 열 수 있는 두 개의 창:
//  - 근거 창(UI-09, 요구 24): 인용문 원문과 검증 상태. 문서마다 발행 시각을, 창 위에 관계 확인 시점을 따로 보인다
//    (기준 관계의 검증 시각이 있으면 그것, 없으면 검증을 통과한 자료의 기준 시각). 데이터 출처(datasetKind)는 여기(아이콘)와 앱 헤더에서만 밝힌다.
//  - AI 질문 창(UI-10): 예시 답변. 근거가 부족하면 답변을 보류한다.
// 모바일에서 노드 시트 위에 열면 그 위에 쌓이고, 닫으면 아래 시트로 돌아간다(Radix 대화상자 스택).
// 지도에서 연 근거 창(request.map)은 인용마다 [지도에서 보기] 토글을 두고, 누른 인용을 mapHighlight로 내보낸다.
// 지도(GraphExplorer)가 이 값을 읽어 강조하고, 근거 창을 닫으면 강조가 풀린다.
import { Info } from "lucide-react";
import { createContext, useContext, useMemo, useState, type ReactNode } from "react";
import { useEvent, useEvidenceItems } from "@/api/queries";
import { EvidenceList, type EvidenceMapLink } from "@/components/domain/evidence";
import { SourceIndicator } from "@/components/domain/source-indicator";
import { EmptyState, ErrorState, SkeletonRows } from "@/components/ui/feedback";
import { Sheet } from "@/components/ui/dialog";
import { IconHint } from "@/components/ui/icon-hint";
import { formatKst } from "@/lib/labels";
import type { EvidenceHighlight } from "@/lib/graph-view";
import { ChatDrawer, type ChatContext } from "./chat-drawer";

export interface EvidenceRequest {
  /** 창 상단에 보여줄 사건·관계 이름 */
  title: string;
  evidenceIds?: string[];
  /** 근거 id를 모를 때 사건 id를 주면 사건 상세에서 근거 목록을 가져온다. */
  eventId?: string;
  /** 지도에서 열었을 때: 인용을 지도에서 강조할 수 있다. issueId는 해당 간선이 없을 때 대신 강조할 사건. */
  map?: { issueId?: string };
  /** 기준 관계를 검증한 시각(있을 때만). 없으면 근거 응답의 자료 기준 시각을 관계 확인 시점으로 보인다. */
  checkedAt?: string | null;
}

interface OverlayApi {
  openEvidence: (request: EvidenceRequest) => void;
  openChat: (context: ChatContext) => void;
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

  const api = useMemo<OverlayApi>(
    () => ({
      openEvidence: (request) => {
        setEvidence(request);
        setEvidenceOpen(true);
        setMapHighlight(null);
      },
      openChat: (context) => {
        setChat(context);
        setChatOpen(true);
      },
      mapHighlight,
      evidenceOpen,
      chatOpen,
    }),
    [mapHighlight, evidenceOpen, chatOpen],
  );

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
      {chat && <ChatDrawer key={chat.targets.map((t) => t.id).join(",")} context={chat} open={chatOpen} onOpenChange={setChatOpen} />}
    </OverlayContext.Provider>
  );
}

export function useOverlays() {
  const api = useContext(OverlayContext);
  if (!api) throw new Error("useOverlays는 OverlayProvider 안에서만 쓸 수 있어요.");
  return api;
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
  const items = useEvidenceItems(ids);
  const loaded = items.flatMap((q) => (q.data ? [q.data] : []));
  const failed = items.find((q) => q.isError);
  const loading = (needsEvent && event.isPending) || items.some((q) => q.isPending);

  let body: ReactNode;
  if (needsEvent && event.isError) {
    body = <ErrorState error={event.error} title="사건 정보를 불러오지 못했어요" onRetry={() => void event.refetch()} />;
  } else if (loading) {
    body = <SkeletonRows count={2} label="근거 문서를 불러오고 있어요" />;
  } else if (failed) {
    body = (
      <div className="flex flex-col gap-4">
        <ErrorState
          error={failed.error}
          title={`근거 ${ids.length}건 중 ${ids.length - loaded.length}건을 불러오지 못했어요`}
          onRetry={() => items.forEach((q) => q.isError && void q.refetch())}
          compact
        />
        {loaded.length > 0 && <EvidenceList items={loaded} mapLink={mapLink} />}
      </div>
    );
  } else if (ids.length === 0) {
    body = <EmptyState title="연결된 근거 문서가 없어요" />;
  } else {
    body = <EvidenceList items={loaded} mapLink={mapLink} />;
  }
  const checkedAt = request.checkedAt ?? loaded[0]?.metadata.asOf;

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
      {checkedAt && (
        <p className="mb-4 flex items-center gap-1 text-sm text-text-secondary">
          관계 확인 시점 <span className="text-text-primary tabular-nums">{formatKst(checkedAt)}</span>
          <IconHint icon={Info} label="관계 확인 시점">
            <p>
              {request.checkedAt
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
