package com.zoop.chat.service;

import java.time.Instant;
import java.util.ArrayList;
import java.util.HashMap;
import java.util.LinkedHashSet;
import java.util.List;
import java.util.Map;
import java.util.Set;

import com.zoop.chat.dto.ChatApplied;
import com.zoop.chat.dto.ChatAppliedItem;
import com.zoop.chat.dto.ChatContextItem;
import com.zoop.chat.dto.ChatConversation;
import com.zoop.chat.dto.ChatCurrentResponse;
import com.zoop.chat.dto.ChatFrozenContext;
import com.zoop.chat.dto.ChatJob;
import com.zoop.chat.dto.ChatResult;
import com.zoop.chat.dto.Citation;
import com.zoop.chat.dto.GraphTarget;
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
 * way: it stays readable while the version it quoted is still in effect now, whatever the stored asOf ({@link ChatZoopDocs}).
 * A citation of any other kind cannot be verified and is withheld.</li>
 * <li>A company or issue in {@code applied} or {@code graphTargets} that is not visible now in the pinned graph at the job's
 * asOf with the current exclusions ({@link ChatTargetAccess}) is left out, whatever the outcome. The evidence check alone
 * would not hide it: an insufficient-evidence result cites nothing, and an excluded issue's evidence can stay readable
 * through another public object that cites it. When visibility cannot be checked, none is shown.</li>
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
    private final ChatTargetAccess targets;

    public ChatResponseGuard(ChatEvidenceAccess access, ChatTargetAccess targets) {
        this.access = access;
        this.targets = targets;
    }

    public ChatJob job(ChatJob job, String requestId) {
        return protect(job, requestId, new HashMap<>(), new HashMap<>());
    }

    public ChatConversation conversation(ChatConversation conversation, String requestId) {
        Map<String, Boolean> checked = new HashMap<>();
        Map<String, Boolean> seen = new HashMap<>();
        List<ChatJob> jobs = new ArrayList<>();
        for (ChatJob job : conversation.jobs()) jobs.add(protect(job, requestId, checked, seen));
        return new ChatConversation(conversation.session(), List.copyOf(jobs));
    }

    public ChatCurrentResponse current(ChatCurrentResponse current, String requestId) {
        return current.conversation() == null ? current
                : new ChatCurrentResponse(conversation(current.conversation(), requestId));
    }

    private ChatJob protect(ChatJob job, String requestId, Map<String, Boolean> checked, Map<String, Boolean> seen) {
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
        ChatResult shownResult = result == null ? null : withVisibleTargets(result, version, asOf, requestId, seen);
        if (shownResult != null && !citesOnlyReadable(shownResult, version, asOf, requestId, checked)) {
            shownResult = withheld(shownResult);
        }
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

    /**
     * The result with only the applied companies and issues, and the map targets, visible now; the same instance when all
     * are.
     */
    private ChatResult withVisibleTargets(ChatResult r, String version, Instant asOf, String requestId,
            Map<String, Boolean> seen) {
        ChatApplied applied = r.applied();
        Set<String> ids = new LinkedHashSet<>();
        if (applied != null) {
            nullSafe(applied.companies()).forEach(i -> ids.add(i.id()));
            nullSafe(applied.issues()).forEach(i -> ids.add(i.id()));
        }
        nullSafe(r.graphTargets()).forEach(g -> ids.add(g.id()));
        String at = "@" + version + "@" + asOf;
        Set<String> unchecked = new LinkedHashSet<>();
        ids.forEach(id -> {
            if (!seen.containsKey(id + at)) unchecked.add(id);
        });
        if (!unchecked.isEmpty()) {
            Set<String> visible = targets.visible(Set.copyOf(unchecked), version, asOf, requestId).orElse(Set.of());
            unchecked.forEach(id -> seen.put(id + at, visible.contains(id)));
        }
        List<GraphTarget> graphTargets = nullSafe(r.graphTargets()).stream()
                .filter(g -> seen.getOrDefault(g.id() + at, false)).toList();
        boolean targetsKept = graphTargets.size() == nullSafe(r.graphTargets()).size();
        ChatApplied shown = applied;
        if (applied != null) {
            List<ChatAppliedItem> companies = visibleOnly(applied.companies(), seen, at);
            List<ChatAppliedItem> issues = visibleOnly(applied.issues(), seen, at);
            if (companies.size() != nullSafe(applied.companies()).size()
                    || issues.size() != nullSafe(applied.issues()).size()) {
                shown = new ChatApplied(companies, issues, applied.period(), applied.graphVersion(), applied.dataAsOf(),
                        applied.questionOverrodeContext());
            }
        }
        if (targetsKept && shown == applied) return r;
        return new ChatResult(r.outcome(), r.messageId(), r.answer(), r.sections(), r.answerBasis(), r.reason(), r.sources(),
                r.citations(), targetsKept ? r.graphTargets() : graphTargets, shown, r.choices(), r.action(),
                r.limitations(), r.metadata());
    }

    private static List<ChatAppliedItem> visibleOnly(List<ChatAppliedItem> items, Map<String, Boolean> seen, String at) {
        return nullSafe(items).stream().filter(i -> seen.getOrDefault(i.id() + at, false)).toList();
    }

    private static ChatResult withheld(ChatResult r) {
        return new ChatResult(r.outcome(), r.messageId(), WITHHELD_ANSWER, List.of(), "none", r.reason(), List.of(),
                List.of(), List.of(), r.applied(), r.choices(), r.action(), r.limitations(), r.metadata());
    }

    private static <T> List<T> nullSafe(List<T> values) {
        return values == null ? List.of() : values;
    }
}
