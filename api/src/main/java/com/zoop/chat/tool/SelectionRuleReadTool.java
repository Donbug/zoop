package com.zoop.chat.tool;

import com.zoop.briefing.query.BriefingQueryService;
import com.zoop.chat.service.ChatEvidenceAccess;
import com.zoop.chat.service.ChatPublicationRecords;
import com.zoop.common.exception.CustomException;
import com.zoop.document.evidence.service.EvidenceService.Readability;
import com.zoop.graph.read.GraphContextLookup;
import com.zoop.graph.read.PublicGraphReader;
import java.time.Instant;
import java.time.LocalDate;
import java.util.ArrayList;
import java.util.HashSet;
import java.util.LinkedHashSet;
import java.util.List;
import java.util.Optional;
import java.util.Set;
import org.springframework.beans.factory.annotation.Autowired;
import org.springframework.dao.DataAccessException;
import org.springframework.stereotype.Component;
import org.springframework.transaction.TransactionException;
import tools.jackson.databind.JsonNode;

/**
 * {@code selectionRule.read} (Q08, governance policy 6.3.1: recorded rules and decisions only, user decisions 2026-10-30):
 * why issues the question names are where the member saw them. The first target names a briefing round
 * ({@link ChatBriefingRound}); the others are issue ids. For each issue visible in the run's pinned graph:
 *
 * <ul>
 * <li>its publication record at that version ({@link ChatSelectionRecord.Publication}): the last review decision's kind,
 * time and path (never who decided, never their note) and the publication rules the version was filtered with;</li>
 * <li>when the named round picked it, its briefing selection ({@link ChatSelectionRecord.BriefingSelection}): rank and the
 * recorded selection reason, with the issue's evidence readable now.</li>
 * </ul>
 *
 * <p>An issue that is not visible at the version has no record here: a hidden issue's decisions are not shown. Records are
 * no evidence; each is a {@code selection_record} item whose label the server writes from the record, and the records
 * travel with the result for the verifier's facts. A read that cannot be made is {@link ChatToolUnavailable}.
 */
@Component
public class SelectionRuleReadTool implements ChatTool {
    /** The title of an issue visible at the pinned version and asOf; empty when it is not. */
    @FunctionalInterface
    public interface Issues {
        Optional<String> visibleTitle(String graphVersionId, Instant asOf, String issueId);
    }

    /** The recorded publication of a visible issue at a version ({@link ChatPublicationRecords#publication}). */
    @FunctionalInterface
    public interface Publications {
        Optional<ChatSelectionRecord.Publication> publication(String graphVersionId, String issueId, String issueTitle);
    }

    private final Issues issues;
    private final Publications publications;
    private final BriefingReadTool.Rounds rounds;
    private final ChatEvidenceAccess access;

    @Autowired
    public SelectionRuleReadTool(PublicGraphReader reader, ChatPublicationRecords records, BriefingQueryService briefings,
            ChatEvidenceAccess access) {
        this((version, asOf, issue) -> {
            var pinned = reader.readPinned(version, asOf, asOf != null);
            return new GraphContextLookup(pinned.graph()).find(issue).filter(t -> "issue".equals(t.kind()))
                    .map(GraphContextLookup.Target::label);
        }, records::publication, briefings::get, access);
    }

    public SelectionRuleReadTool(Issues issues, Publications publications, BriefingReadTool.Rounds rounds,
            ChatEvidenceAccess access) {
        this.issues = issues;
        this.publications = publications;
        this.rounds = rounds;
        this.access = access;
    }

    @Override
    public ChatCapability capability() {
        return ChatCapability.SELECTION_RULE_READ;
    }

    @Override
    public ChatToolOutput read(ChatToolScope scope, ChatToolRequest request) {
        if (scope.graphVersionId() == null) throw new ChatToolUnavailable("the question froze no graph version");
        ChatBriefingRound round = ChatBriefingRound.parse(request.targets().getFirst());
        List<String> asked = request.targets().subList(1, request.targets().size());
        if (asked.isEmpty() || asked.stream().anyMatch(ChatBriefingRound::isRef)) {
            throw new IllegalArgumentException("a selection read names one round, then issues");
        }
        List<ChatSelectionRecord> records = new ArrayList<>();
        List<ChatToolItem> items = new ArrayList<>();
        Set<String> passed = new LinkedHashSet<>();
        Set<String> checked = new HashSet<>();
        boolean truncated = false;
        try {
            JsonNode response = null;
            for (String issueId : asked) {
                Optional<String> title = issues.visibleTitle(scope.graphVersionId(), scope.asOf(), issueId);
                if (title.isEmpty()) continue;
                var publication = publications.publication(scope.graphVersionId(), issueId, title.get())
                        .orElseThrow(() -> new ChatToolUnavailable("graph version " + scope.graphVersionId() + " is gone"));
                records.add(publication);
                items.add(new ChatToolItem("sel-map:" + issueId, "selection_record", label(publication), List.of(),
                        List.of()));

                if (response == null) response = rounds.get(round.date(), round.edition(), scope.traceId());
                var picked = picked(response, scope, issueId);
                if (picked == null) continue;
                List<String> evidence = new ArrayList<>();
                for (JsonNode id : picked.path("evidenceIds")) {
                    String evidenceId = id.asString();
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
                var selection = new ChatSelectionRecord.BriefingSelection(issueId, title.get(),
                        response.path("id").asString(), LocalDate.parse(response.path("date").asString()),
                        response.path("edition").asString(), picked.path("rank").asInt(),
                        picked.path("reason").asString());
                records.add(selection);
                items.add(new ChatToolItem("sel-briefing:" + selection.roundId() + ":" + issueId, "selection_record",
                        label(selection), List.of(), evidence));
            }
        } catch (CustomException | DataAccessException | TransactionException unavailable) {
            throw new ChatToolUnavailable("the selection records cannot be read", unavailable);
        }
        return new ChatToolOutput(scope.graphVersionId(), items, List.copyOf(passed), truncated, false, List.of(),
                List.of(), records);
    }

    /** The issue as the published round picked it, or null: a round that is not published, or came after the cutoff. */
    private static JsonNode picked(JsonNode response, ChatToolScope scope, String issueId) {
        String publishedAt = response.path("publishedAt").asString(null);
        if (!"published".equals(response.path("status").asString("")) || publishedAt == null
                || scope.asOf() != null && Instant.parse(publishedAt).isAfter(scope.asOf())) return null;
        for (JsonNode item : response.path("items")) {
            if (issueId.equals(item.path("eventId").asString())) return item;
        }
        return null;
    }

    /** The item label of a publication record: what the model reads of it. */
    public static String label(ChatSelectionRecord.Publication p) {
        String decision = switch (p.decisionPath()) {
            case "admin_review" -> "관리자 검수에서 " + ("allow".equals(p.decision()) ? "공개 승인" : "공개 거절") + "("
                    + p.decidedAt() + ")";
            case "snapshot_migration" -> "이전 공개본에서 이어진 " + ("allow".equals(p.decision()) ? "공개 승인" : "공개 거절")
                    + "(" + p.decidedAt() + ")";
            default -> "관리자 검수 결정 기록 없음";
        };
        String rules = p.rules().isEmpty() ? "적용된 공개 규칙 없음"
                : "적용된 공개 규칙: " + String.join(", ", p.rules().stream().map(ChatSelectionRecord.Rule::title).toList());
        return "[지도 " + p.graphVersionId() + " 공개 기록] " + p.issueTitle() + " — " + decision + "; " + rules;
    }

    /** The item label of a briefing selection record. */
    public static String label(ChatSelectionRecord.BriefingSelection s) {
        return "[" + s.date() + " " + ("morning".equals(s.edition()) ? "출근" : "퇴근") + " 브리핑 " + s.rank() + "위 선정 기록] "
                + s.issueTitle() + " — 선정 이유: " + s.reason();
    }

    private boolean readable(ChatToolScope scope, String evidenceId) {
        Readability readability = access.readability(evidenceId, scope.graphVersionId(), scope.asOf(), scope.traceId());
        if (readability == Readability.UNAVAILABLE) {
            throw new ChatToolUnavailable("evidence " + evidenceId + " could not be checked");
        }
        return readability == Readability.READABLE;
    }
}
