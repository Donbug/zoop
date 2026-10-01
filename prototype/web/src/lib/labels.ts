import { ApiError, type Schemas } from "@/api/client";

export type RelationType = Schemas["GraphEdge"]["relationType"];
export type DatasetKind = Schemas["Metadata"]["datasetKind"];
export type TimePrecision = Schemas["EventSummary"]["timePrecision"];

/** 시스템 용어 → 쉬운 말 (design-direction §7). 화면에는 항상 오른쪽 값을 쓴다. */
export const relationLabel: Record<RelationType, string> = {
  INVOLVES: "직접 관련",
  STRUCTURALLY_RELATED_TO: "구조적 관련",
  FOLLOWS: "후속 사건",
  SHARES_ISSUE: "사건 공유",
};

export const relationDescription: Record<RelationType, string> = {
  INVOLVES: "사건 기사에 이 기업이 직접 등장해요.",
  STRUCTURALLY_RELATED_TO: "기존에 등록된 협력/공급 기준 관계를 바탕으로 연결된 흐름이에요.",
  FOLLOWS: "앞선 사건 뒤에 이어서 보도된 사건이에요.",
  SHARES_ISSUE: "두 기업 사이에 직접적인 계약이 체결된 것은 아니에요. 같은 이슈에서 함께 다뤄진 관계예요.",
};

/** 데이터 출처 라벨. 헤더 SourceIndicator와 근거 창에서만 쓴다. */
export const datasetLabel: Record<DatasetKind, string> = {
  "approved-live": "실제 기사",
  "approved-snapshot": "실제 기사 · 저장본",
  "synthetic-preview": "합성 데이터",
};

export const datasetDescription: Record<DatasetKind, string> = {
  "approved-live": "검증 절차를 통과한 기사예요. 사실이나 투자 성과를 보증하지 않아요.",
  "approved-snapshot": "검증 절차를 통과한 기사를 저장한 시점 기준으로 보여줘요.",
  "synthetic-preview": "화면 확인용으로 만든 가상의 기사와 기업이에요.",
};

/** 기사 속 서술 상태(assertion_status)를 쉬운 말로. 모르는 값은 원문을 노출하지 않는다. */
const assertionStatusLabels: Record<string, string> = {
  occurred: "발생",
  announced: "보도 언급",
  planned: "계획",
  forecast: "전망",
};

export function assertionStatusLabel(status: string | null | undefined): string {
  return (status && assertionStatusLabels[status]) || "확인 필요";
}

/** 서버 오류 코드 → 사람말(상황 + 해결책). 원시 코드는 화면에 쓰지 않는다. 모르는 코드는 undefined. */
const errorMessages: Record<string, string> = {
  bff_unreachable: "서버에 연결할 수 없어요. 잠시 후 다시 시도해 주세요.",
  unauthenticated: "로그인이 필요해요. 다시 로그인해 주세요.",
  forbidden: "이 기능을 쓸 수 있는 권한이 없어요.",
  guest_forbidden: "로그인하면 쓸 수 있는 기능이에요.",
  invalid_credentials: "이메일 또는 비밀번호가 올바르지 않아요.",
  login_invalid: "이메일과 비밀번호를 입력해 주세요.",
  signup_invalid: "가입 정보를 확인해 주세요.",
  email_taken: "이미 가입된 이메일이에요. 로그인해 주세요.",
  member_blocked: "이용이 제한된 계정이에요. 운영팀에 문의해 주세요.",
  validation_error: "입력한 값을 확인해 주세요.",
  version_conflict: "다른 곳에서 설정이 바뀌었어요. 최신 설정을 불러왔으니 다시 시도해 주세요.",
  duplicate_watchlist_id: "이미 관심 종목에 있는 기업이에요.",
  unknown_company: "지금 데이터에 없는 기업이에요. 다른 기업을 골라 주세요.",
  already_connected: "이미 가상 계좌가 연결되어 있어요.",
  connection_not_found: "연결된 가상 계좌를 찾지 못했어요. 새로고침해 주세요.",
  mock_portfolio_not_found: "연결할 수 있는 가상 계좌가 아니에요. 목록에서 다시 골라 주세요.",
  portfolio_unavailable: "연결된 가상 계좌 정보를 찾을 수 없어요. 연결을 끊고 다시 연결해 주세요.",
  company_not_found: "기업을 찾을 수 없어요. 지도에서 다시 골라 주세요.",
  event_not_found: "사건을 찾을 수 없어요. 지도에서 다시 골라 주세요.",
  evidence_not_found: "근거를 찾을 수 없어요. 사건을 다시 열어 주세요.",
  edge_not_found: "연결을 찾을 수 없어요. 지도에서 다시 골라 주세요.",
  briefing_not_found: "브리핑을 찾을 수 없어요. 다른 회차를 골라 주세요.",
  chat_session_not_found: "대화가 끝났어요. 새로 질문해 주세요.",
  unknown_context_id: "질문 대상을 찾을 수 없어요. 지도에서 다시 골라 주세요.",
  invalid_range: "조회 범위가 올바르지 않아요. 기간을 다시 골라 주세요.",
  not_found: "요청한 정보를 찾을 수 없어요.",
  internal_error: "일시적인 서버 문제예요. 잠시 후 다시 시도해 주세요.",
  quote_verification_failed: "원문과 인용이 일치하는지 확인하지 못해 답변을 보류했어요.",
  no_evidence_for_context: "수집된 기사에서 근거를 찾지 못해 답변을 보류했어요.",
  no_evidence_in_period: "고른 기간에 발행된 근거가 없어 답변을 보류했어요.",
  prediction_or_advice_not_supported: "주가 예측·매매 판단은 제공하지 않아요. 근거 문장만 확인할 수 있어요.",
  pinned_version_unavailable: "질문할 때 고른 자료를 지금은 쓸 수 없어요. 최신 자료로 바꿔 답하지 않았어요.",
  chat_session_busy: "이전 질문을 아직 처리하고 있어요. 끝난 뒤에 보내 주세요. 쓰던 질문은 그대로 남겨 뒀어요.",
  chat_job_conflict: "같은 질문 번호로 다른 내용이 전송됐어요. 처음 받은 질문은 그대로예요. 고친 질문은 새로 보내 주세요.",
  chat_job_not_found: "질문 기록을 찾을 수 없어요.",
  chat_job_not_retryable: "이 질문은 다시 실행할 수 없어요. 새 질문으로 보내 주세요.",
  chat_job_not_cancellable: "이미 끝난 질문은 취소할 수 없어요.",
  empty_question: "질문을 입력해 주세요.",
  invalid_period: "기간의 시작과 끝을 확인해 주세요.",
};

export function errorReasonMessage(code: string | null | undefined): string | undefined {
  return code ? errorMessages[code] : undefined;
}

/** 서버 입력 검증 오류(details.fields: 항목 → 사람말)를 입력칸별 오류로. 서버가 권위이므로 화면은 그대로 보여준다. */
export function fieldErrorsOf(error: unknown): Record<string, string> {
  if (!(error instanceof ApiError)) return {};
  return (error.details?.fields as Record<string, string> | undefined) ?? {};
}

export type GraphMode = Schemas["GraphMetadata"]["mode"];

export const modeLabel: Record<GraphMode, string> = {
  all: "시장 전체",
  personal: "내 종목",
};

/** 사건 발생 시각을 정밀도에 맞게 보여준다. 모르면 지어내지 않고 '발생 시각 미상'. */
export function formatEventTime(value: string | null | undefined, precision: TimePrecision | null | undefined) {
  if (!value || !precision || precision === "unknown") return "발생 시각 미상";
  const [datePart = value, timePart] = value.split("T");
  const [y, m, d] = datePart.split("-");
  switch (precision) {
    case "year":
      return `${y}년`;
    case "month":
      return `${y}년 ${Number(m)}월`;
    case "day":
      return `${y}-${m}-${d}`;
    case "datetime":
      return timePart ? `${datePart} ${timePart.slice(0, 5)}` : datePart;
  }
}

/** 여러 사건의 발생 시각 범위(예: '2026-09-16 ~ 2026-09-17'). 시각을 아는 사건이 없으면 null(지어내지 않는다). */
export function eventPeriod(events: { eventTime: string | null; timePrecision: TimePrecision | null }[]) {
  const known = events
    .filter((e) => e.eventTime && e.timePrecision && e.timePrecision !== "unknown")
    .sort((a, b) => a.eventTime!.localeCompare(b.eventTime!));
  if (known.length === 0) return null;
  const first = formatEventTime(known[0]!.eventTime, known[0]!.timePrecision);
  const last = formatEventTime(known.at(-1)!.eventTime, known.at(-1)!.timePrecision);
  return first === last ? first : `${first} ~ ${last}`;
}

/** ISO 시각을 'YYYY-MM-DD HH:mm KST' 형태로 보여준다. */
export function formatKst(iso: string | null | undefined) {
  if (!iso) return "시각 미상";
  const date = new Date(iso);
  if (Number.isNaN(date.getTime())) return iso;
  const parts = new Intl.DateTimeFormat("ko-KR", {
    timeZone: "Asia/Seoul",
    year: "numeric",
    month: "2-digit",
    day: "2-digit",
    hour: "2-digit",
    minute: "2-digit",
    hour12: false,
  }).formatToParts(date);
  const get = (type: string) => parts.find((p) => p.type === type)?.value ?? "";
  return `${get("year")}-${get("month")}-${get("day")} ${get("hour")}:${get("minute")} KST`;
}

/** 그래프 빈 상태 사유(metadata.emptyReason)를 안내 문구로 바꾼다. */
export function emptyReasonMessage(reason: string | null | undefined, mode: GraphMode) {
  switch (reason) {
    case "no_personal_stocks":
      return {
        title: "아직 보유·관심 종목이 없어요",
        body: "관심 종목을 고르거나 가상 계좌를 연결하면 내 종목 지도를 보여드려요.",
      };
    case "no_related_issues":
      return {
        title: "이 기업과 연결된 사건이 아직 없어요",
        body: "다른 기업을 고르거나 시장 전체 지도를 살펴보세요.",
      };
    case "no_approved_issues":
      return {
        title: "검증을 통과한 사건이 아직 없어요",
        body: "잠시 후 다시 확인해 주세요.",
      };
    default:
      return {
        title: `${modeLabel[mode]} 지도에 표시할 연결이 없어요`,
        body: "다른 모드를 골라 보세요.",
      };
  }
}
