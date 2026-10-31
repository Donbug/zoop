package com.zoop.chat.tool;

import com.zoop.chat.service.ChatEvidenceAccess;
import com.zoop.common.exception.CustomException;
import com.zoop.document.evidence.service.EvidenceService.Readability;
import com.zoop.graph.read.GraphContextLookup;
import com.zoop.graph.read.PublicGraphReader;
import java.util.ArrayList;
import java.util.HashSet;
import java.util.LinkedHashSet;
import java.util.List;
import java.util.Optional;
import java.util.Set;
import org.springframework.dao.DataAccessException;
import org.springframework.transaction.TransactionException;

/**
 * Reads targets of one kind from the run's pinned public graph, through the same path as the public graph API
 * ({@link PublicGraphReader}: pinned version, asOf filter, current exclusions) and never Neo4j or an AI-internal graph. A
 * target that is not visible there is absent from the result. The evidence passed on is what the public evidence read can
 * read now at that version, in target order, deduplicated, kept within the request's evidence scope and capped at the
 * request limit. At most {@value #MAX_ITEMS} items are returned, as many as the answer stage takes for one branch; more
 * marks the result truncated, so the targets left out are never taken for none (a company read as its issues can have
 * many).
 *
 * <p>The data version is the pinned graph version. A run without a frozen graph, an unavailable version or snapshot, a
 * database that cannot be read and an evidence state that could not be checked are {@link ChatToolUnavailable}, never an
 * empty result; any other error stays an adapter fault.
 */
abstract class GraphTargetTool implements ChatTool {
    /** Items one read returns at most (zoop-ai-chat-4 {@code Branch.items}). */
    static final int MAX_ITEMS = 50;

    private final PublicGraphReader reader;
    private final ChatEvidenceAccess access;

    GraphTargetTool(PublicGraphReader reader, ChatEvidenceAccess access) {
        this.reader = reader;
        this.access = access;
    }

    /** The visible target of this tool's kind, or empty. */
    abstract Optional<GraphContextLookup.Target> find(GraphContextLookup lookup, String id);

    /** What one requested id reads, in order: its own target by default; a tool may read several for one id. */
    List<GraphContextLookup.Target> targets(GraphContextLookup lookup, String id) {
        return find(lookup, id).map(List::of).orElse(List.of());
    }

    /** Evidence passed on for a found target ahead of its graph evidence; none by default. */
    List<String> ownEvidence(GraphContextLookup.Target target) {
        return List.of();
    }

    /** Whether a found target is reported even when none of its evidence is passed on. */
    boolean keptWithoutEvidence() {
        return true;
    }

    @Override
    public ChatToolOutput read(ChatToolScope scope, ChatToolRequest request) {
        if (scope.graphVersionId() == null) throw new ChatToolUnavailable("the question froze no graph version");
        GraphContextLookup lookup;
        String version;
        try {
            var pinned = reader.readPinned(scope.graphVersionId(), scope.asOf(), scope.asOf() != null);
            lookup = new GraphContextLookup(pinned.graph());
            version = pinned.selected().version().id();
        } catch (CustomException | DataAccessException | TransactionException unavailable) {
            // The version, its snapshot or the database behind them cannot be read now; any other error is a fault.
            throw new ChatToolUnavailable("graph version " + scope.graphVersionId() + " cannot be read", unavailable);
        }

        Set<String> passed = new LinkedHashSet<>();
        Set<String> checked = new LinkedHashSet<>();
        boolean truncated = false;
        List<ChatToolItem> items = new ArrayList<>();
        Set<String> found = new HashSet<>();
        List<GraphContextLookup.Target> targets = new ArrayList<>();
        for (String id : request.targets()) {
            // Two requested ids may read the same target (an issue and a company it involves): it is reported once.
            targets(lookup, id).stream().filter(t -> found.add(t.id())).forEach(targets::add);
        }
        for (var target : targets) {
            if (items.size() >= MAX_ITEMS) {
                truncated = true;
                break;
            }
            List<String> evidence = new ArrayList<>();
            List<String> candidates = new ArrayList<>(ownEvidence(target));
            candidates.addAll(target.evidenceIds());
            for (String evidenceId : candidates) {
                // The runner interrupts a read that ran out of time: stop instead of reading on.
                if (Thread.currentThread().isInterrupted()) throw new ChatToolUnavailable("read interrupted");
                if (request.evidenceScope() != null && !request.evidenceScope().contains(evidenceId)) continue;
                if (passed.contains(evidenceId)) {
                    evidence.add(evidenceId);
                } else if (passed.size() >= request.limit()) {
                    // Not read: it may or may not be readable, so the result says it was cut, never that there is none.
                    if (!checked.contains(evidenceId)) truncated = true;
                } else if (checked.add(evidenceId) && readable(scope, version, evidenceId)) {
                    passed.add(evidenceId);
                    evidence.add(evidenceId);
                }
            }
            if (evidence.isEmpty() && !keptWithoutEvidence()) continue;
            items.add(new ChatToolItem(target.id(), target.kind(), target.label(), target.companyIds(), evidence));
        }
        return new ChatToolOutput(version, items, List.copyOf(passed), truncated, false);
    }

    private boolean readable(ChatToolScope scope, String version, String evidenceId) {
        Readability readability = access.readability(evidenceId, version, scope.asOf(), scope.traceId());
        if (readability == Readability.UNAVAILABLE) {
            throw new ChatToolUnavailable("evidence " + evidenceId + " could not be checked");
        }
        return readability == Readability.READABLE;
    }
}
