package com.zoop.graph.read;

import java.util.ArrayList;
import java.util.List;
import java.util.Objects;
import java.util.Set;
import java.util.stream.Stream;

/**
 * What changed between two publicly visible graphs (Q05 period comparison): the companies, issues and approved relations
 * (display edges) one has and the other does not. Both graphs are read through {@link PublicGraphReader}, so each already
 * has the current public exclusions applied. Derived shared-issue pairs follow from the issues and are not listed, and an
 * edge that stayed is not a change even when its evidence or role changed.
 */
public final class GraphChanges {
    /**
     * One change: {@code kind} is {@code company}, {@code issue} or {@code edge}; {@code change} is {@code added} or
     * {@code removed}. Evidence is that of the newer graph, visible there, and only for what was added: a removed item has
     * none to show now.
     */
    public record Change(String id, String kind, String change, String label, List<String> companyIds,
            List<String> evidenceIds) {
        public Change {
            companyIds = List.copyOf(companyIds);
            evidenceIds = List.copyOf(evidenceIds);
        }
    }

    private GraphChanges() {
    }

    /** Additions first, then removals; within each, companies, issues, then edges, in the graph's own order. */
    public static List<Change> between(DisplayGraph before, DisplayGraph after) {
        var newer = new GraphContextLookup(after);
        List<Change> changes = new ArrayList<>();
        for (String kind : List.of("company", "issue", "edge")) {
            Set<String> old = Set.copyOf(ids(before, kind));
            for (String id : ids(after, kind)) {
                if (old.contains(id)) continue;
                var target = newer.find(id).orElseThrow();
                changes.add(new Change(id, kind, "added", label(after, kind, id), target.companyIds(), target.evidenceIds()));
            }
        }
        for (String kind : List.of("company", "issue", "edge")) {
            Set<String> now = Set.copyOf(ids(after, kind));
            for (String id : ids(before, kind)) {
                if (now.contains(id)) continue;
                changes.add(new Change(id, kind, "removed", label(before, kind, id), companies(before, kind, id), List.of()));
            }
        }
        return List.copyOf(changes);
    }

    private static List<String> ids(DisplayGraph graph, String kind) {
        return switch (kind) {
            case "company" -> List.copyOf(graph.companies.keySet());
            case "issue" -> List.copyOf(graph.issues.keySet());
            default -> graph.edges.values().stream().filter(e -> !e.derived()).map(DisplayGraph.Edge::id).toList();
        };
    }

    private static String label(DisplayGraph graph, String kind, String id) {
        return switch (kind) {
            case "company" -> graph.companies.get(id).label();
            case "issue" -> graph.issues.get(id).label();
            default -> {
                var edge = graph.edges.get(id);
                String what = Stream.of(edge.summary(), edge.role(), edge.relationType()).filter(Objects::nonNull)
                        .findFirst().orElse(edge.relationType());
                yield name(graph, edge.source()) + " – " + name(graph, edge.target()) + " (" + what + ")";
            }
        };
    }

    private static List<String> companies(DisplayGraph graph, String kind, String id) {
        return switch (kind) {
            case "company" -> List.of(id);
            case "issue" -> List.copyOf(graph.issueCompanies.getOrDefault(id, Set.of()));
            default -> {
                var edge = graph.edges.get(id);
                yield Stream.of(edge.source(), edge.target()).filter(graph.companies::containsKey).toList();
            }
        };
    }

    private static String name(DisplayGraph graph, String id) {
        var company = graph.companies.get(id);
        if (company != null) return company.label();
        var issue = graph.issues.get(id);
        return issue != null ? issue.label() : id;
    }
}
