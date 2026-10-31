package com.zoop.chat.executor;

import java.util.ArrayList;
import java.util.List;
import java.util.Set;

import com.zoop.chat.dto.ChatAppliedItem;
import com.zoop.chat.dto.ChatPeriod;
import com.zoop.chat.repository.ChatJobRow;
import tools.jackson.databind.JsonNode;
import tools.jackson.databind.ObjectMapper;

/**
 * What a conversation's last answers carry over to its next question: only what the server stored as {@code applied}, never
 * an answer's text. A question is judged from its own words first; these are candidates when it names nothing.
 */
final class ChatPriorTurns {
    /** The turns a new question may carry from (MCP actions contract 2). */
    static final int TURNS = 2;
    /** A period the member asked for; {@code evidence} only describes what the cited articles happened to span. */
    private static final Set<String> ASKED = Set.of("question", "context");

    private ChatPriorTurns() {
    }

    /** {@code answers} newest first. */
    static ChatRun.Prior of(List<ChatJobRow> answers, ObjectMapper mapper) {
        List<ChatAppliedItem> companies = List.of();
        List<ChatAppliedItem> issues = List.of();
        ChatPeriod period = null;
        for (ChatJobRow answer : answers) {
            JsonNode applied = mapper.readTree(answer.result()).path("applied");
            if (companies.isEmpty() && issues.isEmpty()) {
                companies = items(applied.path("companies"));
                issues = items(applied.path("issues"));
            }
            JsonNode asked = applied.path("period");
            if (period == null && ASKED.contains(asked.path("basis").asString(""))) {
                period = new ChatPeriod(asked.path("start").asString(), asked.path("end").asString());
            }
        }
        return new ChatRun.Prior(companies, issues, period);
    }

    private static List<ChatAppliedItem> items(JsonNode items) {
        List<ChatAppliedItem> read = new ArrayList<>();
        items.forEach(item -> read.add(new ChatAppliedItem(item.path("id").asString(), item.path("label").asString())));
        return read;
    }
}
