package com.zoop.chat.tool;

import com.zoop.chat.service.ChatEvidenceAccess;
import com.zoop.common.exception.CustomException;
import com.zoop.document.evidence.service.EvidenceService.Readability;
import com.zoop.graph.read.GraphContextLookup;
import com.zoop.graph.read.GraphPathLookup;
import com.zoop.graph.read.PublicGraphReader;
import java.util.ArrayList;
import java.util.LinkedHashMap;
import java.util.LinkedHashSet;
import java.util.List;
import java.util.Map;
import java.util.Set;
import org.springframework.dao.DataAccessException;
import org.springframework.stereotype.Component;
import org.springframework.transaction.TransactionException;

/**
 * {@code graph.path.read} (Q04): how the first target connects to each other target in the run's pinned public graph, read
 * through the same path as the public graph API ({@link PublicGraphReader}: pinned version, asOf filter, current
 * exclusions). A connection is the shortest path of stored, approved edges ({@link GraphPathLookup}) of at most
 * {@value #MAX_HOPS} hops, counted like the map's depth: company – issue – company is one hop (design summary, graph
 * source; implementation plan stage 4). At most {@value #MAX_ELEMENTS} nodes and {@value #MAX_ELEMENTS} edges are returned;
 * more marks the result truncated.
 *
 * <ul>
 * <li>Items are the path in order: its companies and issues, then the display edges between them, each once. An edge stays
 * even when none of its evidence is readable now; it then carries no evidence and the answer cannot cite it.</li>
 * <li>A pair that is proven unconnected adds nothing; when no pair connects, the result is empty and not truncated, so the
 * answer may say no connection was found in the graph. A pair whose search reached the hop limit marks the result
 * truncated: a longer connection may exist, so it is never "none".</li>
 * <li>The first target is the anchor and is never replaced: when it is not a visible company or issue, no pair is read and
 * the visible others are returned alone, so the answer can say the anchor is missing instead of describing other
 * companies' connections. Any other target that is not visible is absent. With no other visible target there is no pair:
 * the anchor itself is returned so the answer can say which second target is missing.</li>
 * <li>Evidence passed on is what the public evidence read can read now at the version: edges first in path order, then the
 * issues on the path, deduplicated, within the request's evidence scope and capped at the request limit.</li>
 * <li>Each pair read is also reported on its own ({@link ChatToolPath}): found with its steps in order (edge, stored
 * direction, relation, role and that edge's evidence passed on), none, or cut. So a pair cut by the hop limit stays apart
 * from a pair proven unconnected even when another pair was found, and the answer can tie each step to its own evidence.</li>
 * </ul>
 * A run without a frozen graph, an unreadable version or database and an evidence state that could not be checked are
 * {@link ChatToolUnavailable}, never an empty result.
 */
@Component
public class GraphPathTool implements ChatTool {
    static final int MAX_HOPS = 3;
    static final int MAX_ELEMENTS = 50;

    private final PublicGraphReader reader;
    private final ChatEvidenceAccess access;

    public GraphPathTool(PublicGraphReader reader, ChatEvidenceAccess access) {
        this.reader = reader;
        this.access = access;
    }

    @Override
    public ChatCapability capability() {
        return ChatCapability.GRAPH_PATH_READ;
    }

    @Override
    public ChatToolOutput read(ChatToolScope scope, ChatToolRequest request) {
        if (scope.graphVersionId() == null) throw new ChatToolUnavailable("the question froze no graph version");
        GraphContextLookup lookup;
        GraphPathLookup paths;
        String version;
        try {
            var pinned = reader.readPinned(scope.graphVersionId(), scope.asOf(), scope.asOf() != null);
            lookup = new GraphContextLookup(pinned.graph());
            paths = new GraphPathLookup(pinned.graph());
            version = pinned.selected().version().id();
        } catch (CustomException | DataAccessException | TransactionException unavailable) {
            throw new ChatToolUnavailable("graph version " + scope.graphVersionId() + " cannot be read", unavailable);
        }

        String anchor = request.targets().getFirst();
        List<String> others = request.targets().stream().skip(1).filter(id -> !id.equals(anchor)).filter(paths::isNode)
                .distinct().toList();
        Map<String, GraphContextLookup.Target> nodes = new LinkedHashMap<>();
        Map<String, GraphContextLookup.Target> edges = new LinkedHashMap<>();
        boolean truncated = false;
        if (!paths.isNode(anchor) || others.isEmpty()) {
            // No pair to read: what is visible is returned alone and the missing side stays missing.
            for (String id : paths.isNode(anchor) ? List.of(anchor) : others) {
                lookup.find(id).ifPresent(target -> nodes.put(target.id(), target));
            }
        }
        Map<String, GraphPathLookup.Result> pairs = new LinkedHashMap<>();
        for (String other : paths.isNode(anchor) ? others : List.<String>of()) {
            var result = paths.shortest(anchor, other, MAX_HOPS);
            pairs.putIfAbsent(other, result);
            if (result.status() == GraphPathLookup.Status.CUT) truncated = true;
            var path = result.path().orElse(null);
            if (path == null) continue;
            for (String id : path.nodeIds()) {
                if (nodes.containsKey(id)) continue;
                if (nodes.size() >= MAX_ELEMENTS) truncated = true;
                else lookup.find(id).ifPresent(target -> nodes.put(id, target));
            }
            for (String id : path.edgeIds()) {
                if (edges.containsKey(id)) continue;
                if (edges.size() >= MAX_ELEMENTS) truncated = true;
                else lookup.find(id).ifPresent(target -> edges.put(id, target));
            }
        }

        // Evidence order: the edges that make the connection, then the issues on it.
        List<GraphContextLookup.Target> sources = new ArrayList<>(edges.values());
        nodes.values().stream().filter(t -> "issue".equals(t.kind())).forEach(sources::add);
        Set<String> passed = new LinkedHashSet<>();
        Set<String> checked = new LinkedHashSet<>();
        Map<String, List<String>> carried = new LinkedHashMap<>();
        for (GraphContextLookup.Target target : sources) {
            List<String> evidence = new ArrayList<>();
            for (String evidenceId : target.evidenceIds()) {
                if (Thread.currentThread().isInterrupted()) throw new ChatToolUnavailable("read interrupted");
                if (request.evidenceScope() != null && !request.evidenceScope().contains(evidenceId)) continue;
                if (passed.contains(evidenceId)) {
                    evidence.add(evidenceId);
                } else if (passed.size() >= request.limit()) {
                    if (!checked.contains(evidenceId)) truncated = true;
                } else if (checked.add(evidenceId) && readable(scope, version, evidenceId)) {
                    passed.add(evidenceId);
                    evidence.add(evidenceId);
                }
            }
            carried.put(target.id(), evidence);
        }

        List<ChatToolItem> items = new ArrayList<>();
        for (GraphContextLookup.Target target : nodes.values()) {
            items.add(new ChatToolItem(target.id(), target.kind(), target.label(), target.companyIds(),
                    carried.getOrDefault(target.id(), List.of())));
        }
        for (GraphContextLookup.Target target : edges.values()) {
            items.add(new ChatToolItem(target.id(), target.kind(), target.label(), target.companyIds(),
                    carried.getOrDefault(target.id(), List.of())));
        }
        List<ChatToolPath> read = new ArrayList<>();
        pairs.forEach((other, result) -> read.add(path(paths, anchor, other, result, carried)));
        return new ChatToolOutput(version, items, List.copyOf(passed), truncated, false, read);
    }

    private static ChatToolPath path(GraphPathLookup paths, String anchor, String other, GraphPathLookup.Result result,
            Map<String, List<String>> carried) {
        return switch (result.status()) {
            case NONE -> new ChatToolPath(anchor, other, ChatToolPath.NONE, List.of());
            case CUT -> new ChatToolPath(anchor, other, ChatToolPath.CUT, List.of());
            case FOUND -> {
                List<ChatToolPath.Step> steps = new ArrayList<>();
                for (String edgeId : result.path().orElseThrow().edgeIds()) {
                    var edge = paths.edge(edgeId).orElseThrow();
                    steps.add(new ChatToolPath.Step(edgeId, edge.source(), edge.target(), edge.relationType(), edge.role(),
                            carried.getOrDefault(edgeId, List.of())));
                }
                yield new ChatToolPath(anchor, other, ChatToolPath.FOUND, steps);
            }
        };
    }

    private boolean readable(ChatToolScope scope, String version, String evidenceId) {
        Readability readability = access.readability(evidenceId, version, scope.asOf(), scope.traceId());
        if (readability == Readability.UNAVAILABLE) {
            throw new ChatToolUnavailable("evidence " + evidenceId + " could not be checked");
        }
        return readability == Readability.READABLE;
    }
}
