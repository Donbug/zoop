package com.zoop.chat.tool;

import com.zoop.briefing.query.BriefingQueryService;
import com.zoop.chat.service.ChatEvidenceAccess;
import com.zoop.common.exception.CustomException;
import com.zoop.document.evidence.service.EvidenceService.Readability;
import java.time.Instant;
import java.time.LocalDate;
import java.util.ArrayList;
import java.util.HashSet;
import java.util.LinkedHashSet;
import java.util.List;
import java.util.Set;
import java.util.function.Predicate;
import org.springframework.beans.factory.annotation.Autowired;
import org.springframework.dao.DataAccessException;
import org.springframework.stereotype.Component;
import org.springframework.transaction.TransactionException;
import tools.jackson.databind.JsonNode;

/**
 * {@code briefing.read} (Q06): the issues of one published morning or evening briefing round, through the public briefing
 * read ({@code GET /api/v1/briefings}), so the same rights, corrections and suspension apply. The first target names the
 * round ({@link ChatBriefingRound}); any other targets are company ids, and then only the issues involving one of them are
 * kept. Each issue is a {@code briefing_item} labelled with its round, rank, title and selection reason; it passes on the
 * evidence of the issue that is readable now at the run's pinned graph version and asOf, within the limit.
 *
 * <p>A round that is not published (not ready, generating, failed), is suspended, or was published after the run's asOf
 * has no issues to read: an empty result, never a made-up round. A published round that selected no issue is empty too.
 * A read that cannot be made is {@link ChatToolUnavailable}.
 */
@Component
public class BriefingReadTool implements ChatTool {
    /** The public read of one round's response, as {@code GET /api/v1/briefings?date=&edition=} returns it. */
    @FunctionalInterface
    public interface Rounds {
        JsonNode get(LocalDate date, String edition, String requestId);
    }

    private final Rounds rounds;
    private final ChatEvidenceAccess access;

    @Autowired
    public BriefingReadTool(BriefingQueryService briefings, ChatEvidenceAccess access) {
        this(briefings::get, access);
    }

    public BriefingReadTool(Rounds rounds, ChatEvidenceAccess access) {
        this.rounds = rounds;
        this.access = access;
    }

    @Override
    public ChatCapability capability() {
        return ChatCapability.BRIEFING_READ;
    }

    @Override
    public ChatToolOutput read(ChatToolScope scope, ChatToolRequest request) {
        Set<String> companies = new HashSet<>(request.targets().subList(1, request.targets().size()));
        if (companies.stream().anyMatch(ChatBriefingRound::isRef)) {
            throw new IllegalArgumentException("a briefing read names one round");
        }
        return round(scope, request, issue -> companies.isEmpty() || involved(issue).stream().anyMatch(companies::contains));
    }

    private static List<String> involved(JsonNode issue) {
        List<String> involved = new ArrayList<>();
        issue.path("companies").forEach(c -> involved.add(c.path("id").asString()));
        return involved;
    }

    /** The issues {@code kept} takes of the round the first target names, each with its evidence readable now. */
    ChatToolOutput round(ChatToolScope scope, ChatToolRequest request, Predicate<JsonNode> kept) {
        if (scope.graphVersionId() == null) throw new ChatToolUnavailable("the question froze no graph version");
        ChatBriefingRound round = ChatBriefingRound.parse(request.targets().getFirst());
        JsonNode response;
        try {
            response = rounds.get(round.date(), round.edition(), scope.traceId());
        } catch (CustomException | DataAccessException | TransactionException unavailable) {
            throw new ChatToolUnavailable("the briefing round " + round.ref() + " cannot be read", unavailable);
        }
        String status = response.path("status").asString("");
        String publishedAt = response.path("publishedAt").asString(null);
        boolean afterAsOf = scope.asOf() != null && publishedAt != null && Instant.parse(publishedAt).isAfter(scope.asOf());
        if (!"published".equals(status) || publishedAt == null || afterAsOf) {
            return new ChatToolOutput("briefing:none", List.of(), List.of(), false, false);
        }
        String header = response.path("date").asString() + " " + ("morning".equals(response.path("edition").asString())
                ? "출근" : "퇴근") + " 브리핑";

        Set<String> passed = new LinkedHashSet<>();
        Set<String> checked = new HashSet<>();
        boolean truncated = false;
        List<ChatToolItem> items = new ArrayList<>();
        for (JsonNode issue : response.path("items")) {
            if (!kept.test(issue)) continue;
            List<String> evidence = new ArrayList<>();
            for (JsonNode id : issue.path("evidenceIds")) {
                String evidenceId = id.asString();
                // The runner interrupts a read that ran out of time: stop instead of reading on.
                if (Thread.currentThread().isInterrupted()) throw new ChatToolUnavailable("read interrupted");
                if (request.evidenceScope() != null && !request.evidenceScope().contains(evidenceId)) continue;
                if (passed.contains(evidenceId)) {
                    evidence.add(evidenceId);
                } else if (passed.size() >= request.limit()) {
                    if (!checked.contains(evidenceId)) truncated = true;
                } else if (checked.add(evidenceId) && readable(scope, evidenceId)) {
                    passed.add(evidenceId);
                    evidence.add(evidenceId);
                }
            }
            String label = "[" + header + " " + issue.path("rank").asInt() + "위] " + issue.path("title").asString()
                    + " — 선정 이유: " + issue.path("reason").asString();
            items.add(new ChatToolItem(issue.path("eventId").asString(), "briefing_item", label, involved(issue), evidence));
        }
        return new ChatToolOutput(ChatBriefingRound.dataVersion(response.path("date").asString(),
                response.path("edition").asString(), response.path("id").asString()), items, List.copyOf(passed), truncated,
                false);
    }

    private boolean readable(ChatToolScope scope, String evidenceId) {
        Readability readability = access.readability(evidenceId, scope.graphVersionId(), scope.asOf(), scope.traceId());
        if (readability == Readability.UNAVAILABLE) {
            throw new ChatToolUnavailable("evidence " + evidenceId + " could not be checked");
        }
        return readability == Readability.READABLE;
    }
}
