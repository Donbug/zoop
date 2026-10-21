package com.zoop.chat.service;

import com.zoop.chat.dto.ChatContextItem;
import com.zoop.chat.dto.ChatContextRequest;
import com.zoop.chat.dto.ChatFrozenContext;
import com.zoop.common.exception.CustomException;
import com.zoop.common.exception.ErrorCode;
import com.zoop.graph.read.GraphContextLookup;
import com.zoop.graph.read.PublicGraphReader;
import com.zoop.graph.version.GraphVersionSelector;
import java.util.ArrayList;
import java.util.LinkedHashMap;
import java.util.LinkedHashSet;
import java.util.List;
import java.util.Map;
import java.util.Set;
import org.springframework.stereotype.Component;

/**
 * Fixes the selection of a new question at its first acceptance (OpenAPI {@code aiJobs}): the public graph version, and
 * each selected company, issue, edge or evidence as it is publicly visible in that version.
 *
 * <p>A selection, an explicit {@code graphVersion} or an {@code asOf} is read through the same pinned path as the public
 * graph API; an id that is not visible there is {@code INVALID_REQUEST}, an unavailable version or snapshot keeps its own
 * error and is never replaced by another version. A question without any of these pins the active version when one exists
 * and otherwise freezes no graph: a general question does not need the graph and the job reports the missing graph when a
 * requirement does.
 */
@Component
public class ChatContextFreezer {
    /** The answer reads at most this many documents; the frozen count is capped to what can be used. */
    static final int MAX_EVIDENCE = 20;

    private final PublicGraphReader reader;
    private final GraphVersionSelector selector;

    public ChatContextFreezer(PublicGraphReader reader, GraphVersionSelector selector) {
        this.reader = reader;
        this.selector = selector;
    }

    /** The frozen context, the company ids it involves ({@code context_company_ids}) and the pinned version id (or null). */
    public record Frozen(ChatFrozenContext context, List<String> companyIds, String graphVersionId) { }

    public Frozen freeze(ChatContextRequest request) {
        ChatContextRequest selection = request == null ? ChatContextRequest.EMPTY : request;
        boolean selected = !selection.contextIds().isEmpty() || !selection.evidenceIds().isEmpty();
        if (!selected && selection.asOf() == null && selection.graphVersion() == null) {
            String active = activeVersion();
            return new Frozen(new ChatFrozenContext(List.of(), 0, selection.period(), null, active), List.of(), active);
        }
        if (!selected) {
            // Nothing to look up: pin the requested version without loading its snapshot.
            var version = selector.select(null, selection.graphVersion(), selection.asOf());
            String id = version.version().id();
            return new Frozen(new ChatFrozenContext(List.of(), 0, selection.period(),
                    version.asOfRequested() ? version.asOf() : null, id), List.of(), id);
        }

        var pinned = reader.read(null, selection.graphVersion(), selection.asOf());
        var lookup = new GraphContextLookup(pinned.graph());
        Map<String, GraphContextLookup.Target> targets = new LinkedHashMap<>();
        for (String id : selection.contextIds()) targets.put(id, find(lookup, id));
        List<GraphContextLookup.Target> evidence = new ArrayList<>();
        for (String id : selection.evidenceIds()) {
            var target = find(lookup, id);
            if (!"evidence".equals(target.kind())) throw new CustomException(ErrorCode.INVALID_REQUEST);
            evidence.add(target);
        }

        // The evidence the question may use: what the selected targets carry, narrowed to explicit references if any.
        Set<String> pool = new LinkedHashSet<>();
        targets.values().forEach(t -> pool.addAll(t.evidenceIds()));
        if (!evidence.isEmpty()) {
            Set<String> wanted = new LinkedHashSet<>(evidence.stream().map(GraphContextLookup.Target::id).toList());
            if (targets.isEmpty()) pool.addAll(wanted);
            else pool.retainAll(wanted);
        }

        List<ChatContextItem> items = new ArrayList<>();
        Set<String> companyIds = new LinkedHashSet<>();
        targets.values().forEach(t -> {
            items.add(new ChatContextItem(t.id(), t.kind(), t.label()));
            companyIds.addAll(t.companyIds());
        });
        evidence.stream().filter(t -> !targets.containsKey(t.id()))
                .forEach(t -> items.add(new ChatContextItem(t.id(), t.kind(), t.label())));

        var version = pinned.selected();
        return new Frozen(new ChatFrozenContext(List.copyOf(items), Math.min(pool.size(), MAX_EVIDENCE),
                selection.period(), version.asOfRequested() ? version.asOf() : null, version.version().id()),
                List.copyOf(companyIds), version.version().id());
    }

    private String activeVersion() {
        try {
            return selector.select(null, null, null).version().id();
        } catch (CustomException unavailable) {
            if (unavailable.getErrorCode() == ErrorCode.VERSION_UNAVAILABLE) return null;
            throw unavailable;
        }
    }

    private static GraphContextLookup.Target find(GraphContextLookup lookup, String id) {
        return lookup.find(id).orElseThrow(() -> new CustomException(ErrorCode.INVALID_REQUEST));
    }
}
