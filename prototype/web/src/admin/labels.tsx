// 관리자 화면 상태 → 아이콘 + 한국어 라벨. 같은 상태는 모든 화면에서 같은 아이콘을 쓴다.
import {
  Ban,
  CircleCheck,
  CircleDashed,
  CircleHelp,
  CircleX,
  Clock,
  Loader2,
  PauseCircle,
  TriangleAlert,
  type LucideIcon,
} from "lucide-react";
import type { CandidateStatus, GraphDbStatus, Job, Round } from "./api";
import { StatusLabel, type StatusTone } from "./ui";

interface StatusSpec {
  icon: LucideIcon;
  label: string;
  tone: StatusTone;
  spin?: boolean;
}

export const candidateStatusSpec: Record<CandidateStatus, StatusSpec> = {
  ALLOW: { icon: CircleCheck, label: "통과", tone: "success" },
  HOLD: { icon: PauseCircle, label: "보류", tone: "warning" },
  REJECT: { icon: CircleX, label: "폐기", tone: "error" },
};

export const graphDbStatusSpec: Record<GraphDbStatus["status"], StatusSpec> = {
  reflected: { icon: CircleCheck, label: "반영됨", tone: "success" },
  pending: { icon: Clock, label: "반영 대기", tone: "warning" },
  mismatch: { icon: TriangleAlert, label: "불일치", tone: "error" },
  unavailable: { icon: CircleHelp, label: "확인 불가", tone: "neutral" },
};

export const versionGraphDbSpec: Record<string, StatusSpec> = {
  reflected: graphDbStatusSpec.reflected,
  pending: graphDbStatusSpec.pending,
  unknown: { icon: CircleHelp, label: "모름", tone: "neutral" },
};

export const jobStatusSpec: Record<Job["status"], StatusSpec> = {
  queued: { icon: Clock, label: "대기", tone: "neutral" },
  running: { icon: Loader2, label: "실행 중", tone: "progress", spin: true },
  succeeded: { icon: CircleCheck, label: "성공", tone: "success" },
  failed: { icon: CircleX, label: "실패", tone: "error" },
  cancelled: { icon: Ban, label: "취소됨", tone: "neutral" },
};

export const roundStatusSpec: Record<Round["status"], StatusSpec> = {
  scheduled: { icon: CircleDashed, label: "예정", tone: "neutral" },
  missing: { icon: TriangleAlert, label: "지연(회차 없음)", tone: "warning" },
  generating: { icon: Loader2, label: "생성 중", tone: "progress", spin: true },
  verifying: { icon: Loader2, label: "검증 중", tone: "progress", spin: true },
  published: { icon: CircleCheck, label: "발행됨", tone: "success" },
  failed: { icon: CircleX, label: "실패", tone: "error" },
  suspended: { icon: Ban, label: "제공 중단", tone: "error" },
};

export const stageStatusSpec: Record<Round["stages"]["generate"]["status"], StatusSpec> = {
  pending: { icon: CircleDashed, label: "대기", tone: "neutral" },
  running: { icon: Loader2, label: "진행 중", tone: "progress", spin: true },
  done: { icon: CircleCheck, label: "완료", tone: "success" },
  failed: { icon: CircleX, label: "실패", tone: "error" },
  skipped: { icon: Ban, label: "건너뜀", tone: "neutral" },
};

export function Status({ spec, className }: { spec: StatusSpec | undefined; className?: string }) {
  if (!spec) return <StatusLabel icon={CircleHelp} label="알 수 없음" className={className} />;
  return <StatusLabel icon={spec.icon} label={spec.label} tone={spec.tone} spin={spec.spin} className={className} />;
}

export const memberStatusSpec: Record<"active" | "blocked", StatusSpec> = {
  active: { icon: CircleCheck, label: "정상", tone: "success" },
  blocked: { icon: Ban, label: "차단됨", tone: "error" },
};

export const editionLabel = { morning: "출근", evening: "퇴근" } as const;

export const jobKindLabel: Record<string, string> = {
  "flush-graph": "GraphDB 반영 재시도",
  "retry-model-errors": "모델 오류 재처리",
};

export const auditActionLabel: Record<string, string> = {
  "auth.login": "로그인",
  "auth.login_failed": "로그인 실패",
  "auth.logout": "로그아웃",
  "review.decide": "검수 결정",
  "graph.publish": "그래프 게시",
  "graph.activate": "그래프 버전 전환",
  "graph.seed": "그래프 최초 등록",
  "job.create": "작업 실행",
  "job.retry": "작업 재시도",
  "job.cancel": "작업 취소",
  "job.recover": "작업 복구",
  "briefing.generate": "브리핑 생성",
  "briefing.reprocess": "브리핑 재처리",
  "briefing.correct": "브리핑 정정",
  "briefing.suspend": "브리핑 제공 중단",
  "briefing.resume": "브리핑 제공 재개",
  "transcript.view": "AI 대화록 열람",
  "member.block": "회원 차단",
  "member.unblock": "회원 차단 해제",
};
