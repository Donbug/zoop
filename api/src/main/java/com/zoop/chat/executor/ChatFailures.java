package com.zoop.chat.executor;

import com.zoop.chat.dto.ChatFailure;
import java.util.Set;

/**
 * Server-owned {@code ChatFailure}: the member-facing message comes from a template per kind and reason (never from a model),
 * and {@code retry} follows ZOOP-AIG-001 6.3.3: only a transient failure the provider did not process, or answered with a
 * confirmed failure, may be rerun, and only while fewer than three model-calling runs were made. A response of unknown fate
 * ({@code response_unknown}) is never rerun because the provider may already have processed and charged it.
 */
final class ChatFailures {
    static final int MAX_RUNS = 3;
    /** Kinds an engine may report; {@code save_failed} and {@code result_lost} belong to the executor's own recovery. */
    static final Set<String> ENGINE_KINDS = Set.of("transient", "budget_exceeded", "validation_failed", "permission_denied",
            "internal");

    private ChatFailures() {
    }

    static ChatFailure of(String kind, String reason, boolean rerunnable, int runs) {
        boolean rerun = "transient".equals(kind) && rerunnable && !"response_unknown".equals(reason) && runs < MAX_RUNS;
        return new ChatFailure(kind, reason, message(kind, reason, rerun), rerun ? "rerun" : null);
    }

    private static String message(String kind, String reason, boolean rerun) {
        return switch (kind) {
            case "transient" -> switch (reason == null ? "" : reason) {
                case "response_unknown" -> "처리 결과를 확인하지 못했어요. 같은 질문이 두 번 처리되지 않도록 다시 실행하지 않아요. "
                        + "요청 ID로 문의하거나 새 질문으로 보내 주세요.";
                default -> transientCause(reason) + (rerun ? " 같은 질문과 같은 조건으로 다시 처리할 수 있어요."
                        : " 다시 처리할 수 있는 횟수를 넘었어요. 새 질문으로 보내 주세요.");
            };
            case "budget_exceeded" -> "output_limit".equals(reason)
                    ? "답변이 너무 길어 완성하지 못했어요. 질문을 나눠서 보내 주세요."
                    : "질문 범위가 너무 넓어 처리하지 못했어요. 대상이나 기간을 줄여 새 질문으로 보내 주세요.";
            case "validation_failed" -> "답변이 검증을 통과하지 못해 보여드리지 않아요. 질문을 고쳐 새 질문으로 보내 주세요.";
            case "permission_denied" -> "이 질문을 처리할 권한을 확인하지 못했어요. 로그인 상태를 확인해 주세요.";
            case "result_lost" -> "검증한 결과를 보관하지 못해 복구할 수 없어요. 질문을 새 질문으로 다시 보내 주세요.";
            default -> "답변을 만드는 중 예상하지 못한 오류가 났어요. 질문을 새 질문으로 다시 보내 주세요.";
        };
    }

    private static String transientCause(String reason) {
        return switch (reason == null ? "" : reason) {
            case "deadline_guard" -> "처리 시간이 부족해 답변을 끝내지 못했어요.";
            case "tool_timeout" -> "자료 조회가 제한 시간 안에 끝나지 않았어요.";
            default -> "답변 기능이 일시적으로 응답하지 않았어요.";
        };
    }
}
