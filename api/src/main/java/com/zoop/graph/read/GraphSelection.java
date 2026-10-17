package com.zoop.graph.read;

import com.zoop.graph.snapshot.PublicGraphSnapshot.Issue;
import java.util.ArrayList;
import java.util.LinkedHashMap;
import java.util.LinkedHashSet;
import java.util.List;
import java.util.Map;
import java.util.Set;

/**
 * Picks the nodes of one response (prototype {@code graph.select_graph}). Without focus: the whole public graph,
 * newest issues first. With focus companies: the ego graph, where one hop adds the focus' issues and then their
 * companies; without depth it keeps hopping (FOLLOWS joins an issue to its neighbours within the same hop).
 * Focus companies are always kept, even with no relations. Past {@code limit} nodes the result is truncated.
 */
final class GraphSelection {
    record Result(Map<String, Kind> nodes, boolean truncated) { }

    enum Kind { COMPANY, ISSUE }

    private GraphSelection() {
    }

    static Result select(DisplayGraph g, List<String> focus, Integer depth, int limit) {
        List<Issue> candidates = focus.isEmpty()
                ? g.issues.values().stream().sorted(DisplayGraph.RECENT).toList()
                : egoIssues(g, focus, depth);
        Map<String, Kind> nodes = new LinkedHashMap<>();
        boolean truncated = false;
        for (String companyId : focus) {
            if (nodes.size() >= limit) {
                truncated = true;
                break;
            }
            nodes.put(companyId, Kind.COMPANY);
        }
        for (Issue issue : candidates) {
            List<String> missing = g.issueCompanies.getOrDefault(issue.issueId(), Set.of()).stream()
                    .filter(c -> !nodes.containsKey(c)).toList();
            if (nodes.size() + 1 + missing.size() > limit) {
                truncated = true;
                continue;
            }
            nodes.put(issue.issueId(), Kind.ISSUE);
            missing.forEach(c -> nodes.put(c, Kind.COMPANY));
        }
        // A follow-up stays next to the issue it follows, without pulling in more companies.
        for (String issueId : nodes.entrySet().stream().filter(e -> e.getValue() == Kind.ISSUE).map(Map.Entry::getKey).toList()) {
            for (String neighbour : g.followsNeighbours.getOrDefault(issueId, Set.of())) {
                if (nodes.containsKey(neighbour)) continue;
                if (nodes.size() >= limit) truncated = true;
                else nodes.put(neighbour, Kind.ISSUE);
            }
        }
        return new Result(nodes, truncated);
    }

    private static List<Issue> egoIssues(DisplayGraph g, List<String> focus, Integer depth) {
        Map<String, Issue> ordered = new LinkedHashMap<>();
        Set<String> seen = new LinkedHashSet<>(focus);
        List<String> frontier = new ArrayList<>(focus);
        int hops = 0;
        while (!frontier.isEmpty() && (depth == null || hops < depth)) {
            Map<String, Issue> fresh = new LinkedHashMap<>();
            for (String companyId : frontier) {
                for (Issue issue : g.issuesOf(companyId)) {
                    if (!ordered.containsKey(issue.issueId())) fresh.put(issue.issueId(), issue);
                }
            }
            if (depth == null) followClosure(g, fresh, ordered);
            List<Issue> level = fresh.values().stream().sorted(DisplayGraph.RECENT).toList();
            level.forEach(i -> ordered.put(i.issueId(), i));
            frontier = new ArrayList<>();
            for (Issue issue : level) {
                for (String companyId : g.issueCompanies.getOrDefault(issue.issueId(), Set.of())) {
                    if (seen.add(companyId)) frontier.add(companyId);
                }
            }
            hops++;
        }
        return List.copyOf(ordered.values());
    }

    private static void followClosure(DisplayGraph g, Map<String, Issue> fresh, Map<String, Issue> ordered) {
        List<String> stack = new ArrayList<>(fresh.keySet());
        while (!stack.isEmpty()) {
            String current = stack.remove(stack.size() - 1);
            for (String neighbour : g.followsNeighbours.getOrDefault(current, Set.of())) {
                if (!fresh.containsKey(neighbour) && !ordered.containsKey(neighbour)) {
                    fresh.put(neighbour, g.issues.get(neighbour));
                    stack.add(neighbour);
                }
            }
        }
    }
}
