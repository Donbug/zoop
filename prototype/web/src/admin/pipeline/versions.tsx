// 그래프 버전(요구 76): 사용자에게 지금 보이는 버전, 원장에서 새 버전 게시, 이전 버전으로 되돌리기, 전환 이력.
import { CircleCheck, GitBranch, History, RotateCcw, Upload } from "lucide-react";
import { useState } from "react";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { ErrorState, SkeletonRows } from "@/components/ui/feedback";
import { useToast } from "@/components/ui/toast";
import { useActivateVersion, useGraphVersions, usePublishVersion, type GraphVersion } from "../api";
import { formatCount } from "../format";
import { Status, versionGraphDbSpec } from "../labels";
import { ReasonDialog } from "../reason-dialog";
import { AdminSection, DataTable, KstTime, StatusLabel, Td, Th } from "../ui";

const activationActionLabel: Record<string, string> = { publish: "게시", activate: "전환", seed: "최초 등록" };

export function VersionsPanel() {
  const versions = useGraphVersions();
  const publish = usePublishVersion();
  const activate = useActivateVersion();
  const toast = useToast();
  const [publishOpen, setPublishOpen] = useState(false);
  const [target, setTarget] = useState<GraphVersion | null>(null);

  if (versions.isPending) return <SkeletonRows count={4} label="그래프 버전을 불러오고 있어요" />;
  if (versions.isError) return <ErrorState error={versions.error} title="그래프 버전을 불러오지 못했어요" onRetry={() => void versions.refetch()} />;
  const data = versions.data;

  return (
    <div className="flex flex-col gap-6">
      <AdminSection
        title="그래프 버전"
        icon={GitBranch}
        id="versions-title"
        actions={
          <Button onClick={() => setPublishOpen(true)}>
            <Upload aria-hidden="true" />
            원장에서 새 버전 게시
          </Button>
        }
      >
        <DataTable caption="그래프 버전 목록">
          <thead>
            <tr>
              <Th>버전</Th>
              <Th>사용자 표시</Th>
              <Th>만든 시각</Th>
              <Th>출처</Th>
              <Th className="text-right">이슈</Th>
              <Th className="text-right">관계</Th>
              <Th>GraphDB</Th>
              <Th>사유</Th>
              <Th>
                <span className="sr-only">행동</span>
              </Th>
            </tr>
          </thead>
          <tbody>
            {data.items.map((v) => (
              <tr key={v.id} className={v.active ? "bg-surface-selected" : undefined}>
                <Td className="font-semibold whitespace-nowrap">
                  {v.id}
                  {v.synthetic && <Badge className="ml-2">합성</Badge>}
                </Td>
                <Td>{v.active ? <StatusLabel icon={CircleCheck} label="표시 중" tone="success" /> : <span className="text-text-tertiary">–</span>}</Td>
                <Td>
                  <KstTime value={v.createdAt} />
                </Td>
                <Td className="max-w-56 truncate text-text-secondary" title={v.sourceLabel}>
                  {v.sourceLabel}
                </Td>
                <Td className="text-right">{formatCount(v.issueCount)}</Td>
                <Td className="text-right">{formatCount(v.relationCount)}</Td>
                <Td>
                  <Status spec={versionGraphDbSpec[v.graphDb.status]} />
                </Td>
                <Td className="max-w-56 truncate text-text-secondary" title={v.reason ?? undefined}>
                  {v.reason ?? "–"}
                </Td>
                <Td className="text-right whitespace-nowrap">
                  {!v.active && (
                    <Button variant="secondary" size="sm" onClick={() => setTarget(v)} aria-label={`${v.id}로 되돌리기`}>
                      <RotateCcw aria-hidden="true" />
                      되돌리기
                    </Button>
                  )}
                </Td>
              </tr>
            ))}
          </tbody>
        </DataTable>
      </AdminSection>

      <AdminSection title="전환 이력" icon={History} id="activations-title">
        <DataTable caption="그래프 버전 전환 이력">
          <thead>
            <tr>
              <Th>시각</Th>
              <Th>동작</Th>
              <Th>버전</Th>
              <Th>관리자</Th>
              <Th>사유</Th>
            </tr>
          </thead>
          <tbody>
            {data.activations.map((a, i) => (
              <tr key={`${a.versionId}-${a.at}-${i}`}>
                <Td>
                  <KstTime value={a.at} seconds />
                </Td>
                <Td>{activationActionLabel[a.action] ?? a.action}</Td>
                <Td className="whitespace-nowrap tabular-nums">
                  {a.previousVersionId ? `${a.previousVersionId} → ` : ""}
                  {a.versionId}
                </Td>
                <Td className="text-text-secondary">{a.adminEmail ?? "시스템"}</Td>
                <Td className="text-text-secondary">{a.reason ?? "–"}</Td>
              </tr>
            ))}
          </tbody>
        </DataTable>
      </AdminSection>

      <ReasonDialog
        open={publishOpen}
        onOpenChange={(open) => {
          setPublishOpen(open);
          if (!open) publish.reset();
        }}
        title="새 그래프 버전 게시"
        target={<p>지금 원장 내용을 새 버전으로 저장하고 사용자에게 바로 보여 줘요. 현재 표시 중: {data.activeVersionId}</p>}
        reasonLabel="게시 사유"
        confirmLabel="게시하기"
        confirmIcon={<Upload aria-hidden="true" />}
        pending={publish.isPending}
        error={publish.error}
        onConfirm={({ reason }) =>
          publish.mutate(reason, {
            onSuccess: (result) => {
              setPublishOpen(false);
              toast({ tone: "success", title: `${result.version.id}을 게시했어요` });
            },
          })
        }
      />
      <ReasonDialog
        key={target?.id ?? "none"}
        open={target !== null}
        onOpenChange={(open) => {
          if (!open) {
            setTarget(null);
            activate.reset();
          }
        }}
        title="그래프 버전 되돌리기"
        target={
          <p>
            사용자 그래프를 <strong className="font-semibold">{data.activeVersionId}</strong>에서 <strong className="font-semibold">{target?.id}</strong>로 바꿔요. 검수 기록(허용·거부)은 그대로 덮어 적용돼요.
          </p>
        }
        reasonLabel="되돌리는 사유"
        confirmLabel={`${target?.id ?? ""}로 되돌리기`}
        confirmIcon={<RotateCcw aria-hidden="true" />}
        pending={activate.isPending}
        error={activate.error}
        onConfirm={({ reason }) =>
          target &&
          activate.mutate(
            { id: target.id, reason },
            {
              onSuccess: (result) => {
                setTarget(null);
                toast({ tone: "success", title: result.idempotent ? "이미 표시 중인 버전이에요" : `${result.activeVersionId}로 되돌렸어요` });
              },
            },
          )
        }
      />
    </div>
  );
}
