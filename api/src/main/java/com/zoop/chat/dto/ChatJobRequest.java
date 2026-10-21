package com.zoop.chat.dto;

import com.zoop.common.exception.CustomException;
import com.zoop.common.exception.ErrorCode;
import com.zoop.common.json.StrictJson;
import java.time.DateTimeException;
import java.time.LocalDate;
import java.time.OffsetDateTime;
import java.util.LinkedHashSet;
import java.util.List;
import java.util.Set;
import java.util.regex.Pattern;
import tools.jackson.databind.JsonNode;

/**
 * OpenAPI {@code ChatJobRequest}: a new question, or the answer to a clarification ({@code resolves}). Read strictly: an
 * unknown key, a wrong type, a duplicate id or a value out of range is {@code INVALID_REQUEST}, never coerced.
 * {@code context} is null when it was not sent.
 */
public record ChatJobRequest(String jobId, String question, ChatContextRequest context, ChatClarificationReply resolves) {
    public static final Pattern ID = Pattern.compile("[A-Za-z0-9_-]{8,64}");
    public static final int MAX_QUESTION = 4000;
    private static final int MAX_IDS = 20;
    private static final Pattern DAY = Pattern.compile("\\d{4}-\\d{2}-\\d{2}");

    public static ChatJobRequest parse(JsonNode body) {
        try {
            var root = StrictJson.Obj.of(body).keys(Set.of("jobId", "question"), Set.of("context", "resolves"));
            String jobId = id(root.string("jobId"));
            String question = root.string("question");
            int length = question.codePointCount(0, question.length());
            if (length < 1 || length > MAX_QUESTION || question.isBlank()) throw invalid();
            if (root.has("context") && root.has("resolves")) throw invalid();
            ChatContextRequest context = root.has("context") ? context(root.object("context")) : null;
            ChatClarificationReply resolves = root.has("resolves") ? resolves(root.object("resolves")) : null;
            return new ChatJobRequest(jobId, question, context, resolves);
        } catch (StrictJson.Malformed malformed) {
            throw invalid();
        }
    }

    public static String id(String value) {
        if (value == null || !ID.matcher(value).matches()) throw invalid();
        return value;
    }

    private static ChatContextRequest context(StrictJson.Obj context) {
        context.keys(Set.of(), Set.of("contextIds", "evidenceIds", "period", "asOf", "graphVersion"));
        List<String> contextIds = context.has("contextIds") ? ids(context.strings("contextIds")) : List.of();
        List<String> evidenceIds = context.has("evidenceIds") ? ids(context.strings("evidenceIds")) : List.of();
        ChatPeriod period = context.has("period") && !context.isNull("period") ? period(context.object("period")) : null;
        String asOf = context.has("asOf") ? context.stringOrNull("asOf") : null;
        String graphVersion = context.has("graphVersion") ? context.stringOrNull("graphVersion") : null;
        if (graphVersion != null && graphVersion.isBlank()) throw invalid();
        try {
            return new ChatContextRequest(contextIds, evidenceIds, period,
                    asOf == null ? null : OffsetDateTime.parse(asOf).toInstant(), graphVersion);
        } catch (DateTimeException offsetMissingOrMalformed) {
            throw invalid();
        }
    }

    private static List<String> ids(List<String> values) {
        if (values.size() > MAX_IDS || new LinkedHashSet<>(values).size() != values.size()) throw invalid();
        for (String value : values) {
            if (value.isBlank()) throw invalid();
        }
        return List.copyOf(values);
    }

    private static ChatPeriod period(StrictJson.Obj period) {
        period.exactly(Set.of("start", "end"));
        String start = period.string("start");
        String end = period.string("end");
        if (!DAY.matcher(start).matches() || !DAY.matcher(end).matches()) throw invalid();
        try {
            if (LocalDate.parse(start).isAfter(LocalDate.parse(end))) throw invalid();
        } catch (DateTimeException notADay) {
            throw invalid();
        }
        return new ChatPeriod(start, end);
    }

    private static ChatClarificationReply resolves(StrictJson.Obj resolves) {
        resolves.exactly(Set.of("jobId", "choiceId"));
        String jobId = id(resolves.string("jobId"));
        String choiceId = resolves.stringOrNull("choiceId");
        if (choiceId != null && (choiceId.isEmpty() || choiceId.codePointCount(0, choiceId.length()) > 128)) throw invalid();
        return new ChatClarificationReply(jobId, choiceId);
    }

    private static CustomException invalid() {
        return new CustomException(ErrorCode.INVALID_REQUEST);
    }
}
