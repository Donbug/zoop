package com.zoop.chat.executor;

import com.zoop.chat.dto.ChatAppliedItem;
import com.zoop.chat.dto.ChatFrozenContext;
import com.zoop.chat.dto.ChatPeriod;
import com.zoop.chat.service.FrozenSelection;
import java.time.Instant;
import java.util.List;

/**
 * One claimed execution of a job: its frozen request and the clarification chain it continues. {@code turns} runs from the
 * root question to this job's own text (ZOOP-AIG-001 6.3.4: a reply is executed as the root question plus the answers in
 * order); a question that answers no clarification has one turn. {@code selection} is the frozen scope (requested ids and
 * the evidence pool) the public {@code context} cannot reproduce on its own. {@code prior} is what the conversation's last
 * answers verified, a candidate only and never model input.
 */
public record ChatRun(String jobId, String sessionId, String memberId, int attemptNo, String mode, List<Turn> turns,
        ChatFrozenContext context, FrozenSelection selection, String graphVersionId, int clarificationDepth, Instant askedAt, Instant deadline,
        Prior prior) {

    /**
     * One question of the chain; {@code choiceId} and {@code choiceLabel} are the clarification option it picked, as the
     * answered clarification offered it (both null for free text or the root).
     */
    public record Turn(String jobId, String question, String choiceId, String choiceLabel) { }

    /**
     * The targets and the period the last two answers of the conversation applied (MCP actions contract 2). Each comes from
     * the newest of them that has any. Ids only stand as candidates for a question that names nothing; a run sees the ones
     * still visible in its own pinned graph.
     */
    public record Prior(List<ChatAppliedItem> companies, List<ChatAppliedItem> issues, ChatPeriod period) {
        public static final Prior NONE = new Prior(List.of(), List.of(), null);

        public Prior {
            companies = List.copyOf(companies);
            issues = List.copyOf(issues);
        }
    }

    public ChatRun(String jobId, String sessionId, String memberId, int attemptNo, String mode, List<Turn> turns,
            ChatFrozenContext context, FrozenSelection selection, String graphVersionId, int clarificationDepth, Instant askedAt,
            Instant deadline) {
        this(jobId, sessionId, memberId, attemptNo, mode, turns, context, selection, graphVersionId, clarificationDepth, askedAt,
                deadline, Prior.NONE);
    }

    public ChatRun withPrior(Prior replaced) {
        return new ChatRun(jobId, sessionId, memberId, attemptNo, mode, turns, context, selection, graphVersionId,
                clarificationDepth, askedAt, deadline, replaced);
    }

    public String question() {
        return turns.getLast().question();
    }

    /** The period a comparison falls back on when its words write none: the selected one, else the previous answers'. */
    public ChatPeriod period() {
        return context.period() != null ? context.period() : prior.period();
    }
}
