package com.zoop.chat.dto;

import com.zoop.common.response.Metadata;
import java.util.List;

/**
 * OpenAPI {@code ChatResult}: the verified, stored result of a completed job. A result stored before {@code answerStatus} and
 * {@code notices} existed reads back with no notices and the status its outcome and limitations give.
 */
public record ChatResult(String outcome, String messageId, String answer, List<ChatAnswerSection> sections,
        String answerBasis, String reason, List<String> sources, List<Citation> citations, List<GraphTarget> graphTargets,
        ChatApplied applied, List<ChatChoice> choices, ChatAction action, List<ChatLimitation> limitations,
        Metadata metadata, String answerStatus, List<ChatNotice> notices) {
    public ChatResult {
        notices = notices == null ? List.of() : List.copyOf(notices);
        if (answerStatus == null) answerStatus = !"answered".equals(outcome) ? "guidance"
                : limitations == null || limitations.isEmpty() ? "complete" : "partial";
    }

    /** A result whose status follows from its outcome and limitations, with no notices. */
    public ChatResult(String outcome, String messageId, String answer, List<ChatAnswerSection> sections,
            String answerBasis, String reason, List<String> sources, List<Citation> citations, List<GraphTarget> graphTargets,
            ChatApplied applied, List<ChatChoice> choices, ChatAction action, List<ChatLimitation> limitations,
            Metadata metadata) {
        this(outcome, messageId, answer, sections, answerBasis, reason, sources, citations, graphTargets, applied, choices,
                action, limitations, metadata, null, List.of());
    }
}
