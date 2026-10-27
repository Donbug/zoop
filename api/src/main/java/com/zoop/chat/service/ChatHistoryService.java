package com.zoop.chat.service;

import java.util.List;
import java.util.function.Supplier;

import com.zoop.auth.service.CsrfKeyRing;
import com.zoop.auth.service.MemberSessionService.MemberPrincipal;
import com.zoop.chat.dto.ChatConversationList;
import com.zoop.chat.dto.ChatConversationSummary;
import com.zoop.chat.dto.ChatJobRequest;
import com.zoop.chat.repository.ChatRepository;
import com.zoop.chat.repository.ChatSessionRow;
import com.zoop.chat.repository.ChatSessionSummaryRow;
import com.zoop.common.exception.CustomException;
import com.zoop.common.exception.ErrorCode;
import org.springframework.beans.factory.annotation.Value;
import org.springframework.dao.DataAccessException;
import org.springframework.stereotype.Service;
import org.springframework.transaction.annotation.Transactional;
import tools.jackson.databind.ObjectMapper;

/**
 * The member's conversation history (D-AI-02, FS050/FS051; the list and deletion FS050 moved to P2): the list of their
 * conversations and the deletion of one.
 *
 * <ul>
 * <li>The list holds conversations with at least one question, latest question first, each titled by its first question.
 * A conversation opened with "새 대화" and never asked in is not listed. Reading the list never starts an execution.</li>
 * <li>Deletion removes the conversation, its jobs and their tool calls at once, with no deleted marker and no retention
 * period, as a withdrawal removes them (privacy policy 2026-10-13.1: no long-term backup). The model execution ledger keeps
 * its rows without the job they belonged to. A conversation with a queued or running question cannot be deleted
 * ({@code JOB_IN_PROGRESS}); the member cancels it first, so no executor writes into a deleted conversation.</li>
 * <li>The approved privacy policy and terms (2026-10-13.1) say a single chat cannot be deleted. Deletion therefore stays off
 * ({@code zoop.chat.delete-enabled=false}: {@code RESOURCE_NOT_FOUND}) until their revision is approved and in force.</li>
 * </ul>
 */
@Service
public class ChatHistoryService {
    static final int DEFAULT_LIMIT = 20;
    static final int MAX_LIMIT = 50;
    /** The longest title the list shows; the full question is in the conversation itself. */
    static final int MAX_TITLE = 100;

    private final ChatRepository repository;
    private final ObjectMapper mapper;
    private final CsrfKeyRing keys;
    private final boolean deleteEnabled;

    public ChatHistoryService(ChatRepository repository, ObjectMapper mapper, CsrfKeyRing keys,
            @Value("${zoop.chat.delete-enabled:false}") boolean deleteEnabled) {
        this.repository = repository;
        this.mapper = mapper;
        this.keys = keys;
        this.deleteEnabled = deleteEnabled;
    }

    @Transactional(readOnly = true)
    public ChatConversationList list(MemberPrincipal member, String cursor, Integer requestedLimit) {
        if (requestedLimit != null && (requestedLimit < 1 || requestedLimit > MAX_LIMIT)) {
            throw new CustomException(ErrorCode.INVALID_REQUEST);
        }
        int limit = requestedLimit == null ? DEFAULT_LIMIT : requestedLimit;
        var after = ChatSessionCursor.decode(mapper, keys, cursor, member.memberId(), limit);
        List<ChatSessionSummaryRow> rows = data(() -> repository.sessions(member.memberId(),
                after == null ? null : after.at(), after == null ? null : after.id(), limit + 1));
        List<ChatSessionSummaryRow> page = rows.subList(0, Math.min(limit, rows.size()));
        String next = null;
        if (rows.size() > limit) {
            var last = page.getLast();
            next = ChatSessionCursor.encode(mapper, keys, member.memberId(), limit, last.updatedAt(), last.id());
        }
        return new ChatConversationList(page.stream().map(ChatHistoryService::summary).toList(), next, deleteEnabled);
    }

    @Transactional
    public void delete(MemberPrincipal member, String sessionId) {
        if (!deleteEnabled) throw new CustomException(ErrorCode.RESOURCE_NOT_FOUND);
        ChatJobRequest.id(sessionId);
        data(() -> {
            // The conversation lock orders this after any submission or retry in flight and keeps new ones out until it ends.
            ChatSessionRow session = repository.lockSession(sessionId)
                    .orElseThrow(() -> new CustomException(ErrorCode.RESOURCE_NOT_FOUND));
            if (!session.memberId().equals(member.memberId())) throw new CustomException(ErrorCode.ACCESS_DENIED);
            if (repository.activeJob(sessionId).isPresent()) throw new CustomException(ErrorCode.JOB_IN_PROGRESS);
            return repository.deleteSession(sessionId);
        });
    }

    private static ChatConversationSummary summary(ChatSessionSummaryRow row) {
        String question = row.firstQuestion().strip();
        String title = question.codePointCount(0, question.length()) <= MAX_TITLE ? question
                : question.substring(0, question.offsetByCodePoints(0, MAX_TITLE - 1)) + "…";
        return new ChatConversationSummary(row.id(), title, row.createdAt(), row.updatedAt(), row.jobs());
    }

    private static <T> T data(Supplier<T> work) {
        try {
            return work.get();
        } catch (DataAccessException unavailable) {
            throw new CustomException(ErrorCode.SOURCE_UNAVAILABLE, unavailable);
        }
    }
}
