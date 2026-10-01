// 감사 로그: 로그인·검수·게시·작업·브리핑 운영 기록(최신 먼저). 동작 종류 필터 + 검색.
import { CircleCheck, CircleX, ScrollText, ShieldAlert } from "lucide-react";
import { useDeferredValue, useState } from "react";
import { Button } from "@/components/ui/button";
import { EmptyState, ErrorState, SkeletonRows } from "@/components/ui/feedback";
import { Input } from "@/components/ui/input";
import { Select } from "@/components/ui/select";
import { useAuditLog } from "../api";
import { auditActionLabel } from "../labels";
import { AdminPageHeader, DataTable, KstTime, StatusLabel, Td, Th } from "../ui";

const outcomeSpec = {
  ok: { icon: CircleCheck, label: "완료", tone: "success" },
  denied: { icon: ShieldAlert, label: "거부됨", tone: "warning" },
  failed: { icon: CircleX, label: "실패", tone: "error" },
} as const;

const actionOptions = [{ value: "all", label: "모든 동작" }, ...Object.entries(auditActionLabel).map(([value, label]) => ({ value, label }))];

export function AdminAuditPage() {
  const [action, setAction] = useState("all");
  const [query, setQuery] = useState("");
  const deferredQuery = useDeferredValue(query);
  const audit = useAuditLog({ action: action === "all" ? "" : action, q: deferredQuery });
  const rows = audit.data?.pages.flatMap((page) => page.items) ?? [];

  return (
    <>
      <AdminPageHeader title="감사 로그" icon={ScrollText} />
      <div className="flex flex-wrap items-end gap-3">
        <Select label="동작" hideLabel value={action} onValueChange={setAction} options={actionOptions} className="w-56" />
        <Input
          label="감사 로그 검색"
          hideLabel
          variant="search"
          placeholder="대상·사유·관리자로 찾기"
          value={query}
          onChange={(e) => setQuery(e.target.value)}
          onClear={() => setQuery("")}
          className="w-80"
        />
      </div>
      {audit.isPending && <SkeletonRows count={6} label="감사 로그를 불러오고 있어요" />}
      {audit.isError && <ErrorState error={audit.error} title="감사 로그를 불러오지 못했어요" onRetry={() => void audit.refetch()} />}
      {audit.isSuccess && rows.length === 0 && <EmptyState title="조건에 맞는 기록이 없어요" />}
      {rows.length > 0 && (
        <DataTable caption="감사 로그">
          <thead>
            <tr>
              <Th>시각</Th>
              <Th>주체</Th>
              <Th>동작</Th>
              <Th>대상</Th>
              <Th>결과</Th>
              <Th>사유</Th>
            </tr>
          </thead>
          <tbody>
            {rows.map((row) => {
              const outcome = outcomeSpec[row.outcome];
              return (
                <tr key={row.id}>
                  <Td>
                    <KstTime value={row.at} seconds />
                  </Td>
                  <Td className="text-text-secondary">{row.actorKind === "system" ? "시스템" : (row.actorEmail ?? row.actorId)}</Td>
                  <Td className="whitespace-nowrap">{auditActionLabel[row.action] ?? row.action}</Td>
                  <Td className="max-w-72 text-sm break-all text-text-secondary">
                    {row.targetType}
                    {row.targetId ? ` · ${row.targetId}` : ""}
                  </Td>
                  <Td>
                    <StatusLabel icon={outcome.icon} label={outcome.label} tone={outcome.tone} />
                  </Td>
                  <Td className="max-w-96">{row.reason ?? <span className="text-text-tertiary">–</span>}</Td>
                </tr>
              );
            })}
          </tbody>
        </DataTable>
      )}
      {audit.hasNextPage && (
        <Button variant="secondary" className="self-start" loading={audit.isFetchingNextPage} onClick={() => void audit.fetchNextPage()}>
          기록 더 보기
        </Button>
      )}
    </>
  );
}
