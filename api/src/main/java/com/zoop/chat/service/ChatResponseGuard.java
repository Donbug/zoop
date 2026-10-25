package com.zoop.chat.service;

import java.time.Instant;
import java.util.ArrayList;
import java.util.HashMap;
import java.util.LinkedHashSet;
import java.util.List;
import java.util.Map;
import java.util.Set;

import com.zoop.chat.dto.ChatContextItem;
import com.zoop.chat.dto.ChatConversation;
import com.zoop.chat.dto.ChatCurrentResponse;
import com.zoop.chat.dto.ChatFrozenContext;
import com.zoop.chat.dto.ChatJob;
import com.zoop.chat.dto.ChatResult;
import com.zoop.chat.dto.Citation;
import org.springframework.stereotype.Component;

/**
 * Re-checks evidence access every time a stored job is returned (OpenAPI {@code aiJobs}; design summary section 9): job
 * reads, conversation reads, the latest-conversation restore, an idempotent resend, cancel and retry all pass here. What is
 * stored never changes; only the response hides what is not readable now.
 *
 * <ul>
 * <li>A selected evidence item that is no longer readable keeps its id and kind but not its title.</li>
 * <li>A result citing any evidence that is not readable now (withdrawn, private, rights changed, excluded from the pinned
 * graph, or not verifiable) returns no answer text, sections, sources, citations or graph targets; {@code answer} carries
 * a fixed notice and {@code answerBasis} is {@code none}. An approved ZOOP document ({@code zoop_doc}) is checked the same
 * way: it stays readable while the version it quoted is still in effect ({@link ChatZoopDocs}). A citation of any other
 * kind cannot be verified and is withheld.</li>
 * </ul>
 *
 * <p>It runs outside the chat transaction because the evidence read has its own.
 */
@Component
public class ChatResponseGuard {
    public static final String WITHHELD_ANSWER = "이 답변이 인용한 자료를 지금은 보여드릴 수 없어요. 자료가 비공개로 바뀌었거나 "
            + "접근 권한을 확인하지 못했어요. 필요하면 새 질문으로 다시 물어봐 주세요.";
    public static final String WITHHELD_EVIDENCE_LABEL = "표시할 수 없는 근거";
    private static final Set<String> CHECKABLE = Set.of("article", "company_profile", "zoop_doc");

    private final ChatEvidenceAccess access;

    public ChatResponseGuard(ChatEvidenceAccess access) {
        this.access = access;
    }

    public ChatJob job(ChatJob job, String requestId) {
        return protect(job, requestId, new HashMap<>());
    }

    public ChatConversation conversation(ChatConversation conversation, String requestId) {
        Map<String, Boolean> checked = new HashMap<>();
        List<ChatJob> jobs = new ArrayList<>();
        for (ChatJob job : conversation.jobs()) jobs.add(protect(job, requestId, checked));
        return new ChatConversation(conversation.session(), List.copyOf(jobs));
    }

    public ChatCurrentResponse current(ChatCurrentResponse current, String requestId) {
        return current.conversation() == null ? current
                : new ChatCurrentResponse(conversation(current.conversation(), requestId));
    }

    private ChatJob protect(ChatJob job, String requestId, Map<String, Boolean> checked) {
        ChatFrozenContext context = job.context();
        String version = context == null ? null : context.graphVersion();
        var asOf = context == null ? null : context.asOf();
        ChatFrozenContext shownContext = context;
        if (context != null && context.items().stream().anyMatch(i -> "evidence".equals(i.kind()))) {
            List<ChatContextItem> items = context.items().stream()
                    .map(i -> !"evidence".equals(i.kind()) || readable(i.id(), version, asOf, requestId, checked) ? i
                            : new ChatContextItem(i.id(), i.kind(), WITHHELD_EVIDENCE_LABEL))
                    .toList();
            if (!items.equals(context.items())) {
                shownContext = new ChatFrozenContext(items, context.evidenceCount(), context.period(), context.asOf(),
                        context.graphVersion());
            }
        }
        ChatResult result = job.result();
        ChatResult shownResult = result == null || citesOnlyReadable(result, version, asOf, requestId, checked) ? result
                : withheld(result);
        if (shownContext == context && shownResult == result) return job;
        return new ChatJob(job.id(), job.sessionId(), job.seq(), job.question(), job.status(), job.phase(), job.outcome(),
                job.askedAt(), shownContext, job.resolves(), job.failure(), shownResult, job.runs(), job.createdAt(),
                job.updatedAt(), job.finishedAt());
    }

    private boolean citesOnlyReadable(ChatResult result, String version, Instant asOf, String requestId,
            Map<String, Boolean> checked) {
        Set<String> articles = new LinkedHashSet<>();
        Set<String> documents = new LinkedHashSet<>();
        for (Citation citation : nullSafe(result.citations())) {
            // A catalog profile or ZOOP document quote is checked like an article: readable while its source still holds it.
            boolean checkable = CHECKABLE.contains(citation.sourceKind());
            (checkable ? articles : documents).add(citation.evidenceId());
        }
        if (!documents.isEmpty()) return false;
        Set<String> cited = new LinkedHashSet<>(articles);
        nullSafe(result.sections()).forEach(s -> cited.addAll(nullSafe(s.evidenceIds())));
        for (String id : cited) {
            if (!readable(id, version, asOf, requestId, checked)) return false;
        }
        return true;
    }

    private boolean readable(String id, String version, Instant asOf, String requestId,
            Map<String, Boolean> checked) {
        return checked.computeIfAbsent(id + "@" + version + "@" + asOf,
                key -> access.readable(id, version, asOf, requestId));
    }

    private static ChatResult withheld(ChatResult r) {
        return new ChatResult(r.outcome(), r.messageId(), WITHHELD_ANSWER, List.of(), "none", r.reason(), List.of(),
                List.of(), List.of(), r.applied(), r.choices(), r.action(), r.limitations(), r.metadata());
    }

    private static <T> List<T> nullSafe(List<T> values) {
        return values == null ? List.of() : values;
    }
}
