// 회원 상세(요구 78): 활동 요약, 차단/차단 해제(사유 필수·확인 창·감사 로그), 조치 이력.
// 차단하면 열려 있는 세션이 바로 끝나고 다음 요청에서 로그아웃·안내가 나오며, 다시 로그인할 수 없다.
import { ArrowLeft, Ban, BookOpenCheck, CircleCheck, Clock, GraduationCap, History, KeyRound, ShieldCheck, Sparkles, Star, ThumbsDown, ThumbsUp, UserRound, Wallet, Workflow, Zap } from "lucide-react";
import { useState } from "react";
import { Link, useParams } from "react-router";
import { ApiError } from "@/api/client";
import { Button } from "@/components/ui/button";
import { EmptyState, ErrorState, SkeletonRows } from "@/components/ui/feedback";
import { useToast } from "@/components/ui/toast";
import { useMember, useSetMemberStatus } from "../api";
import { formatCount } from "../format";
import { memberStatusSpec, Status } from "../labels";
import { ReasonDialog } from "../reason-dialog";
import { AdminPageHeader, AdminSection, DataTable, KstTime, Metric, Td, Th } from "../ui";
import { signupLabel } from "./members";

const actionLabel = { "member.block": "차단", "member.unblock": "차단 해제" } as const;

export function AdminMemberDetailPage() {
  const { id = "" } = useParams();
  const member = useMember(id);
  const setStatus = useSetMemberStatus();
  const toast = useToast();
  const [dialog, setDialog] = useState<"block" | "unblock" | null>(null);
  const data = member.data;
  const row = data?.member;

  return (
    <>
      <div>
        <Button variant="ghost" size="sm" asChild>
          <Link to="/admin/members">
            <ArrowLeft aria-hidden="true" />
            회원 목록
          </Link>
        </Button>
      </div>
      <AdminPageHeader
        title={row ? `회원 ${row.id}` : "회원 상세"}
        icon={UserRound}
        actions={
          row &&
          (row.status === "active" ? (
            <Button variant="secondary" onClick={() => setDialog("block")}>
              <Ban aria-hidden="true" />
              차단
            </Button>
          ) : (
            <Button variant="secondary" onClick={() => setDialog("unblock")}>
              <ShieldCheck aria-hidden="true" />
              차단 해제
            </Button>
          ))
        }
      />
      {member.isPending && <SkeletonRows count={3} label="회원 정보를 불러오고 있어요" />}
      {member.isError &&
        (member.error instanceof ApiError && member.error.status === 404 ? (
          <EmptyState title="찾는 회원이 없어요" action={<Link to="/admin/members" className="font-medium text-brand-primary hover:underline">회원 목록으로 가기</Link>} />
        ) : (
          <ErrorState error={member.error} title="회원 정보를 불러오지 못했어요" onRetry={() => void member.refetch()} />
        ))}
      {data && row && (
        <>
          <p className="flex flex-wrap items-center gap-x-4 gap-y-1 text-base">
            <Status spec={memberStatusSpec[row.status]} className="text-base" />
            <span className="text-text-secondary">{row.emailMasked}</span>
          </p>
          <dl className="grid grid-cols-4 gap-x-6 gap-y-4 border-y border-border-subtle py-4">
            <Metric icon={KeyRound} label="가입 방식" value={signupLabel(row.signupMethod)} />
            <Metric icon={Clock} label="가입" value={<KstTime value={row.createdAt} />} />
            <Metric icon={Clock} label="최근 활동" value={<KstTime value={row.lastActiveAt} />} detail="1분 단위로 기록돼요" />
            <Metric icon={Workflow} label="로그인 세션(누적)" value={`${formatCount(row.activity.sessions)}회`} />
            <Metric icon={Zap} label="그래프 선택" value={`${formatCount(row.activity.graphSelections)}회`} detail="노드·간선" />
            <Metric icon={Sparkles} label="AI 질문" value={`${formatCount(row.activity.aiQuestions)}회`} />
            <Metric icon={BookOpenCheck} label="브리핑 조회" value={`${formatCount(row.activity.briefingViews)}회`} />
            <Metric
              icon={ThumbsUp}
              label="평가"
              value={
                <span className="inline-flex items-center gap-3">
                  <span className="inline-flex items-center gap-1">
                    <ThumbsUp className="size-4" aria-hidden="true" />
                    {formatCount(data.feedbackUp)}
                  </span>
                  <span className="inline-flex items-center gap-1">
                    <ThumbsDown className="size-4" aria-hidden="true" />
                    {formatCount(data.feedbackDown)}
                  </span>
                </span>
              }
              detail="좋아요 / 싫어요"
            />
            <Metric icon={CircleCheck} label="초기 설정" value={data.onboardingCompleted ? "완료" : "미완료"} />
            <Metric icon={GraduationCap} label="튜토리얼" value={data.tutorialCompleted ? "완료" : "미완료"} />
            <Metric icon={Star} label="관심 종목" value={`${formatCount(data.watchlistCount)}개`} detail="종목 이름은 보이지 않아요" />
            <Metric icon={Wallet} label="가상 보유 종목" value={`${formatCount(data.holdingCount)}개`} detail={data.accountConnected ? "가상 계좌 연결됨" : "가상 계좌 없음"} />
          </dl>
          <AdminSection title="차단·해제 이력" icon={History} id="member-history">
            {data.history.length === 0 ? (
              <p className="py-2 text-base text-text-secondary">차단하거나 해제한 기록이 없어요.</p>
            ) : (
              <DataTable caption="차단·해제 이력">
                <thead>
                  <tr>
                    <Th>시각</Th>
                    <Th>조치</Th>
                    <Th>사유</Th>
                    <Th>관리자</Th>
                  </tr>
                </thead>
                <tbody>
                  {data.history.map((entry, index) => (
                    <tr key={`${entry.at}-${index}`}>
                      <Td>
                        <KstTime value={entry.at} seconds />
                      </Td>
                      <Td className="whitespace-nowrap">{actionLabel[entry.action]}</Td>
                      <Td className="max-w-96">{entry.reason ?? <span className="text-text-tertiary">–</span>}</Td>
                      <Td className="text-text-secondary">{entry.adminEmail ?? "–"}</Td>
                    </tr>
                  ))}
                </tbody>
              </DataTable>
            )}
          </AdminSection>
          <ReasonDialog
            key={dialog ?? "closed"}
            open={dialog !== null}
            onOpenChange={(open) => {
              if (!open) {
                setDialog(null);
                setStatus.reset();
              }
            }}
            title={dialog === "unblock" ? "회원 차단 해제" : "회원 차단"}
            target={
              dialog === "unblock" ? (
                <p>
                  <strong className="font-semibold">{row.id}</strong>({row.emailMasked})의 차단을 풀어요. 이 회원은 다시 로그인할 수 있어요.
                </p>
              ) : (
                <p>
                  <strong className="font-semibold">{row.id}</strong>({row.emailMasked})을 차단해요. 열려 있는 모든 세션이 지금 끝나고, 다시 로그인할 수 없어요.
                </p>
              )
            }
            reasonLabel={dialog === "unblock" ? "해제 사유(감사 로그에 남아요)" : "차단 사유(감사 로그에 남아요)"}
            confirmLabel={dialog === "unblock" ? "차단 해제하기" : "차단하기"}
            confirmIcon={dialog === "unblock" ? <ShieldCheck aria-hidden="true" /> : <Ban aria-hidden="true" />}
            pending={setStatus.isPending}
            error={setStatus.error}
            onConfirm={({ reason }) =>
              dialog &&
              setStatus.mutate(
                { id: row.id, action: dialog, reason },
                {
                  onSuccess: (result) => {
                    setDialog(null);
                    toast({
                      tone: "success",
                      title: !result.changed ? "이미 같은 상태예요" : dialog === "block" ? `${row.id}을 차단했어요` : `${row.id}의 차단을 풀었어요`,
                    });
                  },
                },
              )
            }
          />
        </>
      )}
    </>
  );
}
