// 회원 관리(요구 78): 회원 목록(가명 id·가린 이메일·가입 방식·활동·상태). 실명·이메일 원문은 서버가 내보내지 않는다.
import { Users } from "lucide-react";
import { useDeferredValue, useState } from "react";
import { Link } from "react-router";
import { Button } from "@/components/ui/button";
import { EmptyState, ErrorState, SkeletonRows } from "@/components/ui/feedback";
import { Input } from "@/components/ui/input";
import { Segmented } from "@/components/ui/segmented";
import { useMembers, type MemberFilters } from "../api";
import { formatCount } from "../format";
import { memberStatusSpec, Status } from "../labels";
import { AdminPageHeader, DataTable, KstTime, Td, Th } from "../ui";

export function signupLabel(method: string): string {
  if (method === "email") return "이메일";
  return method === "social:mock" ? "소셜(개발용 모의)" : `소셜(${method.replace(/^social:/, "")})`;
}

const statusOptions: { value: MemberFilters["status"]; label: string }[] = [
  { value: "all", label: "전체" },
  { value: "active", label: "정상" },
  { value: "blocked", label: "차단됨" },
];

export function AdminMembersPage() {
  const [status, setStatus] = useState<MemberFilters["status"]>("all");
  const [query, setQuery] = useState("");
  const deferred = useDeferredValue(query);
  const members = useMembers({ status, q: deferred });
  const rows = members.data?.pages.flatMap((page) => page.items) ?? [];
  const counts = members.data?.pages[0]?.counts;

  return (
    <>
      <AdminPageHeader title="회원 관리" icon={Users} />
      <div className="flex flex-wrap items-center gap-3">
        <Segmented aria-label="회원 상태" value={status} onValueChange={setStatus} options={statusOptions} />
        <Input
          label="회원 검색"
          hideLabel
          variant="search"
          placeholder="가명 id·가린 이메일로 찾기"
          value={query}
          onChange={(e) => setQuery(e.target.value)}
          onClear={() => setQuery("")}
          className="w-80"
        />
        {counts && (
          <p className="text-sm text-text-secondary tabular-nums">
            전체 {formatCount(counts.all)}명 · 정상 {formatCount(counts.active)} · 차단 {formatCount(counts.blocked)}
          </p>
        )}
      </div>
      {members.isPending && <SkeletonRows count={5} label="회원을 불러오고 있어요" />}
      {members.isError && <ErrorState error={members.error} title="회원을 불러오지 못했어요" onRetry={() => void members.refetch()} />}
      {members.isSuccess && rows.length === 0 && <EmptyState title="조건에 맞는 회원이 없어요" />}
      {rows.length > 0 && (
        <DataTable caption="회원 목록">
          <thead>
            <tr>
              <Th>회원(가명 id)</Th>
              <Th>이메일(가림)</Th>
              <Th>가입 방식</Th>
              <Th>가입</Th>
              <Th>최근 활동</Th>
              <Th className="text-right">로그인 세션</Th>
              <Th className="text-right">그래프 선택</Th>
              <Th className="text-right">AI 질문</Th>
              <Th className="text-right">브리핑 조회</Th>
              <Th>상태</Th>
            </tr>
          </thead>
          <tbody>
            {rows.map((row) => (
              <tr key={row.id}>
                <Td className="font-mono text-sm whitespace-nowrap">
                  <Link to={`/admin/members/${encodeURIComponent(row.id)}`} className="font-semibold text-brand-primary underline-offset-4 hover:underline">
                    {row.id}
                  </Link>
                </Td>
                <Td className="whitespace-nowrap text-text-secondary">{row.emailMasked}</Td>
                <Td className="whitespace-nowrap">{signupLabel(row.signupMethod)}</Td>
                <Td>
                  <KstTime value={row.createdAt} />
                </Td>
                <Td>
                  <KstTime value={row.lastActiveAt} />
                </Td>
                <Td className="text-right">{formatCount(row.activity.sessions)}</Td>
                <Td className="text-right">{formatCount(row.activity.graphSelections)}</Td>
                <Td className="text-right">{formatCount(row.activity.aiQuestions)}</Td>
                <Td className="text-right">{formatCount(row.activity.briefingViews)}</Td>
                <Td>
                  <Status spec={memberStatusSpec[row.status]} />
                </Td>
              </tr>
            ))}
          </tbody>
        </DataTable>
      )}
      {members.hasNextPage && (
        <Button variant="secondary" className="self-start" loading={members.isFetchingNextPage} onClick={() => void members.fetchNextPage()}>
          더 보기
        </Button>
      )}
    </>
  );
}
