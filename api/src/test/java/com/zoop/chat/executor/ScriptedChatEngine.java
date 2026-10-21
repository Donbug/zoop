package com.zoop.chat.executor;

import java.time.Instant;
import java.util.ArrayList;
import java.util.List;
import java.util.function.BiFunction;

import com.zoop.chat.dto.ChatAnswerSection;
import com.zoop.chat.dto.ChatApplied;
import com.zoop.chat.dto.ChatChoice;
import com.zoop.chat.dto.ChatResult;
import com.zoop.common.response.Metadata;

/**
 * Test-only deterministic {@link ChatEngine}: no model, no data. Each test scripts what the run does through the control and
 * what it returns. It is never registered in the application.
 */
final class ScriptedChatEngine implements ChatEngine {
    static final Instant AS_OF = Instant.parse("2026-10-21T00:00:00Z");
    static final String GENERAL_NOTICE = "일반 개념 설명입니다. 최신 기업·시장 사실은 별도 조회가 필요합니다.";

    final List<ChatRun> runs = new ArrayList<>();
    private volatile BiFunction<ChatRun, ChatRunControl, ChatEngineOutcome> script;

    ScriptedChatEngine(BiFunction<ChatRun, ChatRunControl, ChatEngineOutcome> script) {
        this.script = script;
    }

    void script(BiFunction<ChatRun, ChatRunControl, ChatEngineOutcome> next) {
        this.script = next;
    }

    @Override
    public ChatEngineOutcome answer(ChatRun run, ChatRunControl control) {
        runs.add(run);
        return script.apply(run, control);
    }

    /** The Q02 path of the plan's first PR: one general-knowledge section, no sources or citations. */
    static ChatEngineOutcome.Completed generalAnswer(String text) {
        String section = GENERAL_NOTICE + " " + text;
        return new ChatEngineOutcome.Completed(result("answered", section,
                List.of(new ChatAnswerSection("general_knowledge", section, List.of())), "general_knowledge", List.of(),
                null), null);
    }

    static ChatEngineOutcome.Completed clarification(String reason, String... choiceIds) {
        List<ChatChoice> choices = new ArrayList<>();
        for (String id : choiceIds) choices.add(new ChatChoice(id, id, "company"));
        return new ChatEngineOutcome.Completed(result("clarification", "", List.of(), "none", choices, reason), null);
    }

    static ChatEngineOutcome.Completed guidance(String reason) {
        return new ChatEngineOutcome.Completed(result("guidance", "", List.of(), "none", List.of(), reason), null);
    }

    private static ChatResult result(String outcome, String answer, List<ChatAnswerSection> sections, String basis,
            List<ChatChoice> choices, String reason) {
        return new ChatResult(outcome, "engine-message", answer, sections, basis, reason, List.of(), List.of(), List.of(),
                new ChatApplied(List.of(), List.of(), null, null, AS_OF, false), choices, null, List.of(),
                new Metadata("zoop", AS_OF, null, "chat-run", false, List.of()));
    }
}
