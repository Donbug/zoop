package com.zoop.graph.read;

import java.util.ArrayDeque;
import java.util.ArrayList;
import java.util.Collections;
import java.util.HashMap;
import java.util.List;
import java.util.Map;
import java.util.Optional;
import java.util.TreeMap;

/**
 * Shortest connections between two graph nodes (companies and issues) of one pinned, filtered display graph, for the chat
 * path tool. A hop is the map's {@code depth} hop (design summary, graph source): a company to another company through one
 * issue they both have, i.e. two stored edges, an issue to a company it involves or is structurally related to. Only those
 * stored, approved display edges connect nodes, as in a map read with an explicit depth: a "follows" link between issues
 * is not a step, and a derived "shares an issue" pair is the same connection as its two stored edges, which carry the
 * evidence.
 *
 * <p>The search is breadth first and deterministic: neighbours are visited in id order, so the same graph always gives the
 * same path. It stops after {@code maxHops} hops ({@code 2 * maxHops} edges); a search that still had nodes to expand there
 * is {@link Status#CUT}, never "no connection".
 */
public final class GraphPathLookup {
    /** {@code FOUND}: a path of at most the hop limit. {@code NONE}: proven unconnected. {@code CUT}: not found within the limit. */
    public enum Status { FOUND, NONE, CUT }

    /** The nodes from start to end and the display edge ids between them ({@code edgeIds.size() == nodeIds.size() - 1}). */
    public record Path(List<String> nodeIds, List<String> edgeIds) { }

    public record Result(Status status, Optional<Path> path) { }

    private record Link(String node, String edgeId) { }

    private final DisplayGraph graph;
    private final Map<String, List<Link>> adjacency = new HashMap<>();

    public GraphPathLookup(DisplayGraph graph) {
        this.graph = graph;
        Map<String, TreeMap<String, Link>> sorted = new HashMap<>();
        for (DisplayGraph.Edge edge : graph.edges.values()) {
            if (edge.derived() || !DisplayGraph.COMPANY_LINKS.contains(edge.relationType())
                    || !isNode(edge.source()) || !isNode(edge.target())) continue;
            sorted.computeIfAbsent(edge.source(), k -> new TreeMap<>())
                    .putIfAbsent(edge.target() + "\u0000" + edge.id(), new Link(edge.target(), edge.id()));
            sorted.computeIfAbsent(edge.target(), k -> new TreeMap<>())
                    .putIfAbsent(edge.source() + "\u0000" + edge.id(), new Link(edge.source(), edge.id()));
        }
        sorted.forEach((node, links) -> adjacency.put(node, List.copyOf(links.values())));
    }

    /** A display edge of this graph by id. */
    public Optional<DisplayGraph.Edge> edge(String id) {
        return Optional.ofNullable(graph.edges.get(id));
    }

    /** A visible company or issue of this graph. */
    public boolean isNode(String id) {
        return graph.companies.containsKey(id) || graph.issues.containsKey(id);
    }

    public Result shortest(String from, String to, int maxHops) {
        if (!isNode(from) || !isNode(to)) return new Result(Status.NONE, Optional.empty());
        if (from.equals(to)) return new Result(Status.FOUND, Optional.of(new Path(List.of(from), List.of())));
        Map<String, Link> parent = new HashMap<>();
        parent.put(from, null);
        ArrayDeque<String> frontier = new ArrayDeque<>(List.of(from));
        for (int edges = 0; edges < 2 * maxHops && !frontier.isEmpty(); edges++) {
            ArrayDeque<String> next = new ArrayDeque<>();
            for (String node : frontier) {
                for (Link link : adjacency.getOrDefault(node, List.of())) {
                    if (parent.containsKey(link.node())) continue;
                    parent.put(link.node(), new Link(node, link.edgeId()));
                    if (link.node().equals(to)) return new Result(Status.FOUND, Optional.of(path(parent, to)));
                    next.add(link.node());
                }
            }
            frontier = next;
        }
        // Nodes left to expand at the limit mean a longer path may exist: that is a cut search, not "unconnected".
        boolean expandable = frontier.stream().anyMatch(node -> adjacency.getOrDefault(node, List.of()).stream()
                .anyMatch(link -> !parent.containsKey(link.node())));
        return new Result(expandable ? Status.CUT : Status.NONE, Optional.empty());
    }

    private static Path path(Map<String, Link> parent, String to) {
        List<String> nodes = new ArrayList<>();
        List<String> edges = new ArrayList<>();
        String node = to;
        while (node != null) {
            nodes.add(node);
            Link step = parent.get(node);
            if (step == null) break;
            edges.add(step.edgeId());
            node = step.node();
        }
        Collections.reverse(nodes);
        Collections.reverse(edges);
        return new Path(List.copyOf(nodes), List.copyOf(edges));
    }
}
