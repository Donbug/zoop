package com.zoop.chat.tool;

import java.time.Clock;
import java.time.Instant;
import java.util.ArrayList;
import java.util.LinkedHashSet;
import java.util.List;
import java.util.Optional;
import java.util.Set;

import com.zoop.chat.service.ChatEvidenceAccess;
import com.zoop.common.exception.CustomException;
import com.zoop.document.evidence.service.EvidenceService.Readability;
import com.zoop.graph.read.GraphChanges;
import com.zoop.graph.read.PublicGraphReader;
import com.zoop.graph.version.GraphVersionRepository;
import org.springframework.dao.DataAccessException;
import org.springframework.stereotype.Component;
import org.springframework.transaction.TransactionException;

/**
 * {@code graph.version.diff} (Q05 period comparison, decision of 2026-10-27): what changed between the run's pinned public
 * graph and an earlier public one, both read through {@link PublicGraphReader} (each with the current public exclusions), so
 * the answer matches what the map showed then and shows now.
 *
 * <ul>
 * <li>The earlier graph is the one public at {@link ChatToolRequest#since()} (the period the question wrote), or without one,
 * the version public just before the pinned one became public. There being no earlier public graph is reported as a cut
 * read ({@code truncated}), never as "nothing changed"; the same version on both sides is a read that found no change.</li>
 * <li>Targets narrow the changes to those companies and issues and the relations of those companies;
 * {@link ChatCapability#WHOLE_GRAPH} keeps every change. At most {@link #MAX_CHANGES} changes are reported, additions
 * first; more is {@code truncated}.</li>
 * <li>Each change is an item of its kind ({@code company}, {@code issue}, {@code edge}) whose label starts with
 * {@code [새로 생김]} or {@code [사라짐]}. Only additions carry evidence: what the pinned graph shows for them, readable now,
 * within the evidence scope and the request limit. A removal has none to show.</li>
 * <li>The data version names both versions ({@code <earlier>..<pinned>}). A version, snapshot or database that cannot be
 * read is {@link ChatToolUnavailable}.</li>
 * </ul>
 */
@Component
public class GraphVersionDiffTool implements ChatTool {
    static final int MAX_CHANGES = 40;

    private final PublicGraphReader reader;
    private final GraphVersionRepository versions;
    private final ChatEvidenceAccess access;
    private final Clock clock;

    public GraphVersionDiffTool(PublicGraphReader reader, GraphVersionRepository versions, ChatEvidenceAccess access,
            Clock clock) {
        this.reader = reader;
        this.versions = versions;
        this.access = access;
        this.clock = clock;
    }

    @Override
    public ChatCapability capability() {
        return ChatCapability.GRAPH_VERSION_DIFF;
    }

    @Override
    public ChatToolOutput read(ChatToolScope scope, ChatToolRequest request) {
        if (scope.graphVersionId() == null) throw new ChatToolUnavailable("the question froze no graph version");
        String version;
        String earlier;
        List<GraphChanges.Change> changes;
        try {
            var pinned = reader.read(null, scope.graphVersionId(), scope.asOf());
            version = pinned.selected().version().id();
            Instant at = scope.asOf() != null ? scope.asOf() : clock.instant();
            Optional<String> baseline = request.since() != null ? versions.activeVersionIdAt(request.since())
                    : versions.previousVersionId(version, at);
            if (baseline.isEmpty()) return new ChatToolOutput(version, List.of(), List.of(), true, false);
            earlier = baseline.get();
            if (earlier.equals(version)) {
                return new ChatToolOutput(earlier + ".." + version, List.of(), List.of(), false, false);
            }
            changes = GraphChanges.between(reader.read(null, earlier, null).graph(), pinned.graph());
        } catch (CustomException | DataAccessException | TransactionException unavailable) {
            throw new ChatToolUnavailable("graph versions around " + scope.graphVersionId() + " cannot be read", unavailable);
        }

        boolean whole = request.targets().equals(List.of(ChatCapability.WHOLE_GRAPH));
        Set<String> targets = Set.copyOf(request.targets());
        List<GraphChanges.Change> kept = changes.stream().filter(c -> whole || targets.contains(c.id())
                || c.companyIds().stream().anyMatch(targets::contains)).toList();
        boolean truncated = kept.size() > MAX_CHANGES;
        if (truncated) kept = kept.subList(0, MAX_CHANGES);

        Set<String> passed = new LinkedHashSet<>();
        List<ChatToolItem> items = new ArrayList<>();
        for (var change : kept) {
            List<String> evidence = new ArrayList<>();
            for (String id : change.evidenceIds()) {
                if (Thread.currentThread().isInterrupted()) throw new ChatToolUnavailable("read interrupted");
                if (request.evidenceScope() != null && !request.evidenceScope().contains(id)) continue;
                if (passed.contains(id)) {
                    evidence.add(id);
                } else if (passed.size() >= request.limit()) {
                    truncated = true;
                } else if (readable(scope, version, id)) {
                    passed.add(id);
                    evidence.add(id);
                }
            }
            String mark = "added".equals(change.change()) ? "[새로 생김] " : "[사라짐] ";
            items.add(new ChatToolItem(change.id(), change.kind(), mark + change.label(), change.companyIds(), evidence));
        }
        return new ChatToolOutput(earlier + ".." + version, items, List.copyOf(passed), truncated, false);
    }

    private boolean readable(ChatToolScope scope, String version, String evidenceId) {
        Readability readability = access.readability(evidenceId, version, scope.asOf(), scope.traceId());
        if (readability == Readability.UNAVAILABLE) {
            throw new ChatToolUnavailable("evidence " + evidenceId + " could not be checked");
        }
        return readability == Readability.READABLE;
    }
}
