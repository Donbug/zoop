package com.zoop.chat.executor;

import com.zoop.chat.dto.ChatFrozenContext;
import com.zoop.chat.service.FrozenSelection;
import java.time.Instant;
import java.util.List;

/**
 * One claimed execution of a job: its frozen request and the clarification chain it continues. {@code turns} runs from the
 * root question to this job's own text (ZOOP-AIG-001 6.3.4: a reply is executed as the root question plus the answers in
 * order); a question that answers no clarification has one turn. {@code selection} is the frozen scope (requested ids and
 * the evidence pool) the public {@code context} cannot reproduce on its own.
 */
public record ChatRun(String jobId, String sessionId, String memberId, int attemptNo, String mode, List<Turn> turns,
        ChatFrozenContext context, FrozenSelection selection, String graphVersionId, int clarificationDepth, Instant askedAt, Instant deadline) {

    /**
     * One question of the chain; {@code choiceId} and {@code choiceLabel} are the clarification option it picked, as the
     * answered clarification offered it (both null for free text or the root).
     */
    public record Turn(String jobId, String question, String choiceId, String choiceLabel) { }

    public String question() {
        return turns.getLast().question();
    }
}
