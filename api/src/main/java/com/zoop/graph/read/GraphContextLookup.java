package com.zoop.graph.read;

import com.zoop.graph.snapshot.PublicGraphSnapshot;
import java.util.Collection;
import java.util.HashSet;
import java.util.LinkedHashSet;
import java.util.List;
import java.util.Map;
import java.util.Objects;
import java.util.Optional;
import java.util.Set;
import java.util.function.Function;
import java.util.stream.Collectors;
import java.util.stream.Stream;

/**
 * Looks up the graph targets a member selected (company, issue, display edge or evidence) in one pinned, filtered display
 * graph, for callers outside this package that freeze a selection (the chat job context). Only what is publicly visible in
 * that graph is found; an excluded or unknown id is absent. Evidence follows {@link GraphEvidenceSnapshotReader}: it is
 * visible only while the filtered snapshot lists it AND a visible issue or relation still cites it.
 */
public final class GraphContextLookup {
    /** One selected target: its kind, display label, linked company ids and the evidence it carries. */
    public record Target(String id, String kind, String label, List<String> companyIds, List<String> evidenceIds) { }

    private final DisplayGraph graph;
    private final Map<String, PublicGraphSnapshot.Evidence> evidence;
    private final Map<String, PublicGraphSnapshot.Article> articles;
    private final Set<String> cited = new HashSet<>();

    public GraphContextLookup(DisplayGraph graph) {
        this.graph = graph;
        this.evidence = graph.snapshot.evidence().stream()
                .collect(Collectors.toMap(PublicGraphSnapshot.Evidence::evidenceId, Function.identity(), (a, b) -> a));
        this.articles = graph.snapshot.articles().stream()
                .collect(Collectors.toMap(PublicGraphSnapshot.Article::articleId, Function.identity(), (a, b) -> a));
        graph.snapshot.issues().forEach(i -> {
            cited.addAll(i.evidenceIds());
            cited.addAll(i.geographyEvidenceIds());
        });
        graph.snapshot.relations().forEach(r -> cited.addAll(r.evidenceIds()));
    }

    public Optional<Target> find(String id) {
        var company = graph.companies.get(id);
        if (company != null) {
            Set<String> ids = new LinkedHashSet<>();
            graph.edges.values().stream().filter(e -> !e.derived() && (id.equals(e.source()) || id.equals(e.target())))
                    .forEach(e -> ids.addAll(e.evidenceIds()));
            return Optional.of(new Target(id, "company", company.label(), List.of(id), visible(ids)));
        }
        var issue = graph.issues.get(id);
        if (issue != null) {
            return Optional.of(new Target(id, "issue", issue.label(),
                    List.copyOf(graph.issueCompanies.getOrDefault(id, Set.of())), visible(issue.evidenceIds())));
        }
        var edge = graph.edges.get(id);
        if (edge != null) {
            List<String> companies = Stream.of(edge.source(), edge.target())
                    .filter(graph.companies::containsKey).toList();
            Set<String> ids = new LinkedHashSet<>(edge.evidenceIds());
            if (edge.derived()) {
                // A shared-issue pair carries no relation evidence of its own: it rests on the issues it goes through.
                edge.via().stream().map(graph.issues::get).filter(Objects::nonNull)
                        .forEach(i -> ids.addAll(i.evidenceIds()));
            }
            return Optional.of(new Target(id, "edge", label(edge.source()) + " – " + label(edge.target()),
                    companies, visible(ids)));
        }
        var found = evidence.get(id);
        if (found != null && cited.contains(id)) {
            var article = articles.get(found.articleId());
            String title = article == null || article.title() == null || article.title().isBlank() ? "근거" : article.title();
            return Optional.of(new Target(id, "evidence", title, List.of(), List.of(id)));
        }
        return Optional.empty();
    }

    /** Only visible evidence: an excluded or withdrawn reference is never counted. */
    private List<String> visible(Collection<String> ids) {
        return ids.stream().filter(id -> evidence.containsKey(id) && cited.contains(id)).distinct().toList();
    }

    private String label(String id) {
        var company = graph.companies.get(id);
        if (company != null) return company.label();
        var issue = graph.issues.get(id);
        return issue != null ? issue.label() : id;
    }
}
