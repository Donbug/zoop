// 자동 검수 규칙(요구 76): 켜짐·꺼짐, 다루는 후보 수, 사용자 그래프에 게시한 사건 수, 전환 이력.
// 켜고 끄면 사용자 그래프가 바로 바뀌므로 사유를 받아야만 전환한다(감사 로그에 남는다).
import { CircleCheck, History, ListChecks, PauseCircle, Power } from "lucide-react";
import { useState } from "react";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { ErrorState, SkeletonRows } from "@/components/ui/feedback";
import { IconHint } from "@/components/ui/icon-hint";
import { useToast } from "@/components/ui/toast";
import { usePipelineRules, useSwitchRule, type ReviewRule } from "../api";
import { formatCount } from "../format";
import { ReasonDialog } from "../reason-dialog";
import { AdminSection, KstTime, StatusLabel } from "../ui";

export function RulesPanel() {
  const rules = usePipelineRules();
  const change = useSwitchRule();
  const toast = useToast();
  const [target, setTarget] = useState<ReviewRule | null>(null);
  const turningOn = target ? !target.enabled : false;

  const submit = ({ reason }: { reason: string }) => {
    if (!target) return;
    change.mutate(
      { id: target.id, enabled: turningOn, reason },
      {
        onSuccess: (result) => {
          setTarget(null);
          toast({
            tone: "success",
            title: result.idempotent ? "이미 같은 상태예요" : turningOn ? "규칙을 켰어요" : "규칙을 껐어요",
            description: `사용자 그래프의 규칙 게시 사건 ${formatCount(result.rule.publishedEvents)}건`,
          });
        },
      },
    );
  };

  return (
    <AdminSection title="자동 검수 규칙" icon={ListChecks} id="rules-title">
      {rules.isPending && <SkeletonRows count={1} label="규칙을 불러오고 있어요" />}
      {rules.isError && <ErrorState error={rules.error} title="규칙을 불러오지 못했어요" onRetry={() => void rules.refetch()} compact />}
      {rules.data && (
        <ul className="flex flex-col divide-y divide-border-subtle">
          {rules.data.items.map((rule) => (
            <li key={rule.id} className="flex items-start gap-6 py-3">
              <div className="flex min-w-0 flex-1 flex-col gap-1.5">
                <p className="flex flex-wrap items-center gap-x-3 gap-y-1">
                  <span className="text-base font-semibold text-text-primary">{rule.title}</span>
                  <Badge>{rule.id}</Badge>
                  {rule.enabled ? <StatusLabel icon={CircleCheck} label="켜짐" tone="success" /> : <StatusLabel icon={PauseCircle} label="꺼짐" tone="warning" />}
                </p>
                <p className="text-base text-text-primary">{rule.summary}</p>
                <p className="flex flex-wrap items-center gap-x-5 gap-y-1 text-sm text-text-secondary tabular-nums">
                  <span>다루는 보류 후보 {formatCount(rule.eligible)}건</span>
                  <span>
                    사용자 그래프에 사건 {formatCount(rule.publishedEvents)}건 (후보 {formatCount(rule.publishedCandidates)}건)
                  </span>
                  {rule.changedAt ? (
                    <span>
                      <KstTime value={rule.changedAt} /> {rule.changedBy} · {rule.enabled ? "켬" : "끔"} · 사유: {rule.reason}
                    </span>
                  ) : (
                    <span>기본값({rule.defaultEnabled ? "켜짐" : "꺼짐"}) 그대로예요</span>
                  )}
                </p>
              </div>
              <div className="flex shrink-0 items-center gap-1">
                {rule.history.length > 0 && (
                  <IconHint icon={History} label={`전환 이력 ${rule.history.length}건`} size="md">
                    <ol className="flex flex-col gap-2">
                      {rule.history.map((h) => (
                        <li key={h.id} className="flex flex-col">
                          <span className="font-medium text-text-primary">
                            {h.enabled ? "켬" : "끔"} · <KstTime value={h.changedAt} />
                          </span>
                          <span>
                            {h.adminEmail}: {h.reason}
                          </span>
                        </li>
                      ))}
                    </ol>
                  </IconHint>
                )}
                <Button variant="secondary" onClick={() => setTarget(rule)}>
                  <Power aria-hidden="true" />
                  {rule.enabled ? "규칙 끄기" : "규칙 켜기"}
                </Button>
              </div>
            </li>
          ))}
        </ul>
      )}

      <ReasonDialog
        key={target ? `${target.id}-${turningOn ? "on" : "off"}` : "closed"}
        open={target !== null}
        onOpenChange={(open) => {
          if (!open) {
            setTarget(null);
            change.reset();
          }
        }}
        title={turningOn ? "규칙 켜기" : "규칙 끄기"}
        target={
          <p className="font-medium">
            {target?.title} <span className="text-sm font-normal text-text-secondary">{target?.id}</span>
          </p>
        }
        confirmLabel={turningOn ? "켜고 사용자 그래프에 넣기" : "끄고 사용자 그래프에서 빼기"}
        confirmIcon={<Power aria-hidden="true" />}
        pending={change.isPending}
        error={change.error}
        onConfirm={submit}
      >
        <p className="text-sm text-text-secondary">
          {turningOn
            ? `관리자가 결정하지 않은 보류 후보 중 이 규칙이 다루는 후보가 사건으로 게시돼요. 비운 역할은 ‘역할 미확인’으로 보여요.`
            : `이 규칙으로 게시된 사건 ${formatCount(target?.publishedEvents ?? 0)}건이 사용자 그래프에서 바로 빠져요. 관리자가 직접 허용한 후보는 그대로예요.`}{" "}
          사유는 감사 로그에 남아요.
        </p>
      </ReasonDialog>
    </AdminSection>
  );
}
