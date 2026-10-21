package com.zoop.chat.dto;

import com.zoop.common.response.Metadata;
import java.util.List;

/** OpenAPI {@code ChatResult}: the verified, stored result of a completed job. */
public record ChatResult(String outcome, String messageId, String answer, List<ChatAnswerSection> sections,
        String answerBasis, String reason, List<String> sources, List<Citation> citations, List<GraphTarget> graphTargets,
        ChatApplied applied, List<ChatChoice> choices, ChatAction action, List<ChatLimitation> limitations,
        Metadata metadata) {
}
